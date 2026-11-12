"""Optional AI assistants; editing and director approval remain separate human operations."""

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import delivery_review, execution, store
from lib.novel_workflow.assets import mentions, reference
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_library import catalog
from lib.novel_workflow.scene_source import batch_source


class ExecutionDraft(StrictModel):
    edit: execution.ShotEdit
    reason: str = Field(min_length=1, max_length=3000)
    source_quotes: list[str] = Field(min_length=1, max_length=15)


class StoryFinding(StrictModel):
    kind: str = Field(min_length=1, max_length=80)
    shot_ids: list[str] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=1, max_length=2000)
    visible_evidence: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=2000)


class StoryAdvice(StrictModel):
    summary: str = Field(min_length=1, max_length=3000)
    audience_understanding: str = Field(min_length=1, max_length=4000)
    findings: list[StoryFinding] = Field(default_factory=list, max_length=30)


def _shot_input(path, expected, note_ids, shot_ids):
    if len(shot_ids) != 1:
        raise ValueError("每次只处理一个镜头")
    project = load_json(path / "project.json")
    book = store.require_current(path, project, expected)
    for batch in catalog(path)["batches"].values():
        for scene in batch["scenes"]:
            for shot in scene["shots"]:
                if shot["id"] != shot_ids[0]:
                    continue
                if batch["note_id"] not in note_ids:
                    raise ValueError("镜头不属于所选章节")
                source = batch_source(path, project, batch["basis"])
                reading = store.valid_readings(path, book)[batch["note_id"]]
                candidates = []
                for item in mentions(project, reading):
                    if item["evidence"]["start"] >= source["end"]:
                        continue
                    ref = reference(project, item)
                    if not ref.get("asset_missing") and not ref.get("asset_issue_blocking"):
                        candidates.append(
                            {
                                "kind": item["kind"],
                                "name": ref.get("asset_name", item["name"]),
                                "variant": ref.get("variant"),
                                "description": item["description"],
                                "evidence": item["evidence"],
                            }
                        )
                return project, batch["basis"], deepcopy(shot), source, candidates
    raise ValueError("镜头不存在")


async def shot_draft(path, generator, note_ids, expected, shot_ids):
    from lib.novel_workflow.service import ask

    project, batch_id, shot, source, candidates = await asyncio.to_thread(
        _shot_input, path, expected, note_ids, shot_ids
    )
    rule = await asyncio.to_thread(store.rule, path, "shot_execution")
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "shot_draft", "done": 0, "total": 1}
    )

    def validate(value):
        edit = execution.validate_edit(value.edit, source["text"], project)
        for quote in value.source_quotes:
            locate(source["text"], quote)
        return {"edit": edit, "reason": value.reason, "source_quotes": value.source_quotes}

    result = await ask(
        path,
        generator,
        ExecutionDraft,
        rule
        + "\n"
        + json.dumps(
            {
                "source": source["text"],
                "shot": {
                    k: v
                    for k, v in shot.items()
                    if k not in {"execution_draft", "speaker_suggestions", "edit_history", "attribution_history"}
                },
                "assets": candidates,
                "checks": execution.inspect(shot, project),
            },
            ensure_ascii=False,
        ),
        validate,
        max_output_tokens=14000,
        grow_output=True,
    )

    def commit():
        with project_metadata_lock(path):
            _, _, fresh, _, _ = _shot_input(path, expected, note_ids, shot_ids)
            if (
                execution.content_basis(fresh) != execution.content_basis(shot)
                or store.rule(path, "shot_execution") != rule
            ):
                raise ValueError("镜头或修订规则已变化，请刷新后重新生成建议")
            library = catalog(path)
            batch = next(b for b in library["batches"].values() if b["basis"] == batch_id)
            current = next(sh for sc in batch["scenes"] for sh in sc["shots"] if sh["id"] == shot_ids[0])
            store.write(store.root(path) / "history" / f"execution-draft-{uuid4().hex}.json", batch)
            current["execution_draft"] = {
                **result,
                "basis": execution.content_basis(fresh),
                "created_at": now(),
                "rule_basis": digest(rule),
            }
            store.write(store.root(path) / "scene_library.json", library)
            store.write(store.root(path) / "progress.json", {"phase": "idle", "done": 1, "total": 1})
        return {"drafted": shot_ids[0]}

    return await run_noninterruptible_sync(commit)


async def selection_story(path, generator, note_ids, expected, shot_ids, title):
    from lib.novel_workflow.service import ask

    project = await asyncio.to_thread(load_json, path / "project.json")
    current = await asyncio.to_thread(delivery_review.preview, path, project, shot_ids, title, expected)
    if set(current["note_ids"]) != set(note_ids):
        raise ValueError("所选镜头与章节范围不一致，请刷新")
    # No original evidence, SVT synopsis or unselected material reaches this viewer-understanding pass.
    visible = [
        {
            "id": s["id"],
            "segments": [
                {
                    "duration_seconds": seg["duration_seconds"],
                    "scene_description": seg["scene_description"],
                    "start_frame": seg.get("start_frame", ""),
                    "end_frame": seg.get("end_frame", ""),
                    "utterances": [
                        {k: u.get(k) for k in ("kind", "speaker", "text", "delivery")} for u in seg["utterances"]
                    ],
                }
                for seg in s["segments"]
            ],
        }
        for s in current["shots"]
    ]
    if len(json.dumps(visible, ensure_ascii=False)) > 70000:
        raise ValueError("所选镜头超出单次叙事审阅容量，请缩短本集或先人工审阅")
    rule = await asyncio.to_thread(store.rule, path, "selection_story")
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "selection_story", "done": 0, "total": 1}
    )

    def validate(value):
        names = set(shot_ids)
        for item in value.findings:
            if not set(item.shot_ids) <= names:
                raise ValueError("叙事建议只能指向实际选中镜头")
            # Evidence is an excerpt of visible actions or audible lines, not invented source context.
            excerpts = [
                seg["scene_description"] for sh in visible if sh["id"] in item.shot_ids for seg in sh["segments"]
            ] + [
                u["text"]
                for sh in visible
                if sh["id"] in item.shot_ids
                for seg in sh["segments"]
                for u in seg["utterances"]
            ]
            if not any(item.visible_evidence in excerpt for excerpt in excerpts):
                raise ValueError("请逐字引用选中镜头的动作或台词作为问题依据")
        return value.model_dump()

    result = await ask(
        path,
        generator,
        StoryAdvice,
        rule + "\n" + json.dumps({"selected_in_order": visible}, ensure_ascii=False),
        validate,
        max_output_tokens=10000,
        grow_output=True,
    )

    def commit():
        with project_metadata_lock(path):
            fresh = delivery_review.preview(path, load_json(path / "project.json"), shot_ids, title, expected)
            if fresh["basis"] != current["basis"]:
                raise ValueError("选镜或排序已变化，请重新检查当前版本")
            store.write(
                store.root(path) / "selection_reviews" / f"{current['basis']}.json",
                {**result, "at": now(), "rule_basis": digest(rule)},
            )
            store.write(store.root(path) / "progress.json", {"phase": "idle", "done": 1, "total": 1})
        return {"reviewed": len(shot_ids), "basis": current["basis"]}

    return await run_noninterruptible_sync(commit)
