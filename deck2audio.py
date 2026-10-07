#!/usr/bin/env python3
"""deck2audio — turn a PowerPoint deck into a narrated MP3, with a human-in-the-loop LLM step.

Stages (each resumable; state lives in the project folder):
  1. extract   Pull slide text + speaker notes from a .pptx
  2. research  Generate LLM prompts for academic sources & real-world examples; you paste back + approve
  3. script    Generate LLM prompt(s) to draft the spoken script; you paste back + approve
  4. tts       Synthesize the approved script with a neural female voice and export an MP3

Run everything:  python deck2audio.py run deck.pptx
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

DEFAULT_VOICE = "en-US-AvaMultilingualNeural"
WORDS_PER_MINUTE = 150
SLIDE_HEADING = re.compile(r"^\s*#{1,6}\s*Slide\s+(\d+)\b.*$", re.IGNORECASE | re.MULTILINE)


# ----------------------------------------------------------------------------- helpers

def project_dir_for(deck: Path) -> Path:
    return deck.with_suffix("").parent / f"{deck.stem}_narration"


def load_state(proj: Path) -> dict:
    f = proj / "state.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_state(proj: Path, state: dict) -> None:
    (proj / "state.json").write_text(json.dumps(state, indent=2))


def load_slides(proj: Path) -> list[dict]:
    f = proj / "slides.json"
    if not f.exists():
        sys.exit(f"No slides.json in {proj}. Run the 'extract' stage first.")
    return json.loads(f.read_text())


def banner(title: str) -> None:
    print("\n" + "=" * 78 + f"\n  {title}\n" + "=" * 78)


def ask(question: str, choices: str) -> str:
    """Single-key style prompt; `choices` like 'ARES' — first letter is default."""
    opts = "/".join(c if i else c.upper() for i, c in enumerate(choices.lower()))
    while True:
        ans = input(f"{question} [{opts}]: ").strip().lower()
        if not ans:
            return choices[0].lower()
        if ans[0] in choices.lower():
            return ans[0]


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode(), check=False)
            return True
    return False


def read_clipboard() -> str | None:
    for cmd in (["pbpaste"], ["wl-paste"], ["xclip", "-selection", "clipboard", "-o"]):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, capture_output=True, check=False).stdout.decode()
    return None


def edit_in_editor(text: str, suffix: str = ".md") -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("nano" if shutil.which("nano") else "vi")
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as tmp:
        tmp.write(text)
        path = tmp.name
    subprocess.call([*editor.split(), path])
    out = Path(path).read_text()
    os.unlink(path)
    return out


def collect_response() -> str:
    """Get an LLM response from the user.

    Clipboard is the default because terminals (esp. macOS) truncate very long pasted lines.
    """
    print(textwrap.dedent("""
        How do you want to provide the LLM's response?
          [Enter]  read it from the clipboard (copy the full response first)
          e        open your $EDITOR and paste it there
          p        paste directly here, then type END on its own line
          f        load it from a file path
    """))
    while True:
        mode = input("> ").strip().lower()
        if mode in ("", "c"):
            text = read_clipboard()
            if text is None:
                print("No clipboard tool available; choose e, p, or f.")
                continue
        elif mode == "e":
            text = edit_in_editor("<!-- Paste the LLM response below, save, and close. -->\n\n")
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        elif mode == "p":
            lines = []
            try:
                while (line := input()) .strip() != "END":
                    lines.append(line)
            except EOFError:
                pass
            text = "\n".join(lines)
        elif mode == "f":
            p = Path(input("File path: ").strip().strip("'\"")).expanduser()
            if not p.exists():
                print("File not found.")
                continue
            text = p.read_text()
        else:
            continue
        if text.strip():
            return text.strip()
        print("Got an empty response — try again.")


def human_in_the_loop(prompt: str, label: str, validate=None) -> str | None:
    """Show a prompt, copy it, wait for the pasted response, and require explicit approval.

    Returns the approved text, or None if the user skips this step.
    """
    banner(label)
    print(prompt)
    print("-" * 78)
    if copy_to_clipboard(prompt):
        print("✓ The prompt above has been copied to your clipboard.")
    print("Paste it into your LLM of choice (ChatGPT, Claude, Copilot, Gemini, …).")
    if ask("Ready to provide the response, or skip this step?", "rs") == "s":
        return None

    response = collect_response()
    while True:
        problems = validate(response) if validate else []
        banner(f"Review — {label}")
        print(response)
        print("-" * 78)
        print(f"{len(response.split())} words.")
        for p in problems:
            print(f"⚠  {p}")
        choice = ask("[A]pprove, [E]dit, [R]e-paste a new response, [S]kip?", "aers")
        if choice == "a":
            if problems and ask("There are warnings above. Approve anyway?", "ny") == "n":
                continue
            return response
        if choice == "e":
            response = edit_in_editor(response).strip()
        elif choice == "r":
            print("\n(Tip: ask the LLM to revise, then copy its new answer.)")
            response = collect_response()
        else:
            return None


# ----------------------------------------------------------------------------- stage 1: extract

def shape_text(shape) -> list[str]:
    out: list[str] = []
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            t = "".join(r.text for r in para.runs).strip()
            if t:
                out.append(("  " * para.level) + t)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    if shape.shape_type == 6:  # group
        for s in shape.shapes:
            out.extend(shape_text(s))
    return out


def extract(deck: Path, proj: Path) -> list[dict]:
    from pptx import Presentation

    prs = Presentation(str(deck))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        body: list[str] = []
        for shape in slide.shapes:
            if slide.shapes.title is not None and shape.shape_id == slide.shapes.title.shape_id:
                continue
            body.extend(shape_text(shape))
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        slides.append({"number": i, "title": title, "body": body, "notes": notes})

    proj.mkdir(parents=True, exist_ok=True)
    (proj / "slides.json").write_text(json.dumps(slides, indent=2, ensure_ascii=False))
    (proj / "slides.md").write_text(slides_as_markdown(slides))
    state = load_state(proj)
    state.update({"deck": str(deck.resolve()), "extracted": True})
    save_state(proj, state)
    print(f"✓ Extracted {len(slides)} slides → {proj / 'slides.md'}")
    return slides


def slides_as_markdown(slides: list[dict]) -> str:
    parts = []
    for s in slides:
        parts.append(f"### Slide {s['number']}: {s['title'] or '(untitled)'}")
        if s["body"]:
            parts.append("Slide text:\n" + "\n".join(f"- {b}" for b in s["body"]))
        parts.append("Speaker notes:\n" + (s["notes"] or "(none)"))
        parts.append("")
    return "\n".join(parts)


# ----------------------------------------------------------------------------- stage 2: research

RESEARCH_PROMPTS = {
    "academic": """\
