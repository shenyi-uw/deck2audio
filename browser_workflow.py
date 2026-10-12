"""Persistent, noninteractive workflow used by the local browser interface."""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import deck2audio as core


@dataclass
class PipelineConfig:
    skip_llm: bool = False
    audience: str = "professionals"
    minutes: float | None = None
    batch_size: int = 15
    academic: bool = True
    examples: bool = True

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("Slides per prompt must be at least one.")
        if self.minutes is not None and self.minutes <= 0:
            raise ValueError("Target duration must be positive.")

    @property
    def research_keys(self) -> list[str]:
        if self.skip_llm:
            return []
        return [key for key, enabled in (("academic", self.academic), ("examples", self.examples)) if enabled]


def upload_project(root: Path, name: str, data: bytes) -> Path:
    name = Path(name).name
    if Path(name).suffix.lower() != ".pptx":
        raise ValueError("Choose a PowerPoint .pptx file.")
    if not data:
        raise ValueError("The uploaded file is empty.")
    digest = hashlib.sha256(data).hexdigest()
    proj = root / digest / f"{Path(name).stem}_narration"
    deck = proj.parent / name
    if not (proj / "slides.json").exists():
        deck.parent.mkdir(parents=True, exist_ok=True)
        deck.write_bytes(data)
        core.extract(deck, proj)
    return proj


def config_for(proj: Path) -> PipelineConfig:
    return PipelineConfig(**core.load_state(proj).get("ui", {}).get("config", {}))


def start_pipeline(proj: Path, config: PipelineConfig) -> None:
    slides = core.load_slides(proj)
    if not slides:
        raise ValueError("The deck has no slides.")
    sections = core.deck_script_sections(slides) if config.skip_llm else {}
    state = core.load_state(proj)
    state["ui"] = {
        "config": asdict(config),
        "stage": "review" if config.skip_llm else ("research" if config.research_keys else "drafting"),
        "sections": sections,
        "next_batch": 0,
        "revision": time.time_ns(),
    }
    state["research"] = {}
    state["script"] = "draft"
    state.pop("audio", None)
    state.pop("audio_source", None)
    if config.skip_llm:
        (proj / "script.draft.md").write_text(core.format_script(slides, sections))
    core.save_state(proj, state)


def pending_research(proj: Path) -> list[str]:
    state = core.load_state(proj)
    return [key for key in config_for(proj).research_keys
            if state.get("research", {}).get(key) not in ("approved", "skipped")]


def accept_research(proj: Path, key: str, response: str | None) -> None:
    if key not in pending_research(proj):
        raise ValueError("This research step is not pending.")
    if response is not None and not response.strip():
        raise ValueError("Paste a nonempty response, or skip this research step.")
    state = core.load_state(proj)
    rdir = proj / "research"
    rdir.mkdir(exist_ok=True)
    prompt = core.research_prompt(key, core.load_slides(proj), config_for(proj).audience)
    (rdir / f"{key}.prompt.txt").write_text(prompt)
    if response is not None:
        (rdir / f"{key}.md").write_text(response.strip())
    state.setdefault("research", {})[key] = "approved" if response is not None else "skipped"
    if all(state["research"].get(k) in ("approved", "skipped") for k in config_for(proj).research_keys):
        state["ui"]["stage"] = "drafting"
    core.save_state(proj, state)


def current_batch(proj: Path) -> list[dict]:
    config = config_for(proj)
    start = core.load_state(proj)["ui"]["next_batch"] * config.batch_size
    return core.load_slides(proj)[start:start + config.batch_size]


def current_prompt(proj: Path) -> str:
    state = core.load_state(proj)
    config = config_for(proj)
    sections = {int(k): v for k, v in state["ui"]["sections"].items()}
    return core.script_prompt(core.load_slides(proj), config.batch_size, state["ui"]["next_batch"],
                              config.audience, config.minutes, sections, core.approved_research(proj))


def accept_batch(proj: Path, response: str) -> None:
    state = core.load_state(proj)
    if state.get("ui", {}).get("stage") != "drafting":
        raise ValueError("No script batch is awaiting a response.")
    expected = {slide["number"] for slide in current_batch(proj)}
    if problems := core.validate_script(response, expected):
        raise ValueError("\n".join(problems))
    prompt = current_prompt(proj)
    batch_index = state["ui"]["next_batch"]
    (proj / f"script_prompt_{batch_index + 1}.txt").write_text(prompt)
    sections = {int(k): v for k, v in state["ui"]["sections"].items()}
    sections.update(core.parse_script(response))
    state["ui"]["sections"] = sections
    state["ui"]["next_batch"] += 1
    slides = core.load_slides(proj)
    (proj / "script.draft.md").write_text(core.format_script(slides, sections))
    if state["ui"]["next_batch"] * config_for(proj).batch_size >= len(slides):
        state["ui"]["stage"] = "review"
    core.save_state(proj, state)


def save_review(proj: Path, text: str, approved: bool) -> None:
    if approved:
        expected = {slide["number"] for slide in core.load_slides(proj)}
        if problems := core.validate_script(text, expected):
            raise ValueError("\n".join(problems))
    state = core.load_state(proj)
    path = proj / ("script.md" if approved else "script.draft.md")
    path.write_text(text)
    state["script"] = "approved" if approved else "draft"
    state.pop("audio", None)
    state.pop("audio_source", None)
    core.save_state(proj, state)


def is_approved(proj: Path, text: str) -> bool:
    path = proj / "script.md"
    return core.load_state(proj).get("script") == "approved" and path.exists() and path.read_text() == text


def audio_signature(text: str, voice: str, rate: str, pitch: str, gap: float, pause: float,
                    *, backend: str = "edge") -> str:
    settings = (text, voice, rate, pitch, gap, pause)
    if backend != "edge":
        settings += (backend,)
    return hashlib.sha256(repr(settings).encode()).hexdigest()
