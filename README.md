# deck2audio

**Turn your PowerPoint slides into a narrated audio lesson.**

An Applied Hearing Science Lab tool from the **University of Washington**, designed
for teachers, college instructors, and anyone who wants to turn a presentation
into spoken audio. Choose a narrator, review the script, and save an MP3 that
students can listen to.

You use the app in your web browser, but it runs on **your own computer**, not a
public website. You do not need to know Git or write code. Setup does require
copying a few commands into a command window; the instructions below explain how.
This is not yet a double-click installer.

## Before you begin

You will need:

- A Mac or Windows PC, a web browser, and permission to install software.
- A PowerPoint file ending in **`.pptx`**. If you have an older `.ppt` file, open
  it in PowerPoint and use **Save As** to save it as a PowerPoint Presentation
  (`.pptx`). Speaker notes are especially helpful for narration.
- **Python**, a free program that runs the app. Instructions are below. Python
  **3.11** is the version used to test this project; use it for the most
  predictable setup.
- Internet access for downloading/installing the software and generating audio.
- Optionally, access to an AI chat service such as ChatGPT, Claude, Copilot, or
  Gemini if you want help rewriting your narration. This is **not required**:
  you can use your slides and speaker notes directly.

No Microsoft PowerPoint installation is required just to process an existing
`.pptx` file. No API key is required for the voice service. Your chosen AI chat
service may have its own account requirements or charges.

**Using a school-managed computer?** Ask your IT staff if software installation
or access to online speech services is restricted. Do not try to bypass your
school's security settings.

## 1. Download the app (no Git required)

