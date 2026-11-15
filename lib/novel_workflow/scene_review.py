"""Human adoption and scoped resolution of typed scene-inspection results."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_workflow import store
from lib.novel_workflow.common import digest, now


def complete_corrections(batch):
    """Finish source-backed text corrections before publication; never touch dialogue or asset identity."""
    from lib.novel_workflow.scene_inspection import basis, shot_inputs

    before = {s["id"]: digest(s) for s in shot_inputs(batch)}
    changed = 0
    review = batch.get("review", {})
    for item in review.get("revisions", []):
        if item.get("applied") or item.get("superseded"):
            continue
        try:
            shot = batch["scenes"][item["scene_index"]]["shots"][item["shot_index"]]
            field = item["field"]
            segment = item.get("segment_index")
            if field == "title" and segment is None:
                obj = shot
            elif (
                field in {"scene_description", "start_frame", "end_frame"} and isinstance(segment, int) and segment >= 0
            ):
                obj = shot["segments"][segment]
            else:
                raise ValueError("自动补正仅允许当前镜头的标题、动作和首尾画面")
            refs = item.get("source_refs", [])
            if not refs or any(
                r.get("source_file") != shot["evidence"]["source_file"]
                or r.get("start", -1) < 0
                or r.get("start", -1) >= min(r.get("end", -1), shot["evidence"]["end"])
                or not r.get("quote")
                for r in refs
            ):
                raise ValueError("补正缺少当前镜头揭示范围内的有效来源")
            if not isinstance(item["after"], str) or not item["after"].strip():
                raise ValueError("补正内容不能为空")
            if obj.get(field, "") not in {item["before"], item["after"]}:
                # A later manual edit wins; do not resurrect an older proposal.
                item["superseded"] = True
                continue
            obj[field] = item["after"]
            item.update(applied=True, applied_by="automatic_review", applied_at=now())
            changed += 1
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("自动复审补正未通过校验，已保留候选供继续任务：" + str(exc)) from exc
    if changed:
        reviewed = batch.get("inspection_shots", {})
        for shot in shot_inputs(batch):
            if reviewed.get(shot["id"]) == before[shot["id"]]:
                reviewed[shot["id"]] = digest(shot)
        if batch.get("inspection_basis") and batch.get("inspection_rule_basis"):
            batch["inspection_basis"] = basis(batch, batch["inspection_rule_basis"])
    return changed


def complete_saved(path, note_id, unit_id):
    """Resume previously reviewed candidates using the same product path, without another model call."""
    from lib.novel_workflow.scene_library import catalog

    with project_metadata_lock(path):
        library = catalog(path)
        batch = next(
            (
                b
                for b in library["batches"].values()
                if b["note_id"] == note_id and any(s["id"] == unit_id for s in b["scenes"])
            ),
            None,
        )
        if not batch:
            return 0
        previous = deepcopy(batch)
        count = complete_corrections(batch)
        if batch != previous:
            store.write(store.root(path) / "scene_library.json", library)
        return count


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
            raise ValueError(f"{shot['id']} 的自动复审补正尚未完成，请继续生成任务")


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
