"""Human arrangement to native production; facts remain bound to source Note versions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path

from lib.backends.text_backends.base import resolve_schema, structured_fallback_reason
from lib.episode.episode_source_commands import add_own_source_episode, write_episode_source_file
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, store, understanding


def arrange_episode(manager, name: str, group_id: str) -> int:
    path = manager.get_project_path(name)
    with manager.locked_source_registration(name) as (_directory, project, undo):
        notebook = store.state(path)
        if notebook is None:
            raise ValueError("No Notes")
        store.require_current(path, project, notebook["source_basis"])
        group = next((g for g in notebook["groups"] if g["id"] == group_id), None)
        if not group or group["source_basis"] != notebook["source_basis"]:
            raise ValueError("Group is missing or stale; review its source Notes")
        existing = next(
            (e for e in project.get("episodes", []) if e.get("note_source", {}).get("group_id") == group_id), None
        )
        notes = [n for n in notebook["notes"] if n["id"] in group["note_ids"]]
        readings = [store.note_result(path, n) for n in notes]
        if any(r is None for r in readings):
            raise ValueError("Read every Note in this group before arranging an episode")
        understanding.require_understood(path, group["note_ids"])
        known = understanding.production_context(path, group["note_ids"])
        text = "\n\n".join("".join(c["text"] for c in chapters.chunks(path, project, n)) for n in notes)
        if len(text) > 60000:
            raise ValueError("This group exceeds the episode source context budget; arrange fewer Notes per episode")
        if existing:
            episode = existing["episode"]
            write_episode_source_file(path, episode, text, archive_existing=False, undo=undo)
        else:
            episode = add_own_source_episode(path, project, text, undo=undo, title=group["title"], source_kind="novel")
        entry = next(e for e in project["episodes"] if e["episode"] == episode)
        entry["note_source"] = {
            "group_id": group_id,
            "understanding_basis": known["basis"],
            "source_basis": notebook["source_basis"],
            "note_bases": {n["id"]: r["basis"] for n, r in zip(notes, readings, strict=True)},
            "text_basis": digest(text),
        }
        events = [e for r in readings for e in r["events"]]
        entry["outline"] = {
            "story_beats": [e["title"] + "：" + e["action"] + "；" + e["outcome"] for e in events],
            "next_episode_teaser": None,
        }
        entry["hook"] = next((e["open_thread"] for e in reversed(events) if e["open_thread"]), "")
        return episode


def validate_binding(path: Path, episode: int, binding: dict) -> tuple[dict, list[dict]]:
    project = load_json(path / "project.json")
    entry = next((e for e in project.get("episodes", []) if e["episode"] == episode), None)
    if not entry or entry.get("note_source") != binding:
        raise ValueError("Episode Note arrangement changed during generation")
    source = path / "source" / f"episode_{episode}.txt"
    if digest(source.read_text(encoding="utf-8")) != binding["text_basis"]:
        raise ValueError("Episode source was edited; recheck its Note arrangement")
    notebook = store.require_current(path, project, binding["source_basis"])
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
    scoped = dict(inputs)
    scoped["project_overview"] = {}
    scoped["next_episode_outline"] = None
    quotes = []
    for bucket, kind in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        scoped[bucket] = {}
        for result in readings:
            for asset in result["assets"]:
                if asset["kind"] == kind:
                    scoped[bucket].setdefault(asset["name"], {"description": ""})
                    quotes.append(asset["evidence"]["quote"])
    context = "\n本集由创作者选择 Note 组合形成，原文是素材范围，不要求逐段拍摄。只依据本集原文和已列出的事件改编，不读取或推测后文。不使用作品外部知识。人物年龄、形态、伤势、关系按当前场景原文保持一致；原文未明确的造型不得自行推断。全局资产设定不得覆盖本集证据。"
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
