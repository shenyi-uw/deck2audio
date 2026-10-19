"""Offline American-English Kokoro synthesis from locally installed ONNX assets."""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from pathlib import Path
from threading import Lock

from pcm_audio import SAMPLE_RATE

MODEL_DIR = Path(__file__).resolve().parent / "models" / "kokoro"
DEFAULT_VOICE = "af_heart"
VOICES = {
    "af_heart": "Heart - US English, female",
    "af_bella": "Bella - US English, female",
    "am_michael": "Michael - US English, male",
}
_LOCK = Lock()


def validate_settings(voice: str, rate: str, pitch: str) -> float:
    if voice not in VOICES:
        raise ValueError(f"Unknown Kokoro voice '{voice}'. Choose one of: {', '.join(VOICES)}.")
    if pitch != "+0Hz":
        raise ValueError("Pitch adjustment is not supported by Kokoro; use +0Hz.")
    if not re.fullmatch(r"[+-]\d+%", rate):
        raise ValueError("Speaking rate must be a signed percentage, such as +0% or -10%.")
    speed = 1 + int(rate[:-1]) / 100
    if not 0.5 <= speed <= 2.0:
        raise ValueError("Kokoro speaking rate must be between -50% and +100%.")
    return speed


@lru_cache(maxsize=1)
def _engine():
    try:
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro is not installed. Install requirements-kokoro.txt using this app's "
            ".venv Python, then restart the app. See README.md for offline setup."
        ) from exc
    model, voices = MODEL_DIR / "kokoro-v1.0.onnx", MODEL_DIR / "voices-v1.0.bin"
    if not model.is_file() or not voices.is_file():
        raise RuntimeError(
            f"Kokoro model files are missing in {MODEL_DIR}. Download kokoro-v1.0.onnx "
            "and voices-v1.0.bin as described in README.md before using offline speech."
        )
    return Kokoro(str(model), str(voices))


def _synth_pcm(text: str, voice: str, speed: float) -> bytes:
    # Streamlit sessions share the cached model; serialize access to its phonemizer.
    with _LOCK:
        engine = _engine()
        audio, sample_rate = engine.create(text, voice=voice, speed=speed, lang="en-us")
    import numpy as np

    if sample_rate != SAMPLE_RATE or audio.ndim != 1:
        raise RuntimeError("Kokoro returned an unexpected PCM audio format.")
    if not audio.size or not np.isfinite(audio).all():
        raise RuntimeError("Kokoro returned empty or invalid audio.")
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


async def synth_pcm(text: str, voice: str, rate: str, pitch: str) -> bytes:
    speed = validate_settings(voice, rate, pitch)
    if not text.strip():
        raise ValueError("Speech text cannot be empty.")
    return await asyncio.to_thread(_synth_pcm, text, voice, speed)
