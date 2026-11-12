"""Bounded semantic review of scene prose, with explicit, versioned local adoption."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel


class Revision(StrictModel):
    scene_index: int = Field(ge=0)
    shot_index: int = Field(ge=0)
    segment_index: int | None = Field(default=None, ge=0)
    field: Literal["title", "scene_description"]
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    source_quote: str = Field(min_length=2)
    reason: str = Field(min_length=1)


class SceneReview(StrictModel):
    revisions: list[Revision] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=10)


def target(scenes, revision):
    shot = scenes[revision["scene_index"]]["shots"][revision["shot_index"]]
    if revision["field"] == "title" and revision["segment_index"] is None:
        return shot
    if revision["field"] == "scene_description" and revision["segment_index"] is not None:
        return shot["segments"][revision["segment_index"]]
    raise ValueError("修订字段与位置不匹配")


async def review(path, generator, scenes, original):
    from lib.novel_workflow.service import ask

    def validate(value):
        revisions, seen = [], set()
        for draft in value.revisions:
            item = draft.model_dump()
            try:
                previous = target(scenes, item)[item["field"]]
            except (IndexError, KeyError) as exc:
                raise ValueError("修订必须指向输入中的场镜字段") from exc
            key = (draft.scene_index, draft.shot_index, draft.segment_index, draft.field)
            if key in seen or previous != draft.before or draft.after == draft.before:
                raise ValueError("只返回有变化的、逐字匹配 before 的局部修订；同一字段只修订一次")
            seen.add(key)
            start, end = locate(original, draft.source_quote)
            item.update(id=uuid4().hex, source_quote=original[start:end], applied=False)
            revisions.append(item)
        return {"revisions": revisions, "unresolved": value.unresolved, "reviewed_at": now()}

    return await ask(
        path,
        generator,
        SceneReview,
        "逐项审核场镜与本次原文的语义一致性。核对身份、动机、发色/年龄/形态、事件先后、梦境与现实、人物说法与客观事实。"
        "允许正常镜头化表达，不因未完整复述而报错。引用存在不等于结论成立。"
        "确有不一致时给出最小修订，保留其他内容；before/after 必须是该字段的完整文字。"
        "索引从0开始。title 的 segment_index=null；scene_description 必须指定 segment_index。"
        "缺少明确依据的设定应删除或保持不确定，不填入外部小说知识。"
        "对白允许摘取连续的部分原句，不要求复述完整发言，摘录外层引号差异不算错误。\n"
        "无法通过这些字段安全修复的对白归属、事件缺失或结构问题放入 unresolved。"
        "疑点用工作人员能理解的中文描述，写出本片段第几场、第几镜、镜头标题及相关原句；输入没有镜头ID时不得编造编号；用台词、说话人，不使用utterances等字段名。"
        "不要将没有把握的猜测写为修订。只审核，不替导演组集。\n"
        + json.dumps({"source": original, "scenes": scenes}, ensure_ascii=False),
        validate,
        max_output_tokens=8000,
        grow_output=True,
    )


def adopt(path, project, batch_basis, revision_id, expected):
    from lib.novel_workflow.scene_library import catalog, valid_batch

    with project_metadata_lock(path):
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
        if obj[item["field"]] != item["before"]:
            raise ValueError("修订前文字已变化，不覆盖当前版本")
        store.write(store.root(path) / "history" / f"scene-revision-{uuid4().hex}.json", batch)
        obj[item["field"]] = item["after"]
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
        if resolution == "repaired":
            if any(
                u["kind"] == "dialogue" and not (u.get("speaker") or "").strip()
                for scene in batch["scenes"]
                for shot in scene["shots"]
                for segment in shot["segments"]
                for u in segment["utterances"]
            ):
                raise ValueError("本片段仍有台词缺少说话人，请先在对应台词中确认；填写说明不会修复台词")
            if any(not r.get("applied") and not r.get("superseded") for r in review.get("revisions", [])):
                raise ValueError("本片段仍有未采用的修订，请先处理后确认已修复")
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
