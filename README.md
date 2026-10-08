# deck2audio

Turn a PowerPoint deck into a narrated MP3, with you (and your favorite LLM) in the loop.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

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

## License

[MIT](LICENSE)
