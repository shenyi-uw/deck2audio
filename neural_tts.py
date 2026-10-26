"""Isolated local speech workers and consented, immutable voice references."""
from __future__ import annotations

import atexit
import asyncio
import hashlib
import io
import json
import os
import queue
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIBEVOICE_VOICES = {
    "Emma": "Emma - English, female",
    "Grace": "Grace - English, female",
    "Carter": "Carter - English, male",
    "Davis": "Davis - English, male",
    "Frank": "Frank - English, male",
    "Mike": "Mike - English, male",
}
MAX_RECORDING_BYTES = 10 * 1024 * 1024


def validate_recording(data: bytes) -> None:
    if len(data) > MAX_RECORDING_BYTES:
        raise ValueError("Voice reference must be at most 10 MB.")
    try:
        with wave.open(io.BytesIO(data), "rb") as recording:
            channels, width, rate, frames, compression = (
                recording.getnchannels(), recording.getsampwidth(), recording.getframerate(),
                recording.getnframes(), recording.getcomptype())
            if compression != "NONE" or width != 2 or channels not in (1, 2):
                raise ValueError("Use an uncompressed 16-bit mono or stereo WAV recording.")
            if rate < 16000 or rate > 48000 or not 5 <= frames / rate <= 30:
                raise ValueError("Record 5-30 seconds of speech at 16-48 kHz.")
            pcm = recording.readframes(frames)
            if len(pcm) != frames * channels * width:
                raise ValueError("Voice reference WAV is truncated.")
            # Reject silence without claiming to detect speech or verify identity.
            if not any(abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) > 100
                       for i in range(0, len(pcm), 2)):
                raise ValueError("The recording is silent or too quiet. Record clear speech.")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Voice reference must be a valid WAV recording.") from exc


def save_reference(proj: Path, data: bytes, *, consent: bool) -> Path:
    if not consent:
        raise ValueError("Confirm that this is your own voice or that you have the speaker's permission.")
    validate_recording(data)
    folder = proj / "voices"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / f"{hashlib.sha256(data).hexdigest()}.wav"
    path.write_bytes(data)
    path.chmod(0o600)
    return path.resolve()


def environment_python(backend: str) -> Path:
    env = ROOT / f".venv-{backend}"
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class Worker:
    def __init__(self, backend: str):
        self.backend = backend
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.responses: queue.Queue[str] = queue.Queue()

    def close(self) -> None:
        process = self.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()
        self.process = None

    def _start(self) -> None:
        python = environment_python(self.backend)
        if not python.is_file():
            raise RuntimeError(
                f"{self.backend} is not set up. Run this app's Python with "
                f"setup_offline_tts.py {self.backend}, then restart the app.")
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
               "TOKENIZERS_PARALLELISM": "false"}
        process = subprocess.Popen(
            [str(python), "-u", str(ROOT / "neural_tts_worker.py"), self.backend],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self.process = process
        responses: queue.Queue[str] = queue.Queue()
        self.responses = responses

        def receive() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                responses.put(line)
            responses.put("")

        threading.Thread(target=receive, daemon=True).start()

    def synthesize(self, text: str, voice: str) -> bytes:
        import base64

        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self._start()
            assert self.process is not None and self.process.stdin is not None
            try:
                self.process.stdin.write(json.dumps({"text": text, "voice": voice}) + "\n")
                self.process.stdin.flush()
                line = self.responses.get(timeout=600)
            except (BrokenPipeError, OSError, queue.Empty) as exc:
                self.close()
                raise RuntimeError(f"{self.backend} speech worker failed or timed out. See the app terminal.") from exc
            if not line:
                self.close()
                raise RuntimeError(f"{self.backend} speech worker exited. See the app terminal for details.")
            try:
                response = json.loads(line)
                if "error" in response:
                    raise RuntimeError(f"{self.backend}: {response['error']}")
                pcm = base64.b64decode(response["pcm"], validate=True)
            except (ValueError, KeyError, TypeError) as exc:
                self.close()
                raise RuntimeError(f"{self.backend} returned an invalid worker response.") from exc
            if not pcm or len(pcm) % 2:
                raise RuntimeError(f"{self.backend} returned empty or invalid PCM audio.")
            return pcm


_WORKERS = {name: Worker(name) for name in ("vibevoice", "chatterbox")}


@atexit.register
def close_workers() -> None:
    for worker in _WORKERS.values():
        worker.close()


@dataclass(frozen=True)
class Backend:
    name: str

    def validate_settings(self, voice: str, rate: str, pitch: str) -> None:
        if rate != "+0%" or pitch != "+0Hz":
            raise ValueError(f"{self.name} currently supports natural speed and pitch only; use +0% and +0Hz.")
        if self.name == "vibevoice":
            if voice not in VIBEVOICE_VOICES:
                raise ValueError(f"Unknown VibeVoice speaker '{voice}'.")
        else:
            path = Path(voice)
            if not voice or path.suffix.lower() != ".wav" or not path.is_file():
                raise ValueError("Record and save your voice, or provide a consented WAV reference first.")
            if path.stat().st_size > MAX_RECORDING_BYTES:
                raise ValueError("Voice reference must be at most 10 MB.")
            validate_recording(path.read_bytes())

    async def synth_pcm(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        self.validate_settings(voice, rate, pitch)
        if not text.strip():
            raise ValueError("Speech text cannot be empty.")
        return await asyncio.to_thread(_WORKERS[self.name].synthesize, text, voice)


vibevoice = Backend("vibevoice")
chatterbox = Backend("chatterbox")