You are a research assistant helping me prepare a narrated presentation.
Below is the full content of my slide deck (slide text + speaker notes).

TASK: Suggest academic grounding that would make the narration more insightful.
For the slides where it genuinely adds value (not every slide), provide:
  • Key theories, frameworks, or seminal studies (author(s), year, venue)
  • One or two sentences on the core finding and HOW it connects to the slide
  • A short, quotable takeaway phrased for a spoken audience

RULES:
  • Only cite sources you are confident exist. If unsure, say "verify" next to it.
  • No fabricated statistics. Prefer well-known, verifiable work.
  • Organize your answer by "Slide N" headings so it maps back to the deck.
  • Keep it concise: at most ~3 items per slide.

DECK:
{deck}
""",
    "examples": """\
You are helping me make a presentation memorable for a general professional audience.
Below is the full content of my slide deck (slide text + speaker notes).

TASK: For the slides where it fits, suggest vivid real-world examples, case studies,
analogies, or short stories that illustrate the point. For each:
  • A 2–4 sentence description told in a way that works when spoken aloud
  • Why it illustrates the slide's idea
  • Approximate date/company/person, so I can verify it

RULES:
  • Use real, verifiable events; flag anything uncertain with "verify".
  • Favor diverse industries and recent examples (last ~10 years) where possible.
  • Organize your answer by "Slide N" headings.
  • At most ~2 examples per slide; skip slides where an example would feel forced.