1. Open [the deck2audio GitHub page](https://github.com/shenyi-uw/deck2audio).
   GitHub is simply the website where this program is distributed; you do not
   need a GitHub account to download a public repository.
2. Click the green **Code** button, then **Download ZIP**.
3. Find the downloaded ZIP file in your **Downloads** folder.
   - **Mac:** double-click the ZIP to unpack it.
   - **Windows:** right-click the ZIP, choose **Extract All**, then **Extract**.
     Do not run the program from inside the ZIP preview.
4. Move the unpacked folder somewhere you can keep it, such as **Documents**.
   Rename it **`deck2audio`** to make the instructions easier to follow.
5. Open that folder. You should see files such as `deck2audio.py`,
   `requirements.txt`, and this README. If you see only another folder, open
   that inner folder instead.

**Keep the whole folder together**, including the logo, styling files, and the
hidden `.streamlit` folder. Do not download just one Python file.

## 2. Set up your computer (one time)

Choose the instructions for your computer. A command window is a place where
you paste an instruction and press **Enter** (Windows) or **Return** (Mac).
Copy only the text inside each command box, not the surrounding headings.

The `.venv` folder created below holds the app's supporting software separately
from other Python programs. You do not need to open it or "activate" it.

### Mac

**A. Install Python**

1. Go to [Python downloads for macOS](https://www.python.org/downloads/macos/).
2. Choose a Python 3.11 release with a **macOS 64-bit universal2 installer**.
   It supports Intel and Apple Silicon Macs. Follow the installer instructions.
   If Python 3.11 is already installed, you can skip this step.
3. In **Applications**, open the installed **Python 3.11** folder and double-click
   **Install Certificates.command**, if present. This sets up certificates used
   for secure internet connections.

**B. Open Terminal in your app folder**

1. Press **Command + Space**, type **Terminal**, and press **Return**.
2. Type `cd` followed by a space, but do not press Return yet.
3. Drag your unpacked **deck2audio** folder from Finder into the Terminal window.
   Its location will appear after `cd`. Press **Return**.

If you put the folder directly in Documents and named it `deck2audio`, you can
instead paste:

```bash
cd "$HOME/Documents/deck2audio"
```

**C. Install the app's supporting software**

Paste these commands **one at a time**, pressing Return after each and waiting
for it to finish:

```bash
python3.11 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Installation may take a few minutes. Scrolling messages are normal. If a command
ends with an error, see [Troubleshooting](#troubleshooting) before continuing.

### Windows PC

**A. Install Python**

1. Go to [Python downloads for Windows](https://www.python.org/downloads/windows/).
2. Choose a Python 3.11 release with a **Windows installer** appropriate for your
   computer (usually **64-bit**). If unsure, ask your IT staff.
3. Run the installer. If offered, check **Add python.exe to PATH** and keep the
   **Python launcher** enabled, then choose **Install Now**.
4. Close any command windows you had open before installation.
   If Python 3.11 and its launcher are already installed, you can skip this step.

**B. Open PowerShell in your app folder**

1. Open the unpacked **deck2audio** folder in **File Explorer**.
2. Click the address bar at the top (where the folder location appears).
3. Type `powershell` and press **Enter**. A command window opens in that folder.
   Use PowerShell, not the Python interactive window.

**C. Install the app's supporting software**

Paste these commands **one at a time**, pressing Enter after each and waiting
for it to finish:

```powershell
py -3.11 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Installation may take a few minutes. Scrolling messages are normal. You do not
need to run an activation script or change PowerShell's execution policy.

## 3. Start the app

In the command window, still in your **deck2audio** folder, run:

**Mac**

```bash
.venv/bin/python deck2audio.py ui
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe deck2audio.py ui
```

Leave this window open. The app will print a local web address, normally:

**http://127.0.0.1:8501**

Open that address in your browser. If a different port number is printed, use
the printed address instead. The browser may not open automatically.

> **What does "local" mean?** This address points to your own computer. It is not
> a public website, and sending the address to a colleague will not give them
> access to your app. They need their own installation.

**To stop the app:** return to the command window and press **Ctrl+C**
(on either Mac or Windows). Closing only the browser tab does not stop it.

**To use it another day:** open a command window in the same app folder using
the instructions above, then run the appropriate start command again. You do
not need to repeat installation.

## 4. Make your first narrated lesson

For a first try, use a short deck with two or three slides.

1. **Choose your deck.** Click the upload/browse control, select your `.pptx`
   file, then click **Open uploaded deck**. You can inspect the extracted slide
   text and speaker notes.
2. **Choose how to make the script.**
   - **Simplest option:** check **Skip all research and LLM drafting; use deck
     content directly**. The app uses each slide's speaker notes, falling back
     to its title and body text. You can edit the result before approval.
   - **AI-assisted option:** leave that box unchecked. Choose your audience
     (professionals, graduate students, undergraduates, high school, K-12, or
     general audience). Add a grade, subject, or profession if helpful. Academic
     research and real-world-example prompts are optional.
   - Set a target duration if desired; **0** means no target. "Slides per LLM
     prompt" controls how many slides the AI handles at once.
   - Click **Start / restart pipeline**.
3. **Choose a voice.** Open the **Voice & pacing** sidebar. Choose a voice and
   adjust speed, pitch, and pauses. Click **Preview voice (online)**, then press
   **Play** in the audio player. Check your volume if you cannot hear it.
4. **If using AI, copy and paste.** An **LLM** is an AI chat tool. The app gives
   you a prompt: instructions plus your slide content.
   - Select and copy the prompt text (Command+C on Mac; Ctrl+C on Windows).
   - Paste it into your chosen AI chat service in another browser tab.
   - Copy the complete response back into the app's response textbox.
   - Review and approve research responses, or skip those steps. For narration
     batches, click **Accept batch and continue**. Correct any flagged missing,
     duplicate, out-of-order, unexpected, or empty slide sections.
   - Repeat until the full script is ready. The app never calls an AI chat
     service automatically.
5. **Review the full narration.** Edit the words in the textbox. Check factual
   accuracy, pronunciation, audience suitability, and the closing summary.
   Click **Approve script for audio** when satisfied. If you are not ready,
   choose **Save draft without approval**. Editing an approved script requires
   you to approve it again.
6. **Make and save the audio.** Click **Generate MP3 (online)**. Keep the app
   open while it works. Listen in the browser, then choose **Download narrated
   MP3** to save it. Individual slide clips are also available. You can share
   the MP3 through your school's learning platform, subject to its policies.

### What the AI-assisted script aims to do

The prompts request a personable one-person podcast style with natural "you"
and "I", gentle humor, and audience-relatable examples without repetitive stories
or invented personal experiences. The last slide should end with a summary of
the entire presentation, even if your deck has no summary slide.

The AI is asked to fact-check slide text and notes, avoid over-claiming, and
clarify the original message rather than critique the deck. Study references
should describe a finding and introduce the team/lead researcher, institution,
and publication year using verified details, rather than name-drop researchers.

**AI instructions are not a guarantee of accuracy.** Check important claims
yourself. Direct deck-content mode does not fact-check, add examples or humor,
or write a new closing summary. Audience, duration, and batching settings do not
rewrite content in that mode.

## Your files, privacy, and internet access

- **Your original PowerPoint is not edited.** Browser uploads and saved work go
  into the app's `ui_projects` folder. Use **Resume a saved browser project**
  to continue later. Keep that folder when backing up or updating the app.
- **Save before leaving.** Accepted responses and saved drafts are stored on
  disk; unsaved response textbox edits may be lost when you close the browser.
  Restarting a pipeline clears the active script approval and research selection.
- **Treat saved work as private.** People with access to this app folder can
  access its projects. It is not designed as a shared, authenticated service.
- **Internet is required** for initial installation, voice previews, and MP3
  generation. The online speech service receives the text it will speak.
  Extraction, direct script preparation, and review work offline after setup.
- **AI chat is your choice.** Prompts contain slide text and speaker notes.
  Pasting them into an AI service shares that content with that service.
- **Follow school privacy rules.** Do not send student information, confidential
  material, or other restricted content to AI or speech services unless you
  have permission. Microsoft's online speech service is accessed through
  `edge-tts`; the app does not require an API key.
- The launcher listens only on your own computer and disables Streamlit usage
  telemetry. Local styling and the bundled lab logo need no external downloads
  while the app is running.

## Troubleshooting

| What you see | What to do |
|---|---|
| `python3.11` or `py` is not found | Install Python 3.11 using the instructions above, then close and reopen the command window. On Windows, confirm the Python launcher was installed. |
| "Can't open file", "No such file", or `requirements.txt` not found | You are probably in the wrong folder. Open the unpacked folder containing `deck2audio.py` and `requirements.txt`, then open your command window there. |
| `.venv` or its Python executable is missing | Complete the one-time setup commands first. If you moved the app folder after setup, recreate `.venv` and reinstall the supporting software in its new location. |
| `No module named streamlit` or another missing module | Repeat the supporting-software installation command for your computer. Start the app with the `.venv` command shown above, not a different Python installation. |
| The browser cannot connect | Make sure the command window is still running without an error. Use the exact local address printed there. The address works only on the computer running the app. |
| "Port 8501 is already in use" | Another copy may be running. Use its browser page, or stop the old copy with Ctrl+C before starting again. |
| Installation or audio generation has a network/certificate error | Check your internet connection and school network restrictions. On Mac, run Python's **Install Certificates.command** if available. Ask IT for help rather than disabling certificate checks. |
| Voice preview has a player but no sound | Press Play, check computer volume and output device, and ensure the browser tab is not muted. |
| Voice preview or MP3 generation shows an error | Read the displayed message. Check internet access; try a built-in voice instead of a custom voice ID. The online service may be temporarily unavailable. |
| A slide has no usable text or notes | Add speaker notes or text in PowerPoint, save, and upload the revised deck. Images alone are not converted into narration. |
| Audio generation is disabled | Review and approve the full script. Changes to approved text require reapproval. |
| A school computer blocks installation | Ask your IT staff for assistance. Do not bypass security policies. |

If you need more help, ask your IT staff or report the problem through
[GitHub Issues](https://github.com/shenyi-uw/deck2audio/issues) (a GitHub account
is needed to post). Include your operating system, the step you were following,
and the exact error message. **Do not attach private slides, student information,
or confidential script text.**

## Updating to a newer version

1. Save your draft/accepted responses, download any audio you want to keep, and
   stop the app with Ctrl+C.
2. Back up your current app folder, especially `ui_projects`.
3. Download and unpack a new ZIP from GitHub into a **new folder**.
4. Run the one-time setup commands in that new folder. Do not copy the old
   `.venv` folder; it depends on where it was created.
5. To retain browser projects, copy your backed-up `ui_projects` folder into the
   new app folder. Leave your backup untouched until you confirm they resume.
6. Start the new version and open the printed local address.

## Optional: command-line use (for experienced users)

Most users can ignore this section. The original command-line interface (CLI)
remains available. These examples are for Mac; on Windows, replace
`.venv/bin/python` with `.\.venv\Scripts\python.exe` and use Windows file paths.

```bash
# Full workflow; re-run to resume
.venv/bin/python deck2audio.py run ~/Desktop/MyTalk.pptx --audience "MBA students" --minutes 15

# Use deck content without AI drafting
.venv/bin/python deck2audio.py run ~/Desktop/MyTalk.pptx --skip-all

# Try a narrator
.venv/bin/python deck2audio.py voice-test --voice en-US-EmmaMultilingualNeural --rate -5%
```

| Stage | Command | What happens |
|---|---|---|
| Extract | `extract deck.pptx` | Saves slide titles, body text, tables, and notes as `slides.json` and `slides.md`. |
| Research | `research deck.pptx --audience "high school students"` | Creates academic and example prompts for manual AI interaction and approval. |
| Script | `script deck.pptx` | Drafts/approves `## Slide N` narration sections, with batching and final review. Supports `--skip-all`. |
| Audio | `tts deck.pptx` | Generates a combined MP3 and per-slide clips from `script.md`. |

CLI output goes into `<deck>_narration` next to the deck. You can also pass this
project folder to later stages. The browser's **Open an existing CLI project**
control can open that folder.

Voice options include `--voice`, `--rate` (such as `-5%`), `--pitch` (such as
`+2Hz`), `--slide-gap 1.2`, `--pause 0.8`, and `-o out.mp3`. `[pause]` markers
in scripts create silence. The browser and CLI share narration prompts; later
batches include all earlier accepted narration to help avoid repeated examples,
and the final batch includes full-deck context for the closing summary.

## For contributors: tests

```bash
.venv/bin/python -m unittest -q test_deck2audio test_browser_workflow
```

Tests cover CLI compatibility, shared prompts, saved browser workflows,
validation/approval, branding, and Streamlit controls. TTS is mocked; tests do
not send decks or narration to an online service.

## Lab branding and license

The interface's navy/blue background, cream text, gold accents, and rounded
controls are inspired by the lab's
[Hearing-Test interface](https://github.com/AHSLab-UW/Hearing-Test). The bundled
lab logo comes from that repository's `images/logo.png`. Restart the UI server
after changing theme configuration.

Program license: [MIT](LICENSE).
