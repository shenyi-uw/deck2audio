"""Run with `python deck2audio.py ui`."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from zipfile import BadZipFile

import aiohttp
import streamlit as st
from edge_tts.exceptions import EdgeTTSException
from lxml.etree import XMLSyntaxError
from pptx.exc import PackageNotFoundError

import browser_workflow as workflow
import deck2audio as core
import macos_tts

PROJECT_ROOT = Path(__file__).resolve().parent / "ui_projects"
AUDIENCES = {
    "Professionals": "professionals",
    "Graduate students": "graduate students",
    "Undergraduate students": "undergraduate students",
    "High school students": "high school students",
    "K-12 students": "K-12 students",
    "General audience": "a general audience",
}
VOICES = {
    "Ava - US English, female": core.DEFAULT_VOICE,
    "Emma - US English, female": "en-US-EmmaMultilingualNeural",
    "Jenny - US English, female": "en-US-JennyNeural",
    "Andrew - US English, male": "en-US-AndrewMultilingualNeural",
    "Brian - US English, male": "en-US-BrianMultilingualNeural",
    "Sonia - British English, female": "en-GB-SoniaNeural",
    "Ryan - British English, male": "en-GB-RyanNeural",
    "Natasha - Australian English, female": "en-AU-NatashaNeural",
}


def report_error(exc: BaseException) -> None:
    st.error(f"{type(exc).__name__}: {exc}")
    if isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status == 403 and macos_tts.available():
        st.info("The online speech service rejected the request. For an emergency fallback, "
                "select 'macOS voices (offline fallback)' under Voice & pacing.")


def lab_branding() -> None:
    css = Path(__file__).with_name("ui_branding.css").read_text()
    logo = base64.b64encode(Path(__file__).with_name("ahslab_logo.png").read_bytes()).decode("ascii")
    st.html(f"<style>{css}</style>")
    st.html(f"""
        <div class="ahslab-masthead">
            <div class="ahslab-badge">
                <img class="ahslab-logo" src="data:image/png;base64,{logo}"
                     alt="Applied Hearing Science Lab logo" width="74" height="81">
            </div>
            <div>
                <p class="ahslab-name">Applied Hearing Science Lab</p>
                <p class="ahslab-affiliation">University of Washington</p>
            </div>
        </div>
    """)
    st.title("deck2audio")
    st.write("Turn your PowerPoint into an engaging, audience-aware narrated presentation.")
    st.caption("An Applied Hearing Science Lab tool | Local workspace | Manual LLM prompting | Script approval")


def lab_footer() -> None:
    st.html("""
        <footer class="ahslab-footer">
            Applied Hearing Science Lab &middot; University of Washington<br>
            deck2audio &mdash; from slides to spoken stories
        </footer>
    """)


def choose_project() -> Path | None:
    st.header("1. Choose a PowerPoint deck")
    upload = st.file_uploader("Browse for a PowerPoint deck (.pptx)", type=["pptx"])
    if st.button("Open uploaded deck", disabled=upload is None):
        if upload is not None:
            try:
                with st.spinner("Extracting slide text and speaker notes..."):
                    proj = workflow.upload_project(PROJECT_ROOT, upload.name, upload.getvalue())
                st.session_state["active_project"] = str(proj)
                st.rerun()
            except (OSError, ValueError, KeyError, BadZipFile, PackageNotFoundError, XMLSyntaxError) as exc:
                report_error(exc)

    saved = sorted(PROJECT_ROOT.glob("*/*_narration/state.json"))
    if saved:
        options = {str(p.parent): f"{p.parent.name} ({p.parent.parent.name[:8]})" for p in saved}
        selected = st.selectbox("Resume a saved browser project", list(options), format_func=options.__getitem__)
        if st.button("Resume project"):
            st.session_state["active_project"] = selected
            st.rerun()
    with st.expander("Open an existing CLI project"):
        local = st.text_input("Local *_narration folder path")
        if st.button("Open local project"):
            proj = Path(local).expanduser()
            if not local.strip() or not (proj / "slides.json").is_file():
                st.error("Choose a project folder containing slides.json.")
            else:
                st.session_state["active_project"] = str(proj.resolve())
                st.rerun()
    if active := st.session_state.get("active_project"):
        return Path(active)
    st.info("Select and open a deck to begin. Uploads and approved work stay on this computer.")
    return None


def configure_pipeline(proj: Path) -> None:
    config = workflow.config_for(proj)
    with st.expander("2. Configure processing pipeline", expanded=not core.load_state(proj).get("ui")):
        st.caption("Starting a pipeline replaces the active draft and clears approval, not the uploaded deck.")
        with st.form(f"pipeline_{proj}"):
            skip = st.checkbox("Skip all research and LLM drafting; use deck content directly", value=config.skip_llm)
            audience_names = list(AUDIENCES)
            base_audience = config.audience.split(" - ", 1)[0]
            index = next((i for i, name in enumerate(audience_names) if AUDIENCES[name] == base_audience), 0)
            audience = st.selectbox("Intended audience", audience_names, index=index)
            context = st.text_input("Audience context (optional: profession, subject, grade or age)",
                                    value=config.audience.partition(" - ")[2])
            minutes = st.number_input("Target duration in minutes (0 = no target)", min_value=0.0,
                                      value=config.minutes or 0.0, step=1.0)
            batch_size = st.number_input("Slides per LLM prompt", min_value=1, max_value=100,
                                         value=config.batch_size, step=1)
            academic = st.checkbox("Include academic research prompts", value=config.academic)
            examples = st.checkbox("Include real-world example prompts", value=config.examples)
            st.caption("Skip-all ignores audience, duration, batching, and research settings. "
                       "It uses speaker notes, falling back to slide titles and text; it does not rewrite or fact-check.")
            start = st.form_submit_button("Start / restart pipeline", type="primary")
        if start:
            try:
                intended = AUDIENCES[audience] + (f" - {context.strip()}" if context.strip() else "")
                workflow.start_pipeline(proj, workflow.PipelineConfig(
                    skip_llm=skip, audience=intended, minutes=minutes or None,
                    batch_size=int(batch_size), academic=academic, examples=examples))
                st.rerun()
            except (OSError, ValueError, SystemExit) as exc:
                report_error(exc)


def prompt_box(prompt: str, key: str) -> None:
    st.caption("Select the prompt text and copy it into your chosen LLM. Nothing is sent to an LLM automatically.")
    st.text_area("Prompt to copy", value=prompt, height=300, key=f"prompt_{key}")
    st.download_button("Download prompt", prompt, file_name="prompt.txt", mime="text/plain", key=f"download_{key}")


def research_step(proj: Path, revision: str) -> None:
    pending = workflow.pending_research(proj)
    if not pending:
        st.error("Research state has no pending steps. Restart the pipeline.")
        return
    key = pending[0]
    st.subheader("3. Research: " + ("Academic grounding" if key == "academic" else "Relatable real-world examples"))
    prompt_box(core.research_prompt(key, core.load_slides(proj), workflow.config_for(proj).audience),
               f"{revision}_{key}")
    response = st.text_area("Paste and edit the LLM research response", height=250, key=f"research_{revision}_{key}")
    approve, skip = st.columns(2)
    accepted = approve.button("Approve research response", key=f"approve_{key}", disabled=not response.strip())
    skipped = skip.button("Skip this research step", key=f"skip_{key}")
    if accepted or skipped:
        try:
            workflow.accept_research(proj, key, response if accepted else None)
            st.rerun()
        except (OSError, ValueError) as exc:
            report_error(exc)


def drafting_step(proj: Path, revision: str) -> None:
    batch = workflow.current_batch(proj)
    batch_index = core.load_state(proj)["ui"]["next_batch"]
    st.subheader(f"3. Draft script: slides {batch[0]['number']}-{batch[-1]['number']}")
    prompt_box(workflow.current_prompt(proj), f"{revision}_batch_{batch_index}")
    response = st.text_area("Paste and edit the LLM script response", height=350,
                            key=f"batch_response_{revision}_{batch_index}")
    if response.strip():
        for problem in core.validate_script(response, {s["number"] for s in batch}):
            st.warning(problem)
    if st.button("Accept batch and continue", disabled=not response.strip(), type="primary"):
        try:
            workflow.accept_batch(proj, response)
            st.rerun()
        except (OSError, ValueError) as exc:
            report_error(exc)


@st.cache_data(ttl=60)
def installed_macos_voices() -> dict[str, str]:
    return macos_tts.list_voices()


def voice_controls(proj: Path) -> tuple[str, str, str, float, float, str]:
    saved = core.load_state(proj).get("ui_voice", {})
    with st.sidebar:
        st.header("Voice & pacing")
        st.caption("Preset names indicate voice and accent, not guaranteed personality. "
                   "Charisma and humor come from the script.")
        backends = {"Edge voices (online)": "edge"}
        if macos_tts.available():
            backends["macOS voices (offline fallback)"] = "macos"
        backend_names = list(backends)
        backend_index = next((i for i, name in enumerate(backend_names)
                              if backends[name] == saved.get("backend", "edge")), 0)
        backend = backends[st.selectbox("Speech backend", backend_names, index=backend_index,
                                       key=f"backend_{proj}")]
        names = list(VOICES)
        selection = saved.get("selection", names[0])
        custom_default: str = saved.get("custom", "")
        custom = custom_default
        macos_voice = saved.get("macos_voice", "")
        if backend == "edge":
            index = names.index(selection) if selection in names else 0
            selection = st.selectbox("Narrator voice", names, index=index, key=f"voice_{proj}")
            custom = st.text_input("Custom edge-tts voice ID (optional)", value=custom_default,
                                   key=f"custom_voice_{proj}")
            voice = custom.strip() or VOICES[selection]
        else:
            voices = {"": "System default", **installed_macos_voices()}
            local_names = list(voices)
            index = local_names.index(macos_voice) if macos_voice in voices else 0
            macos_voice = st.selectbox(
                "Installed macOS voice", local_names, index=index, key=f"macos_voice_{proj}",
                format_func=lambda name: f"{name} ({voices[name]})" if name else voices[name])
            voice = macos_voice
        rate_value = st.slider("Speaking rate (%)", -50, 50, saved.get("rate", 0), key=f"rate_{proj}")
        pitch_value = saved.get("pitch", 0)
        if backend == "edge":
            pitch_value = st.slider("Pitch adjustment (Hz)", -20, 20, pitch_value, key=f"pitch_{proj}")
        else:
            st.caption("Pitch adjustment is unavailable for macOS voices. "
                       "Normal speed uses 175 words per minute; the rate slider adjusts that speed.")
        gap = st.slider("Silence between slides (seconds)", 0.0, 5.0, saved.get("gap", 1.2), 0.1, key=f"gap_{proj}")
        pause = st.slider("[pause] length (seconds)", 0.0, 3.0, saved.get("pause", 0.8), 0.1, key=f"pause_{proj}")
        rate, pitch = f"{rate_value:+d}%", f"{pitch_value:+d}Hz" if backend == "edge" else "+0Hz"
        if backend == "edge":
            st.caption("Voice preview and MP3 generation need internet and send spoken text to Microsoft's TTS service.")
        else:
            st.caption("Emergency fallback: synthesis uses installed macOS voices locally. "
                       "No narration is sent to Microsoft's TTS service. Voices sound different from Edge.")
        if st.button("Preview voice (online)" if backend == "edge" else "Preview voice (offline)"):
            try:
                with st.spinner("Generating voice sample..."):
                    sample = asyncio.run(core.synth_chunk(core.VOICE_PREVIEW_TEXT, voice, rate, pitch,
                                                         backend=backend))
                st.session_state[f"sample_{proj}"] = ((backend, voice, rate, pitch), sample)
            except (aiohttp.ClientError, EdgeTTSException, OSError, RuntimeError, ValueError) as exc:
                report_error(exc)
        sample = st.session_state.get(f"sample_{proj}")
        if sample and sample[0] == (backend, voice, rate, pitch):
            st.audio(sample[1], format="audio/mp3")
    values = {"selection": selection, "custom": custom, "rate": rate_value, "pitch": pitch_value,
              "gap": gap, "pause": pause, "backend": backend, "macos_voice": macos_voice}
    if saved != values:
        state = core.load_state(proj)
        state["ui_voice"] = values
        core.save_state(proj, state)
    return voice, rate, pitch, gap, pause, backend


def review_step(proj: Path, revision: str, voice_settings: tuple[str, str, str, float, float, str]) -> None:
    st.subheader("4. Final script review")
    state = core.load_state(proj)
    source = proj / ("script.md" if state.get("script") == "approved" else "script.draft.md")
    if not source.exists():
        st.error("No script available for review. Start the pipeline to create one.")
        return
    text = st.text_area("Edit the full narration script", value=source.read_text(),
                        height=450, key=f"full_script_{revision}")
    if state.get("script") == "approved" and not workflow.is_approved(proj, text):
        workflow.save_review(proj, text, approved=False)
    words = sum(len(part.split()) for part in core.parse_script(text).values())
    st.caption(f"{words} spoken words - approximately {words / core.WORDS_PER_MINUTE:.1f} minutes at normal speed")
    st.info("Before approval, review the wording, factual claims, audience fit, and final summary. "
            "An LLM prompt cannot guarantee factual accuracy.")
    expected = {s["number"] for s in core.load_slides(proj)}
    problems = core.validate_script(text, expected)
    for problem in problems:
        st.warning(problem)
    approve, draft = st.columns(2)
    if approve.button("Approve script for audio", disabled=bool(problems), type="primary"):
        workflow.save_review(proj, text, approved=True)
        st.rerun()
    if draft.button("Save draft without approval"):
        workflow.save_review(proj, text, approved=False)
        st.success("Draft saved. Audio generation requires approval.")
    st.download_button("Download current script", text, file_name="script.md", mime="text/markdown")
    approved = workflow.is_approved(proj, text)
    if approved:
        st.success("This script is approved.")

    st.subheader("5. Generate and listen")
    voice, rate, pitch, gap, pause, backend = voice_settings
    signature = workflow.audio_signature(text, voice, rate, pitch, gap, pause, backend=backend)
    if st.button("Generate MP3 (online)" if backend == "edge" else "Generate MP3 (offline)", disabled=not approved):
        output = proj / "narrated.mp3"
        progress = st.progress(0.0, text="Starting synthesis...")

        def update(done: int, total: int) -> None:
            progress.progress(done / total, text=f"Synthesized slide {done} of {total}")

        try:
            state = core.load_state(proj)
            state.pop("audio", None)
            state.pop("audio_source", None)
            core.save_state(proj, state)
            with st.spinner("Synthesizing approved narration..."):
                asyncio.run(core.generate_audio(proj, core.parse_script(text), voice, rate, pitch,
                                                gap, pause, output, progress=update, backend=backend))
            state = core.load_state(proj)
            state["audio_source"] = signature
            core.save_state(proj, state)
            st.success("Audio generated.")
        except (aiohttp.ClientError, EdgeTTSException, OSError, RuntimeError, ValueError) as exc:
            report_error(exc)
    state = core.load_state(proj)
    if state.get("audio") and state.get("audio_source") == signature:
        path = Path(state["audio"])
        if path.exists():
            st.audio(str(path), format="audio/mp3")
            st.download_button("Download narrated MP3", path.read_bytes(), file_name=path.name, mime="audio/mpeg")
            with st.expander("Per-slide MP3 clips"):
                for slide in core.load_slides(proj):
                    clip = proj / "audio" / f"slide_{slide['number']:03d}.mp3"
                    if clip.exists():
                        st.download_button(f"Download slide {slide['number']}", clip.read_bytes(),
                                           file_name=clip.name, mime="audio/mpeg")
        else:
            st.error("The recorded audio file is missing. Generate it again.")
    elif state.get("audio"):
        st.info("Voice or pacing settings changed. Generate audio again to match the current settings.")


def main() -> None:
    st.set_page_config(page_title="deck2audio | UW Applied Hearing Science Lab", layout="wide")
    lab_branding()
    proj = choose_project()
    if proj is None:
        lab_footer()
        return
    try:
        slides = core.load_slides(proj)
        state = core.load_state(proj)
        st.success(f"Active deck: {Path(state.get('deck', proj.name)).name} - {len(slides)} slides")
        st.caption(f"Project saved at: {proj}")
        with st.expander("Slide text and speaker notes"):
            st.text(core.slides_as_markdown(slides))
        try:
            voice_settings = voice_controls(proj)
        except (OSError, RuntimeError, ValueError) as exc:
            report_error(exc)
            lab_footer()
            return
        configure_pipeline(proj)
        state = core.load_state(proj)
        stage = state.get("ui", {}).get("stage")
        revision = f"{proj}_{state.get('ui', {}).get('revision', 'existing')}"
        if stage == "research":
            research_step(proj, revision)
        elif stage == "drafting":
            drafting_step(proj, revision)
        elif stage == "review" or (stage is None and (proj / "script.md").exists()):
            review_step(proj, revision, voice_settings)
        else:
            st.info("Configure and start the pipeline above.")
    except (OSError, ValueError, KeyError, SystemExit) as exc:
        report_error(exc)
    lab_footer()


if __name__ == "__main__":
    main()
