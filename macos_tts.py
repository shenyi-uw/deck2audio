"""Local macOS speech, with mono PCM assembly and MP3 export."""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 24000


def available() -> bool:
    return sys.platform == "darwin" and shutil.which("say") is not None


def require_available() -> None:
    if not available():
        raise RuntimeError("The macOS voice fallback requires macOS and the built-in 'say' command.")


def list_voices() -> dict[str, str]:
    require_available()
    result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Could not list macOS voices: {result.stderr.strip()}")
    voices = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Z]{2})\s+#", line)
        if match:
            voices[match[1].strip()] = match[2]
    if not voices:
        raise RuntimeError("macOS did not report any installed speech voices.")
    return voices


def validate_settings(voice: str, rate: str, pitch: str) -> int:
    require_available()
    if pitch != "+0Hz":
        raise ValueError("Pitch adjustment is not supported by the macOS fallback; use +0Hz.")
    if not re.fullmatch(r"[+-]\d+%", rate):
        raise ValueError("Speaking rate must be a signed percentage, such as +0% or -10%.")
    words_per_minute = round(175 * (1 + int(rate[:-1]) / 100))
    if words_per_minute <= 0:
        raise ValueError("Speaking rate must be greater than -100%.")
    if voice and voice not in list_voices():
        raise ValueError(f"macOS voice '{voice}' is not installed. List voices with: say -v '?'")
    return words_per_minute


async def synth_pcm(text: str, voice: str, rate: str, pitch: str) -> bytes:
    words_per_minute = validate_settings(voice, rate, pitch)
    if not text.strip():
        raise ValueError("Speech text cannot be empty.")
    with tempfile.TemporaryDirectory(prefix="deck2audio-say-") as temp:
        source, output = Path(temp) / "text.txt", Path(temp) / "speech.wav"
        source.write_text(text, encoding="utf-8")
        command = ["say", "-r", str(words_per_minute), "-f", str(source),
                   "-o", str(output), "--file-format=WAVE", "--data-format=LEI16@24000"]
        if voice:
            command.extend(["-v", voice])
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _, stderr = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError(f"macOS speech failed: {stderr.decode(errors='replace').strip()}")
        if not output.is_file():
            raise RuntimeError("macOS speech did not produce an audio file.")
        try:
            with wave.open(str(output), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, SAMPLE_RATE):
                    raise RuntimeError("macOS speech returned an unexpected PCM audio format.")
                pcm = audio.readframes(audio.getnframes())
        except (wave.Error, EOFError) as exc:
            raise RuntimeError("macOS speech returned an invalid WAV file.") from exc
        if not pcm:
            raise RuntimeError("macOS speech returned no audio.")
        return pcm


def silence(seconds: float) -> bytes:
    return bytes(round(seconds * SAMPLE_RATE) * 2)


def encode_mp3(pcm: bytes) -> bytes:
    try:
        import lameenc
    except ImportError as exc:
        raise RuntimeError(
            "The macOS MP3 encoder is missing. Install the updated requirements.txt "
            "using this app's .venv Python, then restart the app."
        ) from exc
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(48)
    encoder.set_in_sample_rate(SAMPLE_RATE)
    encoder.set_channels(1)
    encoder.set_quality(2)
    audio = bytes(encoder.encode(pcm)) + bytes(encoder.flush())
    if not audio:
        raise RuntimeError("The macOS MP3 encoder returned no audio.")
    return audio
