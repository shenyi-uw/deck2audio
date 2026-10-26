"""Private stdio worker; runs only in an optional engine's isolated environment."""
from __future__ import annotations

import base64
import copy
import json
import re
import sys
import traceback
from contextlib import redirect_stdout
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def block_network(event: str, args: tuple) -> None:
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("Network access is disabled in offline speech workers.")


def split_text(text: str, max_words: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        words = sentence.split()
        while words:
            room = max_words - len(current)
            current.extend(words[:room])
            words = words[room:]
            if len(current) == max_words:
                chunks.append(" ".join(current))
                current = []
        if current and len(current) >= max_words // 2:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


@lru_cache(maxsize=1)
def load_engine(backend: str):
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    folder = ROOT / "models" / backend
    if not folder.is_dir():
        raise RuntimeError(f"Model files missing. Run setup_offline_tts.py {backend} first.")
    if backend == "chatterbox":
        from chatterbox.tts import ChatterboxTTS

        return ChatterboxTTS.from_local(folder, device=device)
    from vibevoice.modular.modeling_vibevoice_streaming_inference import (
        VibeVoiceStreamingForConditionalGenerationInference,
    )
    from vibevoice.processor.vibevoice_streaming_processor import VibeVoiceStreamingProcessor
    from vibevoice.modular.modular_vibevoice_text_tokenizer import VibeVoiceTextTokenizerFast

    tokenizer = VibeVoiceTextTokenizerFast.from_pretrained(
        str(folder / "tokenizer"), local_files_only=True)
    processor = VibeVoiceStreamingProcessor(tokenizer=tokenizer)
    model = VibeVoiceStreamingForConditionalGenerationInference.from_pretrained(
        str(folder), torch_dtype=torch.float32 if device != "cuda" else torch.bfloat16,
        attn_implementation="sdpa", local_files_only=True)
    model.to(device).eval()
    model.set_ddpm_inference_steps(num_steps=5)
    return model, processor, device


def synthesize(backend: str, text: str, voice: str) -> bytes:
    import numpy as np
    import torch

    engine = load_engine(backend)
    pieces = []
    if backend == "vibevoice":
        from transformers.cache_utils import DynamicCache
        from transformers.modeling_outputs import BaseModelOutputWithPast
        from neural_tts import VIBEVOICE_VOICES

        if voice not in VIBEVOICE_VOICES:
            raise ValueError("Unknown VibeVoice speaker.")
        model, processor, device = engine
        gender = "woman" if voice in ("Emma", "Grace") else "man"
        preset = ROOT / "models/vibevoice/voices" / f"en-{voice}_{gender}.pt"
        with torch.serialization.safe_globals([BaseModelOutputWithPast, DynamicCache]):
            cached = torch.load(preset, map_location=device, weights_only=True)
        for chunk in split_text(text, 250):
            inputs = processor.process_input_with_cached_prompt(
                text=chunk, cached_prompt=cached, padding=True,
                return_tensors="pt", return_attention_mask=True)
            inputs = {key: value.to(device) if torch.is_tensor(value) else value
                      for key, value in inputs.items()}
            with torch.inference_mode():
                result = model.generate(
                    **inputs, max_new_tokens=None, cfg_scale=1.5, tokenizer=processor.tokenizer,
                    generation_config={"do_sample": False}, verbose=False,
                    all_prefilled_outputs=copy.deepcopy(cached))
            if not result.speech_outputs or result.speech_outputs[0] is None:
                raise RuntimeError("VibeVoice produced no speech.")
            pieces.append(result.speech_outputs[0].detach().cpu().float().numpy().reshape(-1))
    else:
        from neural_tts import chatterbox

        chatterbox.validate_settings(voice, "+0%", "+0Hz")
        engine.prepare_conditionals(voice)
        if engine.sr != 24000:
            raise RuntimeError("Chatterbox returned an unsupported sample rate.")
        for chunk in split_text(text, 35):
            with torch.inference_mode():
                audio = engine.generate(chunk)
            pieces.append(audio.detach().cpu().float().numpy().reshape(-1))
    if not pieces or any(not audio.size or not np.isfinite(audio).all() for audio in pieces):
        raise RuntimeError("Speech model returned empty or invalid audio.")
    audio = np.concatenate(pieces)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def main() -> None:
    backend = sys.argv[1]
    if backend not in ("vibevoice", "chatterbox"):
        raise ValueError("Unknown speech worker.")
    sys.addaudithook(block_network)
    protocol = sys.stdout
    for line in sys.stdin:
        try:
            with redirect_stdout(sys.stderr):
                request = json.loads(line)
                pcm = synthesize(backend, request["text"], request["voice"])
            response = {"pcm": base64.b64encode(pcm).decode("ascii")}
        except Exception as exc:
            # The worker boundary must report dependency/model failures to the GUI.
            traceback.print_exc(file=sys.stderr)
            response = {"error": f"{type(exc).__name__}: {exc}"}
        protocol.write(json.dumps(response) + "\n")
        protocol.flush()


if __name__ == "__main__":
    main()
