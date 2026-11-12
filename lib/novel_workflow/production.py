"""Human arrangement to native production; facts remain bound to source Note versions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path

from lib.backends.text_backends.base import resolve_schema, structured_fallback_reason
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store, understanding


def validate_binding(path: Path, episode: int, binding: dict) -> tuple[dict, list[dict]]:
    project = load_json(path / "project.json")
    entry = next((e for e in project.get("episodes", []) if e["episode"] == episode), None)
    if not entry or entry.get("note_source") != binding:
        raise ValueError("Episode Note arrangement changed during generation")
    source = path / "source" / f"episode_{episode}.txt"
    if digest(source.read_text(encoding="utf-8")) != binding["text_basis"]:
        raise ValueError("Episode source was edited; recheck its Note arrangement")
    notebook = store.require_current(path, project, binding["source_basis"])
    from lib.novel_workflow import scope

    scope.require(path, notebook, list(binding["note_bases"]))
    notes = {n["id"]: n for n in notebook["notes"]}
    readings = []
    for note_id, basis in binding["note_bases"].items():
        if note_id not in notes:
            raise ValueError("Source Note no longer exists")
        result = store.note_result(path, notes[note_id])
        if not result or result["basis"] != basis:
            raise ValueError("Note evidence or reading rules changed; review the arrangement before generating")
        readings.append(result)
    understanding.require_understood(path, list(binding["note_bases"]))
    known = understanding.production_context(path, list(binding["note_bases"]))
    if binding.get("understanding_basis") != known["basis"]:
        raise ValueError("跨章理解依据已变化，请重新编排本集后生成")
    selection = entry.get("director_selection")
    if selection:
        from lib.novel_workflow.scene_library import selected_shots

        current = selected_shots(path, notebook, store.valid_readings(path, notebook), selection["shot_ids"])
        if any(selection["shot_bases"].get(shot["id"]) != digest(shot) for _, _, shot in current):
            raise ValueError("导演选择的镜头已变化，请核对编排")
    return project, readings


@dataclass
class NoteProductionGuard:
    path: Path
    episode: int
    binding: dict
    generator: object
    context: str

    async def check(self, _content) -> list[str]:
        # This gate checks source/provenance freshness, not semantic correctness of the model's prose.
        await asyncio.to_thread(validate_binding, self.path, self.episode, self.binding)
        return []

    async def generate(self, request):
        failure = ""
        for _ in range(3):
            await self.check(None)
            schema = (
                "\n只输出符合结构的 JSON：" + json.dumps(resolve_schema(request.response_schema), ensure_ascii=False)
                if request.response_schema
                else ""
            )
            result = await self.generator.generate(
                replace(request, response_schema=None, prompt=request.prompt + self.context + schema + failure),
                project_name=self.path.name,
                require_complete=True,
            )
            await self.check(None)
            invalid = (
                structured_fallback_reason(result.text, request.response_schema) if request.response_schema else None
            )
            if not invalid:
                return result
            failure = "\n修正 JSON 结构：" + invalid
        raise ValueError("Production model returned invalid JSON for this Note arrangement")


async def prepare(path, episode, binding, inputs, generator, *, dry_run=False):
    _project, readings = await asyncio.to_thread(validate_binding, path, episode, binding)
    from lib.novel_workflow.assets import reference

    scoped = dict(inputs)
    scoped["project_overview"] = {}
    scoped["next_episode_outline"] = None
    quotes = []
    for bucket, kind in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        scoped[bucket] = {}
        for result in readings:
            for asset in result["assets"]:
                if asset.get("source_kind") in {"annotation", "unknown"} or asset.get("claim_type") in {
                    "unverified",
                    "inference",
                    "statement",
                    "adaptation",
                }:
                    continue
                if asset["kind"] == kind:
                    ref = reference(_project, asset)
                    if ref.get("asset_missing"):
                        raise ValueError("Note asset was removed; restore or resolve it before production")
                    name = ref.get("asset_name", asset["name"])
                    entry = scoped[bucket].setdefault(
                        name, {"description": "", "asset_code": ref.get("asset_code", "")}
                    )
                    if ref.get("variant"):
                        entry.setdefault("derivatives", {})[ref["variant"]] = {
                            "description": asset["description"],
                            "asset_code": ref["asset_code"],
                        }
                    quotes.append(asset["evidence"]["quote"])
    context = "\n" + (await asyncio.to_thread(store.effective_rule, path, "production")).strip()
    context += "\n" + (await asyncio.to_thread(store.effective_rule, path, "fidelity")).strip()
    # Original episode text already includes every selected Note; this is only a bounded reminder.
    selected = []
    used = 0
    for quote in dict.fromkeys(quotes):
        if used + len(quote) <= 10000:
            selected.append(quote)
            used += len(quote)
    known = await asyncio.to_thread(understanding.production_context, path, list(binding["note_bases"]))
    context += "\n本集开始前已揭示、可引用的跨章依据（不能当作新增剧情）：" + json.dumps(
        known["links"], ensure_ascii=False
    )
    context += "\n原文资产依据：" + json.dumps(selected, ensure_ascii=False)
    return scoped, None if dry_run else NoteProductionGuard(path, episode, binding, generator, context)
