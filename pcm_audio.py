"""Shared 24 kHz mono PCM assembly and MP3 export for offline speech."""
from __future__ import annotations

SAMPLE_RATE = 24000


def silence(seconds: float) -> bytes:
    return bytes(round(seconds * SAMPLE_RATE) * 2)


def encode_mp3(pcm: bytes) -> bytes:
    try:
        import lameenc
    except ImportError as exc:
        raise RuntimeError(
            "The local MP3 encoder is missing. Install requirements.txt using "
            "this app's .venv Python, then restart the app."
        ) from exc
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(48)
    encoder.set_in_sample_rate(SAMPLE_RATE)
    encoder.set_channels(1)
    encoder.set_quality(2)
    audio = bytes(encoder.encode(pcm)) + bytes(encoder.flush())
    if not audio:
        raise RuntimeError("The local MP3 encoder returned no audio.")
    return audio
