"""Scoped semantic findings and evidence-ID revisions, independent of draft generation."""

import asyncio
from typing import Literal
from uuid import uuid4

from pydantic import Field

from lib.novel_workflow import store
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_contracts import SourceAware
from lib.novel_workflow.stage_runner import ContractError, run


class Finding(StrictModel):
    shot_ids: list[str] = Field(min_length=1)
    severity: Literal["blocker", "major", "minor", "note"]
    category: Literal["fact", "causal", "speaker", "continuity", "coverage", "style"]
    reason: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class Correction(StrictModel):
    shot_id: str
    segment_index: int | None
    field: Literal["title", "scene_description", "start_frame", "end_frame"]
    after: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class Inspection(SourceAware):
    findings: list[Finding] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)


def shot_inputs(batch):
    return [
        {"id": s["id"], "title": s["title"], "segments": s["segments"], "event_ids": s["production"]["event_ids"]}
        for scene in batch["scenes"]
        for s in scene["shots"]
    ]


def basis(batch, rule_basis):
    return digest([batch["basis"], rule_basis, shot_inputs(batch)])


def pending_shots(batch, rule_basis):
    inputs = shot_inputs(batch)
    previous = batch.get("inspection_shots")
    if previous is None:
        return [s["id"] for s in inputs] if batch.get("inspection_basis") != basis(batch, rule_basis) else []
    return [
        s["id"]
        for s in inputs
        if batch.get("inspection_rule_basis") != rule_basis or previous.get(s["id"]) != digest(s)
    ]


async def review(path, generator, catalogue, unit, batch):
    rule = await asyncio.to_thread(store.effective_rule, path, "scene_inspection")
    shots = {s["id"]: s for scene in batch["scenes"] for s in scene["shots"]}
    material = await asyncio.to_thread(catalogue.material, unit["event_ids"])
    # Evidence is supplied once, including literal context for the scope actually reviewed.
    refs = {catalogue.events[i]["source_id"] for i in unit["event_ids"]}
    material["evidence"] = {sid: catalogue.sources[sid] for sid in refs}
    material["scene"] = {k: unit[k] for k in ("title", "location", "time", "purpose")}
    material["shots"] = shot_inputs(batch)
    material["chapter_story"] = {k: catalogue.story.get(k) for k in ("title", "summary", "advancement")}

    def validate(value):
        errors, revisions, findings = [], [], []
        corrected_fields = {}
        for bucket in ("findings", "corrections"):
            for i, item in enumerate(getattr(value, bucket)):
                ids = item.shot_ids if bucket == "findings" else [item.shot_id]
                if not set(ids) <= set(shots):
                    errors.append(
                        {
                            "path": [bucket, i, "shot_ids" if bucket == "findings" else "shot_id"],
                            "message": "审核必须定位当前场的真实镜头ID",
                        }
                    )
                if not set(item.source_ids) <= set(catalogue.sources):
                    errors.append({"path": [bucket, i, "source_ids"], "message": "依据只能引用本章来源索引"})
        if errors:
            raise ContractError(errors)
        for i, item in enumerate(value.corrections):
            field_key = (item.shot_id, item.segment_index, item.field)
            if field_key in corrected_fields:
                if corrected_fields[field_key] != item.after:
                    errors.append(
                        {
                            "path": ["corrections", i],
                            "type": "unsafe_proposal",
                            "message": "同一镜头字段的建议互相冲突；保留一个有当前依据的方案，或remove撤回当前提议，不新增原著疑点",
                        }
                    )
                continue
            corrected_fields[field_key] = item.after
            shot = shots[item.shot_id]
            if item.field == "title" and item.segment_index is None:
                previous = shot["title"]
            elif (
                item.field != "title"
                and item.segment_index is not None
                and 0 <= item.segment_index < len(shot["segments"])
            ):
                previous = shot["segments"][item.segment_index].get(item.field, "")
            else:
                errors.append({"path": ["corrections", i, "segment_index"], "message": "文字字段与片段位置不一致"})
                continue
            if previous == item.after:
                continue
            refs = [catalogue.sources[sid] for sid in item.source_ids]
            # A mapped edition passage can extend past a shot's event anchor.
            # Overlap is supporting context, not proof of a future revelation.
            if any(e["start"] >= shot["evidence"]["end"] for e in refs):
                errors.append(
                    {
                        "path": ["corrections", i],
                        "type": "unsafe_proposal",
                        "message": "整条修订引用仅在后续出现的依据；改为有当前依据的修订，或remove撤回这条建议，不制造剧情疑点",
                    }
                )
                continue
            scene_index = next(
                i for i, sc in enumerate(batch["scenes"]) if any(s["id"] == item.shot_id for s in sc["shots"])
            )
            shot_index = next(i for i, s in enumerate(batch["scenes"][scene_index]["shots"]) if s["id"] == item.shot_id)
            revisions.append(
                {
                    "id": uuid4().hex,
                    "scene_index": scene_index,
                    "shot_index": shot_index,
                    "segment_index": item.segment_index,
                    "field": item.field,
                    "before": previous,
                    "after": item.after,
                    "source_quote": refs[0]["quote"],
                    "source_refs": refs,
                    "reason": item.reason,
                    "applied": False,
                }
            )
        if errors:
            raise ContractError(errors)
        findings.extend(
            {
                **item.model_dump(),
                "id": digest(item.model_dump())[:24],
                "status": "open",
                "blocking": item.severity in {"blocker", "major"},
                "source_refs": [catalogue.sources[sid] for sid in item.source_ids],
            }
            for item in value.findings
        )
        return {
            "version": 2,
            "issues": findings,
            "revisions": revisions,
            "unresolved": [f["reason"] for f in findings if f["blocking"]],
            "reviewed_at": now(),
        }

    key = digest(["inspection", batch["basis"], rule, material["shots"]])
    return await run(
        path, generator, Inspection, rule, material, key, validate, source_lookup=catalogue.lookup, output_limit=7000
    )
