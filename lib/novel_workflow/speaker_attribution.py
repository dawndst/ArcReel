"""Queued, evidence-cited speaker suggestions for one shot; never auto-assign dialogue."""

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store
from lib.novel_workflow.assets import mentions, reference
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_library import catalog, valid_batch
from lib.novel_workflow.scene_source import batch_source


class Suggestion(StrictModel):
    segment_index: int = Field(ge=0)
    utterance_index: int = Field(ge=0)
    speaker: str | None
    proposed_role: str | None = Field(
        default=None,
        max_length=120,
        description="原文已明确说话角色但资产中遗漏时，提出有场景/行为限定的角色标签，例如借数学课本的女同学；不是编造姓名。身份归属也不明确时为空。",
    )
    source_quote: str = ""
    reason: str = Field(min_length=1, max_length=2000)


class Suggestions(StrictModel):
    items: list[Suggestion] = Field(max_length=100)


def snapshot(path, expected, note_ids, shot_id):
    project = load_json(path / "project.json")
    notebook = store.require_current(path, project, expected)
    readings = store.valid_readings(path, notebook)
    for batch in catalog(path)["batches"].values():
        shots = [sh for sc in batch["scenes"] for sh in sc["shots"]]
        for index, shot in enumerate(shots):
            if shot["id"] != shot_id:
                continue
            if batch["note_id"] not in note_ids or not valid_batch(path, batch, notebook, readings):
                raise ValueError("镜头依据已变化，请刷新后重试")
            source = batch_source(path, project, batch["basis"])
            pending = [
                {"segment_index": i, "utterance_index": j, "text": u["text"]}
                for i, seg in enumerate(shot["segments"])
                for j, u in enumerate(seg["utterances"])
                if u["kind"] == "dialogue" and not (u.get("speaker") or "").strip()
            ]
            candidates = []
            for mention in mentions(project, readings[batch["note_id"]]):
                if mention["kind"] != "character" or mention["evidence"]["start"] >= source["end"]:
                    continue
                ref = reference(project, mention)
                if ref.get("asset_missing") or ref.get("asset_issue_blocking"):
                    continue
                candidates.append({"name": ref.get("asset_name", mention["name"]), "source_name": mention["name"]})
            return {
                "batch_basis": batch["basis"],
                "shot": deepcopy(shot),
                "pending": pending,
                "source": source,
                "candidates": candidates,
                "neighbors": [
                    {"title": sh["title"], "segments": sh["segments"]} for sh in shots[max(0, index - 1) : index + 2]
                ],
            }
    raise ValueError("镜头不存在")


def validate(value, data):
    expected = {(u["segment_index"], u["utterance_index"]) for u in data["pending"]}
    actual = [(u.segment_index, u.utterance_index) for u in value.items]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("每条待确认对白必须且只能返回一次，不得修改其他对白")
    names = {c["name"] for c in data["candidates"]}
    result = []
    for item in value.items:
        row = item.model_dump()
        if item.speaker is not None and item.speaker not in names:
            raise ValueError("说话人必须来自本次提供的已登记候选人物")
        if item.proposed_role:
            from lib.project.asset_types import validate_asset_name

            validate_asset_name(item.proposed_role)
            if item.speaker is not None:
                raise ValueError("已有候选与新增角色建议不能同时填写")
        if (item.speaker is not None or item.proposed_role) and len(item.source_quote.strip()) < 2:
            raise ValueError("确定说话人时必须提供原文归属依据")
        if item.source_quote:
            start, end = locate(data["source"]["text"], item.source_quote)
            row["evidence"] = {
                "source_file": data["source"]["source_file"],
                "start": data["source"]["start"] + start,
                "end": data["source"]["start"] + end,
                "quote": data["source"]["text"][start:end],
            }
        result.append(row)
    return result


async def generate(path, generator, note_ids, expected, shot_ids):
    from lib.novel_workflow.service import ask

    if len(shot_ids) != 1:
        raise ValueError("每次只补判一个镜头")
    check_stop()
    data = await asyncio.to_thread(snapshot, path, expected, note_ids, shot_ids[0])
    if not data["pending"]:
        return {"suggested": 0}
    rule = await asyncio.to_thread(store.rule, path, "speaker_attribution")
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "speaker_attribution", "done": 0, "total": 1}
    )
    items = await ask(
        path,
        generator,
        Suggestions,
        rule
        + "\n"
        + json.dumps(
            {
                "source": data["source"]["text"],
                "shot": {
                    "id": data["shot"]["id"],
                    "title": data["shot"]["title"],
                    "segments": data["shot"]["segments"],
                },
                "pending": data["pending"],
                "candidates": data["candidates"],
                "neighbor_shots": data["neighbors"],
            },
            ensure_ascii=False,
        ),
        lambda value: validate(value, data),
        max_output_tokens=5000,
    )

    def commit():
        with project_metadata_lock(path):
            fresh = snapshot(path, expected, note_ids, shot_ids[0])
            if fresh != data or store.rule(path, "speaker_attribution") != rule:
                raise ValueError("镜头、原文或候选人物已变化，请刷新后重试补判")
            library = catalog(path)
            batch = next(b for b in library["batches"].values() if b["basis"] == data["batch_basis"])
            shot = next(sh for sc in batch["scenes"] for sh in sc["shots"] if sh["id"] == shot_ids[0])
            store.write(store.root(path) / "history" / f"speaker-suggestion-{uuid4().hex}.json", batch)
            shot["speaker_suggestions"] = {"items": items, "created_at": now(), "rule_basis": digest(rule)}
            store.write(store.root(path) / "scene_library.json", library)
            store.write(store.root(path) / "progress.json", {"phase": "idle", "done": 1, "total": 1})
        return {"suggested": len(items)}

    return await run_noninterruptible_sync(commit)