DECK:
{deck}
""",
}


def research(proj: Path) -> None:
    slides = load_slides(proj)
    state = load_state(proj)
    rdir = proj / "research"
    rdir.mkdir(exist_ok=True)
    deck_md = slides_as_markdown(slides)
    labels = {"academic": "Academic resources & theory", "examples": "Real-world examples & stories"}

    for key, template in RESEARCH_PROMPTS.items():
        out = rdir / f"{key}.md"
        status = state.get("research", {}).get(key)
        if status in ("approved", "skipped"):
            if ask(f"'{labels[key]}' is already {status}. Redo it?", "ny") == "n":
                continue
        prompt = template.format(deck=deck_md)
        (rdir / f"{key}.prompt.txt").write_text(prompt)
        result = human_in_the_loop(prompt, f"Step 2 · {labels[key]}")
        state.setdefault("research", {})[key] = "approved" if result else "skipped"
        if result:
            out.write_text(result)
            print(f"✓ Saved approved research → {out}")
        elif out.exists():
            out.unlink()
        save_state(proj, state)


def approved_research(proj: Path) -> str:
    state = load_state(proj)
    parts = []
    for key, title in (("academic", "ACADEMIC RESOURCES"), ("examples", "REAL-WORLD EXAMPLES")):
        f = proj / "research" / f"{key}.md"
        if state.get("research", {}).get(key) == "approved" and f.exists():
            parts.append(f"=== APPROVED {title} (use where they genuinely help) ===\n{f.read_text()}")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- stage 3: script

SCRIPT_PROMPT = """\
You are an award-winning keynote speaker and speechwriter. Write the word-for-word
NARRATION SCRIPT for a recorded audio presentation of the slide deck below.
It will be read aloud by a warm, charismatic female text-to-speech voice{audience}.

TONE & STYLE
  • Insightful, engaging, and personable — like a favorite professor who is also a great storyteller.
  • Speak directly to the listener ("you", "we"). Use contractions and natural rhythm.
  • Open with a hook (a question, surprising fact, or short story){intro_note}.
  • Don't just read the bullets — explain WHY they matter, connect ideas, and add insight.
  • Weave in the approved academic sources and real-world examples where they genuinely
    strengthen a point. Cite sources conversationally (e.g., "As Daniel Kahneman showed in 2011…").
  • Smooth spoken transitions between slides. {outro_note}
  • Target roughly {wpm_low}–{wpm_high} words per slide on average, more for dense slides,
    less for title/section slides.{duration_note}

FORMAT — THIS IS PARSED BY A PROGRAM, FOLLOW EXACTLY
  • One section per slide, in order, each starting with a heading line exactly like:
        ## Slide 7
  • Include EVERY slide from {first} to {last}, even if a section is one sentence.
  • Under each heading write ONLY the words to be spoken: plain prose, no bullet points,
    no markdown formatting, no URLs, no stage directions — except you MAY insert
    [pause] on its own where a dramatic beat helps.
  • Spell out symbols and abbreviations the way they should be spoken
    (e.g., "50 percent", "versus", "A I" only if it should be spelled out).
  • Do not add any text before the first heading or after the last section.
{continuity}
{research}

