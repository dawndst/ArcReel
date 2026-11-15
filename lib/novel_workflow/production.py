"""Human arrangement to native production; facts remain bound to source Note versions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path

from lib.novel_workflow import store, understanding
from lib.novel_workflow.common import digest
from lib.novel_workflow.storage import load_json


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
        await self.check(None)
        result = await self.generator.generate(
            replace(request, prompt=request.prompt + self.context),
            project_name=self.path.name,
            require_complete=True,
        )
        await self.check(None)
        return result


def selected_inputs(path, project, entry, inputs):
    from lib.novel_workflow.scene_library import selected_shots
    from lib.novel_workflow.shot_production import effective_segment
    from lib.references.reference_catalog import split_derivative_reference

    book = store.state(path)
    selected = selected_shots(path, book, store.valid_readings(path, book), entry["director_selection"]["shot_ids"])
    scoped = {
        **inputs,
        "project_overview": {},
        "next_episode_outline": None,
        "characters": {},
        "scenes": {},
        "props": {},
    }
    for _, _, shot in selected:
        for i, segment in enumerate(shot["segments"]):
            segment = effective_segment(segment, shot.get("production"), i)
            for field, bucket in (("characters_in_scene", "characters"), ("scenes", "scenes"), ("props", "props")):
                names = list(segment.get(field, []))
                if bucket == "characters":
                    names += [u["speaker"] for u in segment["utterances"] if u.get("speaker")]
                for name in names:
                    base, variant = split_derivative_reference(name) if bucket == "characters" else (name, "")
                    item = project.get(bucket, {}).get(base, {})
                    if not item.get("asset_id"):
                        raise ValueError("所选镜头的资产未关联，请先确认：" + name)
                    target = scoped[bucket].setdefault(
                        base, {"description": "", "asset_code": item.get("asset_code", "")}
                    )
                    if variant:
                        child = item.get("derivatives", {}).get(variant, {})
                        if not child.get("asset_id"):
                            raise ValueError("所选镜头的视觉变体未关联，请先确认：" + name)
                        target.setdefault("derivatives", {})[variant] = {
                            "description": child.get("description", ""),
                            "asset_code": child.get("asset_code", ""),
                        }
    return scoped


async def prepare(path, episode, binding, inputs, generator, *, dry_run=False):
    _project, _readings = await asyncio.to_thread(validate_binding, path, episode, binding)
    entry = next(e for e in _project["episodes"] if e["episode"] == episode)
    scoped = await asyncio.to_thread(selected_inputs, path, _project, entry, inputs)
    context = "\n" + (await asyncio.to_thread(store.effective_rule, path, "production")).strip()
    context += "\n" + (await asyncio.to_thread(store.effective_rule, path, "fidelity")).strip()
    context += "\n只细化导演已选镜头，不补写未选择的场面；原文已在本集来源中提供，不重复整章阅读。"
    known = await asyncio.to_thread(understanding.production_context, path, list(binding["note_bases"]))
    context += "\n本集开始前已揭示、可引用的跨章依据（不能当作新增剧情）：" + json.dumps(
        known["links"], ensure_ascii=False
    )
    constraints = [
        {"scene_id": row["scene_id"], "conclusion_constraints": row["conclusion_constraints"]}
        for row in entry.get("director_selection", {}).get("mapping", [])
        if row.get("conclusion_constraints")
    ]
    context += "\n按原生片段编号绑定的结论制作约束，仅用于对应片段，不得提前用于其他片段：" + json.dumps(
        constraints, ensure_ascii=False
    )
    return scoped, None if dry_run else NoteProductionGuard(path, episode, binding, generator, context)
