"""Bounded semantic review of scene prose, with explicit, versioned local adoption."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_models import LibraryUtterance
from lib.novel_workflow.storage import load_json


class Revision(StrictModel):
    scene_index: int = Field(ge=0)
    shot_index: int = Field(ge=0)
    segment_index: int | None = Field(default=None, ge=0)
    field: Literal["title", "scene_description", "start_frame", "end_frame", "utterances"]
    before: str | list[LibraryUtterance]
    after: str | list[LibraryUtterance]
    source_quote: str = Field(min_length=2)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def field_values(self):
        if self.field == "utterances":
            if not isinstance(self.before, list) or not isinstance(self.after, list):
                raise ValueError("台词修订必须提供完整的前后列表")
        elif not isinstance(self.before, str) or not isinstance(self.after, str) or not self.after.strip():
            raise ValueError("文字修订必须提供完整文字，修订后不能为空")
        return self


class SceneReview(StrictModel):
    revisions: list[Revision] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=10)


def target(scenes, revision):
    shot = scenes[revision["scene_index"]]["shots"][revision["shot_index"]]
    if revision["field"] == "title" and revision["segment_index"] is None:
        return shot
    if (
        revision["field"] in {"scene_description", "start_frame", "end_frame", "utterances"}
        and revision["segment_index"] is not None
    ):
        return shot["segments"][revision["segment_index"]]
    raise ValueError("修订字段与位置不匹配")


def validate_review(value, scenes, original):
    """Keep unsafe suggestions visible for human review, outside adoptable revisions."""
    revisions, seen, by_field, conflicts = [], set(), {}, set()
    unresolved = list(value.unresolved)
    for draft in value.revisions:
        item = draft.model_dump()
        if draft.after == draft.before:
            continue
        fingerprint = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        key = (draft.scene_index, draft.shot_index, draft.segment_index, draft.field)
        field = {
            "title": "标题",
            "scene_description": "画面描述",
            "start_frame": "起始画面",
            "end_frame": "结束画面",
            "utterances": "台词",
        }[draft.field]
        location = f"第{draft.scene_index + 1}场、第{draft.shot_index + 1}镜"
        if draft.segment_index is not None:
            location += f"、第{draft.segment_index + 1}片段"
        location += f"的{field}"
        reason = None
        try:
            previous = target(scenes, item).get(item["field"], "")
        except (IndexError, KeyError, ValueError):
            reason = "位置索引或字段与片段的对应关系无效"
        else:
            if previous != item["before"]:
                reason = "修订前文字与当前字段不逐字一致"
            else:
                try:
                    start, end = locate(original, draft.source_quote)
                except ValueError:
                    reason = "原文依据不是当前原文中的连续逐字摘录（允许排版空白差异），可能含改写或拼接"
        if reason:
            unresolved.append(f"{location}：审核建议未采用，{reason}。请核对原文后处理。")
            continue
        if key in by_field:
            conflicts.add(key)
            unresolved.append(f"{location}：同一字段有不同的修订建议，相关建议均未采用，请核对原文后处理。")
            continue
        by_field[key] = item
        item.update(id=uuid4().hex, source_quote=original[start:end], applied=False)
        revisions.append((key, item))
    return {
        "revisions": [item for key, item in revisions if key not in conflicts],
        "unresolved": list(dict.fromkeys(unresolved)),
        "reviewed_at": now(),
    }


async def review(path, generator, scenes, original, *, key_dialogues=()):
    from lib.novel_workflow.service import ask

    rule = await asyncio.to_thread(store.effective_rule, path, "scene_review")
    return await ask(
        path,
        generator,
        SceneReview,
        rule
        + "\n"
        + json.dumps({"source": original, "scenes": scenes, "key_dialogues": key_dialogues}, ensure_ascii=False),
        lambda value: validate_review(value, scenes, original),
        max_output_tokens=8000,
        grow_output=True,
    )


def adopt(path, project, batch_basis, revision_id, expected):
    from lib.novel_workflow import execution
    from lib.novel_workflow.scene_library import catalog, valid_batch
    from lib.novel_workflow.scene_source import batch_source
    from lib.novel_workflow.shot_production import asset_bindings, dialogue_links, planning_inputs

    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        notebook = store.require_current(path, project, expected)
        readings = store.valid_readings(path, notebook)
        library = catalog(path)
        batch = next((b for b in library["batches"].values() if b["basis"] == batch_basis), None)
        if not batch or not valid_batch(path, batch, notebook, readings):
            raise ValueError("场镜依据已变化，请刷新后复核")
        item = next((r for r in batch.get("review", {}).get("revisions", []) if r["id"] == revision_id), None)
        if not item:
            raise ValueError("修订建议不存在")
        if item.get("superseded"):
            raise ValueError("镜头方案已变化，该修订建议已过期，请重新核对当前镜头")
        if item["applied"]:
            return {"applied": True}
        obj = target(batch["scenes"], item)
        if obj.get(item["field"], "") != item["before"]:
            raise ValueError("修订前文字已变化，不覆盖当前版本")
        shot = batch["scenes"][item["scene_index"]]["shots"][item["shot_index"]]
        candidate = deepcopy(shot)
        if item["field"] == "title":
            candidate["title"] = item["after"]
        else:
            candidate["segments"][item["segment_index"]][item["field"]] = deepcopy(item["after"])
        original = batch_source(path, project, batch_basis)["text"]
        validated = execution.validate_edit(
            execution.ShotEdit.model_validate({"title": candidate["title"], "segments": candidate["segments"]}),
            original,
            project,
        )
        rules = store.effective_rule(path, "shot_production")
        ctx = batch.get("production_context")
        shots = {s["id"]: s for sc in batch["scenes"] for s in sc["shots"]}
        was_current = bool(
            ctx
            and batch.get("production_basis")
            == planning_inputs(ctx, rules, shots, project, readings[batch["note_id"]])[2]
        )
        store.write(store.root(path) / "history" / f"scene-revision-{uuid4().hex}.json", batch)
        shot.update(title=validated["title"], segments=validated["segments"])
        shot.pop("execution_draft", None)
        if shot.get("production"):
            shot["production"]["assets"] = asset_bindings(project, readings[batch["note_id"]], shot)
            shot["production"]["dialogue_sources"] = dialogue_links(readings[batch["note_id"]], shot)
        if was_current:
            batch["production_basis"] = planning_inputs(ctx, rules, shots, project, readings[batch["note_id"]])[2]
        item.update(applied=True, applied_at=now(), applied_by="human")
        store.write(store.root(path) / "scene_library.json", library)
        return {"applied": True}


def require_reviewed(batch, shot):
    review = batch.get("review", {})
    if review.get("unresolved"):
        raise ValueError("场镜语义审核仍有待核实问题，请复核原文并修订后再组集")
    for item in review.get("revisions", []):
        candidate = batch["scenes"][item["scene_index"]]["shots"][item["shot_index"]]
        if candidate["id"] == shot["id"] and not item["applied"] and not item.get("superseded"):
            raise ValueError(f"{shot['id']} 有未采纳的原文一致性修订，请先在场镜素材库处理")


def confirm_questions(path, project, batch_basis, expected, review_basis, reason, question_index, resolution):
    """Resolve exactly one version-checked question without changing production content."""
    from lib.novel_workflow.scene_library import catalog, valid_batch

    if len(reason.strip()) < 10:
        raise ValueError("请填写核对依据，至少10字；只需核对本片段，不要求阅读全书")
    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        library = catalog(path)
        batch = next((b for b in library["batches"].values() if b["basis"] == batch_basis), None)
        if not batch or not valid_batch(path, batch, notebook, store.valid_readings(path, notebook)):
            raise ValueError("场镜依据已变化，请刷新")
        review = batch.get("review", {})
        if digest(review) != review_basis:
            raise ValueError("审核结果已变化，请刷新后核对")
        questions = review.get("unresolved", [])
        if question_index < 0 or question_index >= len(questions):
            raise ValueError("疑点不存在，请刷新")
        if resolution not in {"repaired", "false_positive"}:
            raise ValueError("请选择已修复或误报")
        store.write(store.root(path) / "history" / f"scene-review-{uuid4().hex}.json", batch)
        review.setdefault("resolved_questions", []).append(
            {
                "questions": [questions[question_index]],
                "resolution": resolution,
                "reason": reason.strip(),
                "confirmed_by": "human",
                "created_at": now(),
            }
        )
        review["unresolved"] = questions[:question_index] + questions[question_index + 1 :]
        store.write(store.root(path) / "scene_library.json", library)
        return {"confirmed": True}