=== SLIDE DECK{batch_note} ===
{deck}
"""


def parse_script(text: str) -> dict[int, str]:
    sections: dict[int, str] = {}
    matches = list(SLIDE_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[int(m.group(1))] = text[m.end():end].strip()
    return sections


def script(proj: Path, batch_size: int, audience: str, minutes: float | None) -> None:
    slides = load_slides(proj)
    state = load_state(proj)
    script_file = proj / "script.md"
    if state.get("script") == "approved" and script_file.exists():
        if ask("An approved script already exists. Redo it?", "ny") == "n":
            return

    research_text = approved_research(proj)
    n = len(slides)
    batches = [slides[i:i + batch_size] for i in range(0, n, batch_size)]
    total_words = int(minutes * WORDS_PER_MINUTE) if minutes else None
    per_slide = (total_words // n) if total_words else 110
    sections: dict[int, str] = {}

    for bi, batch in enumerate(batches):
        first, last = batch[0]["number"], batch[-1]["number"]
        is_first, is_last = bi == 0, bi == len(batches) - 1
        continuity = ""
        if not is_first:
            prev_num = first - 1
            continuity = (
                f"\nCONTINUITY: This is part {bi + 1} of {len(batches)}. The narration so far ended "
                f"with slide {prev_num}:\n\"\"\"\n{sections.get(prev_num, '')[-1200:]}\n\"\"\"\n"
                "Continue seamlessly — do NOT re-introduce the talk or greet the listener again.\n"
            )
        prompt = SCRIPT_PROMPT.format(
            audience=f" to {audience}" if audience else "",
            intro_note=" and briefly preview the journey" if is_first else " — only in part 1; this is a continuation",
            outro_note=("End with a memorable close: recap the big ideas and a call to action."
                        if is_last else "Do NOT conclude the talk; more slides follow this batch."),
            wpm_low=max(40, per_slide - 30), wpm_high=per_slide + 40,
            duration_note=(f" The full talk should run about {minutes:g} minutes (~{total_words} words)."
                           if minutes else ""),
            first=first, last=last,
            continuity=continuity,
            research=("\n" + research_text) if research_text else "",
            batch_note=f" (slides {first}–{last} of {n})" if len(batches) > 1 else "",
            deck=slides_as_markdown(batch),
        )
        (proj / f"script_prompt_{bi + 1}.txt").write_text(prompt)
        expected = set(range(first, last + 1))

        def validate(text: str, expected=expected) -> list[str]:
            got = parse_script(text)
            problems = []
            if missing := sorted(expected - got.keys()):
                problems.append(f"Missing sections for slides: {missing}")
            if extra := sorted(got.keys() - expected):
                problems.append(f"Unexpected slide numbers: {extra}")
            if empty := sorted(k for k, v in got.items() if k in expected and not v):
                problems.append(f"Empty sections: {empty}")
            return problems

        label = f"Step 3 · Narration script" + (f" — part {bi + 1}/{len(batches)} (slides {first}–{last})"
                                                 if len(batches) > 1 else "")
        result = human_in_the_loop(prompt, label, validate)
        if result is None:
            print("Script drafting cancelled; nothing saved.")
            return
        sections.update({k: v for k, v in parse_script(result).items() if k in expected})

    full = "\n\n".join(f"## Slide {s['number']}: {s['title'] or ''}".rstrip(": ") + f"\n\n{sections.get(s['number'], '')}"
                       for s in slides)
    words = len(full.split())
    banner("Final review — full narration script")
    print(full)
    print("-" * 78)
    print(f"{words} words ≈ {words / WORDS_PER_MINUTE:.1f} minutes of audio.")
    while True:
        c = ask("Confirm this script for audio production? [A]pprove, [E]dit, [C]ancel", "aec")
        if c == "a":
            break
        if c == "e":
            full = edit_in_editor(full)
            print(f"{len(full.split())} words ≈ {len(full.split()) / WORDS_PER_MINUTE:.1f} minutes.")
        else:
            print("Not approved; draft saved to script.draft.md")
            (proj / "script.draft.md").write_text(full)
            return
    script_file.write_text(full)
    state["script"] = "approved"
    save_state(proj, state)
    print(f"✓ Approved script saved → {script_file}  (you can still hand-edit it before TTS)")


# ----------------------------------------------------------------------------- stage 4: TTS

def clean_for_speech(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[(?!pause\])([^\]]+)\]\([^)]+\)", r"\1", text, flags=re.I)  # md links
    text = re.sub(r"\[(\d+(,\s*\d+)*)\]", "", text)                                 # [1] citations
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*([-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`~]+", "", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def silent_mp3(seconds: float, header: bytes) -> bytes:
    """Build silent MPEG audio frames matching the encoder's own frame header."""
    versions = {0b11: 1, 0b10: 2, 0b00: 2.5}
    b1, b2, b3 = header[1], header[2], header[3]
    ver = versions[(b1 >> 3) & 0b11]
    br_idx, sr_idx = b2 >> 4, (b2 >> 2) & 0b11
    br_table = ([0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] if ver == 1
                else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160])
    sr_table = {1: [44100, 48000, 32000], 2: [22050, 24000, 16000], 2.5: [11025, 12000, 8000]}[ver]
    bitrate, srate = br_table[br_idx] * 1000, sr_table[sr_idx]
    samples = 1152 if ver == 1 else 576
    size = (144 if ver == 1 else 72) * bitrate // srate
    frame = bytes([0xFF, b1 | 0x01, b2 & 0xFD, b3]) + bytes(size - 4)  # no CRC, no padding
    return frame * max(1, round(seconds * srate / samples))


