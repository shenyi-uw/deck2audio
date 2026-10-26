"""Explicit online setup for isolated VibeVoice or Chatterbox; never run during synthesis."""
from __future__ import annotations

import argparse
import subprocess
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIBEVOICE_REVISION = "16fb2cb1217c9934a886e1948ffb06120caa2df5"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    print(f"Downloading {destination.name}...", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            import shutil

            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("vibevoice", "chatterbox"))
    args = parser.parse_args()
    from neural_tts import VIBEVOICE_VOICES, environment_python

    backend = args.backend
    python = environment_python(backend)
    if not python.is_file():
        venv.create(ROOT / f".venv-{backend}", with_pip=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r",
                    str(ROOT / f"requirements-{backend}.txt")], check=True)
    folder = ROOT / "models" / backend
    folder.mkdir(parents=True, exist_ok=True)
    if backend == "vibevoice":
        revision = "6bce5f06044837fe6d2c5d7a71a84f0416bd57e4"
        base = f"https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B/resolve/{revision}"
        for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
            download(f"{base}/{name}", folder / name)
        # Only the text tokenizer is needed, not another Qwen language model.
        subprocess.run([str(python), "-c",
                        "from huggingface_hub import snapshot_download; "
                        "snapshot_download('Qwen/Qwen2.5-0.5B', "
                        "revision='060db6499f32faf8b98477b0a26969ef7d8b9987', "
                        "allow_patterns=['tokenizer.json','tokenizer_config.json','vocab.json','merges.txt'], "
                        f"local_dir={str(folder / 'tokenizer')!r})"], check=True)
        for voice in VIBEVOICE_VOICES:
            gender = "woman" if voice in ("Emma", "Grace") else "man"
            name = f"en-{voice}_{gender}.pt"
            download(f"https://raw.githubusercontent.com/microsoft/VibeVoice/{VIBEVOICE_REVISION}"
                     f"/demo/voices/streaming_model/{name}", folder / "voices" / name)
    else:
        for name in ("ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"):
            download("https://huggingface.co/ResembleAI/chatterbox/resolve/"
                     f"5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18/{name}", folder / name)
    print(f"{backend} setup complete. Speech uses local assets, with no subscription or API fees.")


if __name__ == "__main__":
    main()
