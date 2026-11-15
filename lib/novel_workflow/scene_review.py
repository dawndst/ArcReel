"""Human adoption and scoped resolution of typed scene-inspection results."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_workflow import store
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.storage import load_json


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
        rules = store.effective_rule(path, "scene_shots")
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
        if batch.get("pipeline_version") == 2:
            from lib.novel_workflow.scene_inspection import basis as inspection_basis
            from lib.novel_workflow.scene_inspection import shot_inputs

            rule_basis = batch.get("inspection_rule_basis") or batch["dependencies"]["inspection_rule"]
            batch["inspection_basis"] = inspection_basis(batch, rule_basis)
            if "inspection_shots" in batch:
                batch["inspection_shots"][shot["id"]] = next(
                    digest(s) for s in shot_inputs(batch) if s["id"] == shot["id"]
                )
        store.write(store.root(path) / "scene_library.json", library)
        return {"applied": True}


def require_reviewed(batch, shot):
    review = batch.get("review", {})
    if (
        any(
            i.get("status") == "open" and i.get("blocking") and shot["id"] in i["shot_ids"]
            for i in review.get("issues", [])
        )
        if review.get("version") == 2
        else review.get("unresolved")
    ):
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
        open_issues = [i for i in review.get("issues", []) if i.get("status") == "open" and i.get("blocking")]
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
        if review.get("version") == 2:
            issue = open_issues[question_index]
            issue.update(status="resolved", resolution=resolution, reason_confirmed=reason.strip())
        review["unresolved"] = questions[:question_index] + questions[question_index + 1 :]
        store.write(store.root(path) / "scene_library.json", library)
        return {"confirmed": True}