async def synth_chunk(text: str, voice: str, rate: str, pitch: str, retries: int = 3) -> bytes:
    import edge_tts

    for attempt in range(retries):
        try:
            buf = bytearray()
            async for chunk in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            if buf:
                return bytes(buf)
        except Exception as e:  # network hiccups are common; retry
            if attempt == retries - 1:
                raise
            print(f"   retrying after error: {e}")
        await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError("TTS returned no audio")


async def tts_async(proj: Path, voice: str, rate: str, pitch: str, slide_gap: float, pause_len: float,
                    output: Path) -> None:
    script_file = proj / "script.md"
    if not script_file.exists():
        sys.exit("No script.md found. Run the 'script' stage first.")
    state = load_state(proj)
    if state.get("script") != "approved":
        if ask("script.md has not been approved through the workflow. Use it anyway?", "ny") == "n":
            return
    sections = parse_script(script_file.read_text())
    if not sections:
        sys.exit("Couldn't find any '## Slide N' sections in script.md.")

    words = sum(len(v.split()) for v in sections.values())
    banner("Step 4 · Text-to-speech")
    print(f"Voice: {voice}   rate: {rate}   pitch: {pitch}")
    print(f"{len(sections)} slides, {words} words ≈ {words / WORDS_PER_MINUTE:.1f} min")
    if ask("Generate the audio now?", "yn") == "n":
        return

    adir = proj / "audio"
    adir.mkdir(exist_ok=True)
    pieces: list[bytes] = []
    header = None
    pending_silence = 0.0
    for num in sorted(sections):
        text = clean_for_speech(sections[num])
        segments = [s.strip() for s in re.split(r"\[pause\]", text, flags=re.I)]
        slide_audio: list[bytes] = []
        print(f" • Slide {num} ({len(text.split())} words)")
        for si, seg in enumerate(segments):
            if seg:
                audio = await synth_chunk(seg, voice, rate, pitch)
                header = header or audio[:4]
                slide_audio.append(audio)
            if si < len(segments) - 1 and header:
                slide_audio.append(silent_mp3(pause_len, header))
        blob = b"".join(slide_audio)
        (adir / f"slide_{num:03d}.mp3").write_bytes(blob)
        if pieces and header and slide_gap > 0:
            pieces.append(silent_mp3(slide_gap, header))
        pieces.append(blob)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"".join(pieces))
    state["audio"] = str(output)
    save_state(proj, state)
    print(f"\n✓ Narrated presentation → {output}")
    print(f"  Per-slide clips → {adir}/ (handy for embedding audio into each slide)")


