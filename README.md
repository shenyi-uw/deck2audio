# deck2audio

Turn a PowerPoint deck into a narrated MP3, with you (and your favorite LLM) in the loop.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

### Local browser interface

```bash
.venv/bin/python deck2audio.py ui
```

Open the local address printed in the terminal (normally `http://127.0.0.1:8501`).
The server listens only on this computer and Streamlit usage telemetry is disabled
by this launcher. Keep it local; this is not an authenticated, multi-user hosting service.

The interface is branded for the **Applied Hearing Science Lab at the University
of Washington**. Its navy/blue background, cream text, gold accents, rounded
controls, and glowing logo badge are inspired by the lab's
[Hearing-Test interface](https://github.com/AHSLab-UW/Hearing-Test).
The bundled lab logo comes from that repository's `images/logo.png`.
Styling is local, with no external font or artwork requests. The launcher loads
the repository's Streamlit theme even when started from another directory.
Restart the UI server after theme configuration changes.

1. **Choose a deck:** browse for a `.pptx` file and open it. Inspect the extracted
   slide text and speaker notes. You can resume a saved browser project or open an
   existing CLI `*_narration` project folder.
2. **Configure the pipeline:** choose direct deck-content drafting (skip all LLM
   steps) or manual LLM drafting. Select professionals, graduate students,
   undergraduates, high school, K-12, or a general audience; add a profession,
   subject, grade, or age for more precise targeting. Set optional duration and
   batch size, and independently enable academic and real-world-example research.
3. **Choose vocal qualities:** select a female or male voice/accent, or supply an
   `edge-tts` voice ID. Adjust speaking rate, pitch, slide gaps, and pauses. Preview
   a short generic sample before synthesizing your deck.
4. **Copy prompts and paste responses:** use the editable prompt and response
   textboxes, or download prompts. Review and approve each research response,
   or skip it. Paste script batches in order; missing, duplicate, out-of-order,
   unexpected, and empty slide sections are flagged and must be corrected.
5. **Review and approve the full script:** edit it in the browser, save an
   unapproved draft, or approve it for audio. Editing an approved script requires
   reapproval. Generate the MP3, listen in the browser, and download the combined
   narration and individual slide clips.

Browser uploads, settings, accepted responses, and drafts are saved in
`ui_projects/` (ignored by Git). Resume a project after restarting the browser or
server; unsaved response textbox edits are not persisted to disk. Starting or
restarting a pipeline clears the active script approval and research selection.
Existing CLI commands remain available.

**Internet and privacy:** extraction, configuration, local draft generation, and
script review work offline after dependencies are installed. No LLM is called
automatically; you decide where to paste prompts, which contain slide text and
notes. Voice preview and MP3 generation need internet and send the text to be
spoken to Microsoft's online TTS service. Only start synthesis for content you
are permitted to send there.

### Command-line workflow

```bash
# Full workflow (resumable — re-run the same command to continue)
.venv/bin/python deck2audio.py run ~/Desktop/MyTalk.pptx --audience "MBA students" --minutes 15

# Skip all research and LLM prompts; still review and approve the script
.venv/bin/python deck2audio.py run ~/Desktop/MyTalk.pptx --skip-all

# Audition voices first
.venv/bin/python deck2audio.py voice-test
.venv/bin/python deck2audio.py voice-test --voice en-US-EmmaMultilingualNeural --rate -5%
```

### Stages
| Stage | Command | What happens |
|---|---|---|
| 1. Extract | `extract deck.pptx` | Slide titles, body text, tables, and speaker notes → `slides.json` / `slides.md` |
| 2. Research | `research deck.pptx` | Two prompts (academic sources; real-world examples) are shown + copied to your clipboard. Paste them into an LLM, copy its answer back, then **Approve / Edit / Re-paste / Skip**. |
| 3. Script | `script deck.pptx` | A speechwriter prompt (tone, hook, transitions, approved research) produces `## Slide N` sections. Missing slides are flagged. Large decks are split into batches with continuity context. A final full-script review requires your confirmation. |
| 4. TTS | `tts deck.pptx` | Text is cleaned for speech and synthesized with `en-US-AvaMultilingualNeural`, and `[pause]` markers and slide gaps become silence. You get one combined MP3 plus one MP3 per slide. |

Output lives in `<deck>_narration/` next to the deck. You can hand-edit `script.md` at any time and re-run `tts`.

### LLM narration guidance

The browser and CLI share the same prompts. They request a wise, charismatic,
engaging presenter with occasional gentle, appropriate humor and relatable,
audience-specific real-world examples. The last slide's narration must end with
a summary of the **entire presentation**, even if there is no summary slide.
For batched decks, the final prompt includes the full deck as reference context,
but asks for narration only for that batch.

Delivery is conversational, like a one-person podcast addressed to one listener:
natural "you" and "I", reflective questions, and warm transitions, without invented
personal experiences. Example research assigns each example to its best-fitting
slide. Script prompts request distinct examples across the whole talk, allowing
only brief, useful callbacks rather than retelling stories. Later batches include
all earlier accepted narration to help avoid repetition; prompts therefore grow
as drafting progresses.

Spoken source attribution is reserved for describing a specific study's finding,
not attaching a researcher's name to a generic statement. Study references must
introduce the team/lead researcher, institution at the time, and publication year
alongside the finding, using verified details. Unverifiable study references
should be omitted rather than filled in with guesses. Relevant, commonly known
public or historical figures may be mentioned outside study attribution.

Prompts also ask the LLM to fact-check slide text and speaker notes, avoid
over-claiming or invented evidence, and clarify uncertain claims with careful
wording while preserving the original message rather than critiquing the deck.
They explicitly prohibit pretending to verify claims without source access.
These are drafting instructions, **not a guarantee of factual accuracy**; verify
important claims before approval. Direct deck-content mode does not fact-check,
add humor/examples, or generate a new closing summary.

### Skip all research and LLM prompts
At the beginning of `run`, or when drafting with `script`, choose **S** to skip all
research and LLM prompts. You can also pass `--skip-all` to either command.
The script uses each slide's speaker notes when available, otherwise its title
and body text, cleaned for speech. Saved research is ignored but not deleted.
Slides without usable text or notes must have speaker notes added first.

This is a direct deck-content script, not an LLM rewrite: `--audience`,
`--minutes`, and `--batch-size` do not alter it. You still get the final
**Approve / Edit / Cancel** review before audio production. Cancelling saves
an unapproved draft and stops a new full workflow before TTS. Script generation
needs no LLM or outside resources; TTS still requires an internet connection.

### Pasting responses
Copy the LLM's whole answer and press **Enter**. The tool reads it from the clipboard, which avoids terminal limits on pasting long lines. You can also choose `e` (your editor), `p` (paste then `END`), or `f` (a file).

### TTS options
`--voice`, `--rate` (e.g. `-5%`), `--pitch` (e.g. `+2Hz`), `--slide-gap 1.2`, `--pause 0.8`, `-o out.mp3`.
Other good female voices: `en-US-EmmaMultilingualNeural`, `en-US-JennyNeural`, `en-US-AriaNeural`, `en-GB-SoniaNeural`, `en-AU-NatashaNeural`.
TTS uses Microsoft Edge's online neural voices through `edge-tts`. It needs an internet connection but no API key.

## Tests

```bash
.venv/bin/python -m unittest -q test_deck2audio test_browser_workflow
```

Tests cover CLI compatibility, shared prompt guidance, persistent browser
workflows, script validation/approval, and Streamlit controls. TTS is mocked;
the tests do not send decks or narration to an online service.

## License

[MIT](LICENSE)
