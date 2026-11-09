"""On-demand episode guide, isolated from full-book reading and production decisions."""

from __future__ import annotations

import json
from pathlib import Path

from lib.backends.providers import CallPurpose
from lib.backends.text_backends.base import TextGenerationRequest, TextTaskType
from lib.backends.text_generator import TextGenerator
from lib.episode.episode_guide_models import EpisodeGuide
from lib.infra.json_io import atomic_write_json, load_json
from lib.infra.text_utils import strip_json_code_fences


def snapshot(path: Path, project: dict, episode: int) -> dict:
    from lib.episode.episode_ledger import normalize_source_text
    from lib.episode.episode_sources import discover_sources
    from lib.novel_understanding.store import digest

    entry = next((e for e in project.get("episodes", []) if e["episode"] == episode), None)
    if entry is None:
        raise ValueError("Episode not found")
    span = entry.get("source_range")
    if span:
        docs = discover_sources(path, project)
        names = [d.rel_path for d in docs]
        first = names.index(span["source_file"])
        last = names.index(span.get("end_file") or span["source_file"])
        text = "\n".join(
            d.text[span["start"] if i == first else 0 : span["end"] if i == last else len(d.text)]
            for i, d in enumerate(docs)
            if first <= i <= last
        )
    else:
        text = normalize_source_text((path / "source" / f"episode_{episode}.txt").read_text(encoding="utf-8"))
    if not text.strip():
        raise ValueError("Episode source is empty")
    rule_path = path / "episode_guides" / "guide.md"
    rule = (
        rule_path.read_text(encoding="utf-8")
        if rule_path.exists()
        else (Path(__file__).parent / "episode_guide.md").read_text(encoding="utf-8")
    )
    return {"text": text, "source_range": span, "rule": rule, "basis": digest([text, span, rule]), "episode": episode}


def cached(path: Path, data: dict) -> dict:
    target = path / "episode_guides" / f"episode_{data['episode']}.json"
    value = load_json(target) if target.exists() else None
    stale = bool(value and value.get("basis") != data["basis"])
    return {
        "guide": value.get("guide") if value and not stale else None,
        "stale": stale,
        "source_range": data["source_range"],
    }


async def generate(path: Path, data: dict) -> EpisodeGuide:
    generator = await TextGenerator.create(TextTaskType.SCRIPT, path.name, purpose=CallPurpose.SCRIPT_GENERATION)
    prompt = data["rule"] + "\n仅以下本集原文可作为事实依据：\n<source>" + data["text"] + "</source>"
    prompt += "\n只输出 JSON，遵循结构：" + json.dumps(EpisodeGuide.model_json_schema(), ensure_ascii=False)
    result = await generator.generate(
        TextGenerationRequest(prompt=prompt, max_output_tokens=6000), project_name=path.name, require_complete=True
    )
    return EpisodeGuide.model_validate_json(strip_json_code_fences(result.text))


def save(path: Path, data: dict, guide: EpisodeGuide) -> None:
    directory = path / "episode_guides"
    directory.mkdir(exist_ok=True)
    rule_path = directory / "guide.md"
    if not rule_path.exists():
        rule_path.write_text(data["rule"], encoding="utf-8")
    atomic_write_json(
        directory / f"episode_{data['episode']}.json", {"basis": data["basis"], "guide": guide.model_dump()}
    )