def tts(proj: Path, args) -> None:
    out = Path(args.output) if args.output else proj / f"{Path(load_state(proj).get('deck', 'presentation')).stem}_narrated.mp3"
    asyncio.run(tts_async(proj, args.voice, args.rate, args.pitch, args.slide_gap, args.pause, out))


async def preview_voice(voice: str, rate: str, pitch: str, out: Path) -> None:
    text = ("Hi there! I'm going to be your narrator today. "
            "Grab a coffee, get comfortable, and let's dive into some genuinely fascinating ideas together.")
    out.write_bytes(await synth_chunk(text, voice, rate, pitch))
    print(f"✓ Voice sample → {out}")
    if shutil.which("afplay"):
        subprocess.call(["afplay", str(out)])


# ----------------------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_tts_opts(p):
        p.add_argument("--voice", default=DEFAULT_VOICE,
                       help=f"edge-tts voice (default {DEFAULT_VOICE}; try en-US-EmmaMultilingualNeural, "
                            "en-US-JennyNeural, en-GB-SoniaNeural)")
        p.add_argument("--rate", default="+0%", help="speaking rate, e.g. -5%% or +8%%")
        p.add_argument("--pitch", default="+0Hz", help="pitch shift, e.g. +2Hz")

    def add_proj(p):
        p.add_argument("target", help="the .pptx file or its *_narration project folder")

    p = sub.add_parser("run", help="run the full workflow (resumes where you left off)")
    add_proj(p)
    p.add_argument("--audience", default="", help='e.g. "graduate students in public health"')
    p.add_argument("--minutes", type=float, help="target talk length in minutes")
    p.add_argument("--batch-size", type=int, default=15, help="slides per script prompt (large decks)")
    p.add_argument("--slide-gap", type=float, default=1.2, help="seconds of silence between slides")
    p.add_argument("--pause", type=float, default=0.8, help="seconds for each [pause] marker")
    p.add_argument("-o", "--output", help="output MP3 path")
    add_tts_opts(p)

    p = sub.add_parser("extract", help="stage 1: extract slide text + notes"); add_proj(p)
    p = sub.add_parser("research", help="stage 2: academic + real-world enrichment"); add_proj(p)
    p = sub.add_parser("script", help="stage 3: draft and approve the narration script"); add_proj(p)
    p.add_argument("--audience", default="")
    p.add_argument("--minutes", type=float)
    p.add_argument("--batch-size", type=int, default=15)
    p = sub.add_parser("tts", help="stage 4: synthesize MP3 from script.md"); add_proj(p)
    p.add_argument("--slide-gap", type=float, default=1.2)
    p.add_argument("--pause", type=float, default=0.8)
    p.add_argument("-o", "--output")
    add_tts_opts(p)
    p = sub.add_parser("voice-test", help="play a short sample of a voice")
    add_tts_opts(p)
    p.add_argument("-o", "--output", default="voice_sample.mp3")

    args = ap.parse_args()
    if args.cmd == "voice-test":
        asyncio.run(preview_voice(args.voice, args.rate, args.pitch, Path(args.output)))
        return

    target = Path(args.target).expanduser()
    if target.suffix.lower() == ".pptx":
        if not target.exists():
            sys.exit(f"File not found: {target}")
        proj = project_dir_for(target)
    else:
        proj = target
    state = load_state(proj)

    try:
        if args.cmd == "extract" or (args.cmd == "run" and not state.get("extracted")):
            if target.suffix.lower() != ".pptx":
                sys.exit("Pass the .pptx file to extract.")
            extract(target, proj)
        if args.cmd in ("research", "run"):
            research(proj)
        if args.cmd in ("script", "run"):
            script(proj, args.batch_size, args.audience, args.minutes)
        if args.cmd in ("tts", "run"):
            if args.cmd == "run" and load_state(proj).get("script") != "approved":
                print("Script not approved yet — stopping before audio. Re-run to continue.")
                return
            tts(proj, args)
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted — progress is saved; re-run the same command to resume.")


if __name__ == "__main__":
    main()
