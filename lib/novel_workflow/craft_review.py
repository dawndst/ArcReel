"""Optional, versioned editorial checks on one saved source fragment.

Evidence is read-only; suggestions never rewrite Notes, assets or episode selection.
Human decisions remain distinct from model assessments and survive in history.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import execution, settings, store
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_source import source_chunk
from lib.novel_workflow.storage import load_json


class CoverageFinding(StrictModel):
    item_id: str
    status: Literal["covered", "partial", "missing", "uncertain"]
    shot_ids: list[str] = Field(default_factory=list, max_length=40)
    reason: str = Field(min_length=1, max_length=1000)


class AppearanceFinding(StrictModel):
    shot_id: str
    reference: str
    status: Literal["consistent", "conflict", "uncertain"]
    reason: str = Field(min_length=1, max_length=1500)
    source_quote: str = Field(min_length=2, max_length=2000)
    suggestion: str = Field(default="", max_length=2000)


class OpeningState(StrictModel):
    present: str = Field(default="", max_length=1500)
    positions: str = Field(default="", max_length=2000)
    props: str = Field(default="", max_length=1500)
    entering: str = Field(default="", max_length=1500)


class OpeningSuggestion(StrictModel):
    scene_id: str
    state: OpeningState
    source_quote: str = Field(min_length=2, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)


class CraftReview(StrictModel):
    coverage: list[CoverageFinding] = Field(default_factory=list, max_length=300)
    appearance: list[AppearanceFinding] = Field(default_factory=list, max_length=200)
    openings: list[OpeningSuggestion] = Field(default_factory=list, max_length=30)


class CraftDecision(StrictModel):
    source_basis: str
    revision: str
    kind: Literal["coverage", "appearance", "opening"]
    item_id: str
    decision: Literal["confirm", "omit", "restore", "accept", "dismiss", "save"]
    reason: str = Field(default="", max_length=2000)
    shot_ids: list[str] = Field(default_factory=list, max_length=100)
    text: str = Field(default="", max_length=3000)
    opening: OpeningState | None = None


def find_batch(path, basis):
    from lib.novel_workflow.scene_library import catalog

    library = catalog(path)
    batch = next((b for b in library["batches"].values() if b["basis"] == basis), None)
    if batch is None:
        raise ValueError("场镜片段不存在")
    return library, batch


def saved_reading(path, batch):
    expected = batch["note_bases"].get(batch["note_id"])
    from lib.novel_workflow.storage import reading_version

    historical = reading_version(path, batch["note_id"], expected)
    if historical is not None:
        return historical
    for file in (store.root(path) / "notes" / batch["note_id"]).glob("*.json"):
        value = load_json(file)
        if value.get("basis") == expected:
            return value
    return None


def action_items(reading, chunk):
    items = []
    for event in (reading or {}).get("events", []):
        ev = event.get("evidence", {})
        if (
            ev.get("source_file") != chunk["source_file"]
            or not chunk["start"] <= ev.get("start", -1) < ev.get("end", -1) <= chunk["end"]
        ):
            continue
        for key, label in (("cause", "前提"), ("conflict", "阻力"), ("action", "行动／决定"), ("outcome", "结果")):
            text = event.get(key, "").strip()
            if not text or text in {"无", "未明确", "未知", "无明确冲突"}:
                continue
            items.append(
                {
                    "id": event["id"] + ":" + key,
                    "event_id": event["id"],
                    "title": event["title"],
                    "kind": label,
                    "text": text,
                    "evidence": ev,
                    "claim_type": event.get("claim_type", "unverified"),
                    "source_kind": event.get("source_kind", "unknown"),
                }
            )
    return items


def inputs(path, project, batch, reading=None, chunk=None):
    chunk = chunk or source_chunk(path, project, batch)
    reading = reading if reading is not None else saved_reading(path, batch)
    from lib.novel_workflow.shot_production import effective_segment

    scenes, assets = [], []
    for sc in batch["scenes"]:
        shots = []
        for sh in sc["shots"]:
            shots.append(
                {
                    "id": sh["id"],
                    "title": sh["title"],
                    "evidence": sh["evidence"],
                    "segments": sh["segments"],
                    "design": sh.get("production", {}).get("design"),
                    "appearance_notes": sh.get("appearance_notes", {}),
                }
            )
            refs = set()
            for i, seg in enumerate(sh["segments"]):
                effective = effective_segment(seg, sh.get("production"), i)
                refs.update(effective.get("characters_in_scene", []))
            for ref in sorted(refs):
                asset = execution.asset(project, "character", ref)
                # The current asset is a design to be checked, never evidence of identity.
                assets.append(
                    {
                        "shot_id": sh["id"],
                        "reference": ref,
                        "asset_id": asset.get("asset_id"),
                        "description": asset.get("description", ""),
                        "image_prompt": asset.get("image_prompt", ""),
                        "missing": not bool(asset),
                    }
                )
        scenes.append(
            {
                "id": sc["id"],
                "title": sc["title"],
                "location": sc["location"],
                "time": sc["time"],
                "shots": shots,
                "opening_state": sc.get("opening_state"),
            }
        )
    value = {
        "source": chunk,
        "items": action_items(reading, chunk),
        "scenes": scenes,
        "assets": assets,
        "reading_basis": (reading or {}).get("basis"),
        "reading_available": reading is not None,
    }
    # Store each observation once; per-shot IDs retain the reveal boundary without
    # repeating the whole chapter's memory for every shot.
    observations = {}
    value["observations"] = {}
    for sc in batch["scenes"]:
        for sh in sc["shots"]:
            ids = []
            for row in (reading or {}).get("assets", []) + (reading or {}).get("changes", []):
                ev = row.get("evidence", {})
                if ev.get("source_file") != chunk["source_file"] or ev.get("end", 10**12) > sh["evidence"]["end"]:
                    continue
                key = row.get("id") or digest(row)[:24]
                observations[key] = row
                ids.append(key)
            value["observations"][sh["id"]] = ids
    value["observation_records"] = observations
    return value


def basis(value, rule):
    return digest([value, rule])


def view(path, project, batch, reading=None, chunk=None):
    value = inputs(path, project, batch, reading, chunk)
    current = basis(value, store.effective_rule(path, "craft_review"))
    saved = batch.get("craft_review")
    review = deepcopy(saved) if saved else None
    stale = bool(review and review["basis"] != current)
    decisions = batch.get("craft_decisions", {})
    rows = []
    for item in value["items"]:
        suggestion = next((r for r in (review or {}).get("coverage", []) if r["item_id"] == item["id"]), None)
        decision = decisions.get(item["id"])
        if decision and decision["basis"] != current:
            decision = {**decision, "stale": True}
        rows.append({**item, "suggestion": suggestion, "decision": decision})
    return {
        "items": rows,
        "review": review,
        "stale": stale,
        "reading_available": value["reading_available"],
        "revision": digest([current, saved, decisions]),
        "basis": current,
    }


def validate(value, material):
    items = {i["id"] for i in material["items"]}
    if len(value.coverage) != len(items) or {v.item_id for v in value.coverage} != items:
        raise ValueError("必须逐项检查所有提供的前提、行动和结果，不得遗漏或编造条目")
    shots = {s["id"]: s for sc in material["scenes"] for s in sc["shots"]}
    scenes = {s["id"]: s for s in material["scenes"]}
    assets = {(a["shot_id"], a["reference"]) for a in material["assets"]}
    if len(value.appearance) != len(assets) or {(a.shot_id, a.reference) for a in value.appearance} != assets:
        raise ValueError("必须逐一检查出镜人物的当前资产造型，不得遗漏或增加人物")
    if len(value.openings) != len(scenes) or {o.scene_id for o in value.openings} != set(scenes):
        raise ValueError("每场须给出一次开场状态建议")
    for row in value.coverage:
        if len(row.shot_ids) != len(set(row.shot_ids)) or not set(row.shot_ids) <= set(shots):
            raise ValueError("承载镜头必须属于当前片段")
        if row.status in {"covered", "partial"} and not row.shot_ids:
            raise ValueError("已承载或部分承载必须指出具体镜头")
        if row.status == "missing" and row.shot_ids:
            raise ValueError("缺失内容不能同时声称有承载镜头")
    source = material["source"]
    for row in [*value.appearance, *value.openings]:
        shot = shots[row.shot_id] if isinstance(row, AppearanceFinding) else scenes[row.scene_id]["shots"][0]
        # New facts in a later scene must not repair an earlier appearance or opening.
        end = shot["evidence"]["end"] - source["start"]
        allowed = source["text"][:end]
        try:
            start, stop = locate(allowed, row.source_quote)
        except ValueError as exc:
            raise ValueError(f"{shot['id']} 外观与开场建议须引用截至对应镜头已揭示的连续原文：{exc}") from exc
        row.source_quote = allowed[start:stop]
    result = value.model_dump()
    for finding in result["appearance"]:
        asset = next(
            a
            for a in material["assets"]
            if (a["shot_id"], a["reference"]) == (finding["shot_id"], finding["reference"])
        )
        finding["current_description"] = asset["description"]
        quote = finding["source_quote"]
        if source["text"].count(quote) == 1:
            start = source["start"] + source["text"].index(quote)
            finding["source_evidence"] = {
                "note_id": source["note_id"],
                "source_file": source["source_file"],
                "start": start,
                "end": start + len(quote),
                "quote": quote,
            }
    return result


async def generate(path, generator, note_ids, expected, shot_ids):
    from lib.novel_workflow.scene_library import catalog
    from lib.novel_workflow.service import ask

    def prepare():
        project = load_json(path / "project.json")
        store.require_current(path, project, expected)
        if not settings.get(path)["craft_checks_enabled"]:
            raise ValueError("内容与外观检查已关闭")
        matches = [
            b
            for b in catalog(path)["batches"].values()
            if shot_ids and shot_ids[0] in {s["id"] for sc in b["scenes"] for s in sc["shots"]}
        ]
        if len(matches) != 1 or matches[0]["note_id"] not in note_ids or len(shot_ids) != 1:
            raise ValueError("每次检查一个原文片段，请从片段检查入口操作")
        batch = matches[0]
        if batch["source_basis"] != expected:
            raise ValueError("原著已替换，不能把历史检查写入当前制作")
        material = inputs(path, project, batch)
        if not material["reading_available"]:
            raise ValueError("此场镜对应的 Note 记录缺失，请先恢复该版本资料")
        return batch, material, store.effective_rule(path, "craft_review")

    batch, material, rule = await asyncio.to_thread(prepare)
    key = basis(material, rule)
    cache = store.root(path) / "craft_cache" / f"{key}.json"
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "craft_review", "done": 0, "total": 1}
    )
    if await asyncio.to_thread(cache.exists):
        result = await asyncio.to_thread(load_json, cache)
    else:
        result = await ask(
            path,
            generator,
            CraftReview,
            rule + "\n" + json.dumps(material, ensure_ascii=False),
            lambda v: validate(v, material),
            max_output_tokens=16000,
        )
        await run_noninterruptible_sync(store.write, cache, result)

    def commit():
        with project_metadata_lock(path):
            _, fresh, fresh_rule = prepare()
            if basis(fresh, fresh_rule) != key:
                raise ValueError("检查期间原文、场镜或资产已变化；结果已缓存，请重新检查")
            library, target = find_batch(path, batch["basis"])
            if target.get("craft_review"):
                store.write(store.root(path) / "history" / f"craft-review-{uuid4().hex}.json", target["craft_review"])
            target["craft_review"] = {**result, "basis": key, "created_at": now()}
            store.write(store.root(path) / "scene_library.json", library)
            store.write(store.root(path) / "progress.json", {"phase": "idle", "done": 1, "total": 1})
        return {"reviewed": batch["basis"]}

    return await run_noninterruptible_sync(commit)


def decide(path, project, batch_basis, req):
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        store.require_current(path, project, req.source_basis)
        if not settings.get(path)["craft_checks_enabled"]:
            raise ValueError("内容与外观检查已关闭")
        library, batch = find_batch(path, batch_basis)
        if batch["source_basis"] != req.source_basis:
            raise ValueError("原著已替换，历史结果只可查看")
        current = view(path, project, batch)
        if current["revision"] != req.revision:
            raise ValueError("场镜、资产或检查结果已变化，请刷新后处理")
        if req.decision != "restore" and len(req.reason.strip()) < 5:
            raise ValueError("请填写至少5字的处理依据")
        shots = {s["id"]: s for sc in batch["scenes"] for s in sc["shots"]}
        previous = deepcopy(batch)
        entry = {"actor": "human", "at": now(), "reason": req.reason.strip(), "basis": current["basis"]}
        if req.kind == "coverage":
            if req.item_id not in {i["id"] for i in current["items"]} or req.decision not in {
                "confirm",
                "omit",
                "restore",
            }:
                raise ValueError("无效的内容承载决定")
            if req.decision == "restore":
                batch.setdefault("craft_decisions", {}).pop(req.item_id, None)
            else:
                if req.decision == "confirm" and (not req.shot_ids or not set(req.shot_ids) <= set(shots)):
                    raise ValueError("请选择实际承载该内容的镜头")
                batch.setdefault("craft_decisions", {})[req.item_id] = {
                    **entry,
                    "decision": req.decision,
                    "shot_ids": list(dict.fromkeys(req.shot_ids)) if req.decision == "confirm" else [],
                }
        elif req.kind == "opening":
            scene = next((s for s in batch["scenes"] if s["id"] == req.item_id), None)
            if scene is None or req.opening is None or req.decision != "save":
                raise ValueError("请填写有效的场景开场状态")
            if not req.opening.present.strip():
                raise ValueError("请注明开场在场人物；空景明确写无人")
            scene["opening_state"] = {**req.opening.model_dump(), **entry}
        else:
            report = batch.get("craft_review", {})
            if current["stale"] or req.decision not in {"accept", "dismiss"}:
                raise ValueError("外观检查已过期，请重新检查后处理")
            finding = next(
                (f for f in report.get("appearance", []) if f["shot_id"] + ":" + f["reference"] == req.item_id), None
            )
            if finding is None:
                raise ValueError("外观建议不存在")
            if req.decision == "accept" and not req.text.strip():
                raise ValueError("请填写采用的当前镜头外观约束")
            finding["decision"] = {**entry, "decision": req.decision, "text": req.text.strip()}
            if req.decision == "accept":
                shots[finding["shot_id"]].setdefault("appearance_notes", {})[finding["reference"]] = {
                    **entry,
                    "text": req.text.strip(),
                    "source_quote": finding["source_quote"],
                }
            elif req.decision == "dismiss":
                shots[finding["shot_id"]].setdefault("appearance_notes", {}).pop(finding["reference"], None)
        # Explicit annotations do not rewrite the underlying actions or asset design.
        # Preserve remaining decisions across this known, human-authored change only.
        fresh_basis = basis(inputs(path, project, batch), store.effective_rule(path, "craft_review"))
        for saved in batch.get("craft_decisions", {}).values():
            if saved["basis"] == current["basis"]:
                saved["basis"] = fresh_basis
        if batch.get("craft_review") and not current["stale"]:
            batch["craft_review"]["basis"] = fresh_basis
        store.write(store.root(path) / "history" / f"craft-decision-{uuid4().hex}.json", previous)
        store.write(store.root(path) / "scene_library.json", library)
        return {"saved": True}


def opening_text(scene):
    state = scene.get("opening_state")
    if not state:
        return ""
    return "\n已确认的原场开场状态（仅用于原场第一镜，后续镜头继承实际动作后的状态）：\n" + "\n".join(
        f"{label}：{state.get(key, '')}"
        for key, label in (
            ("present", "在场"),
            ("positions", "位置与朝向"),
            ("props", "道具持有"),
            ("entering", "稍后入场"),
        )
    )


def appearance_text(shot):
    return "".join(
        f"\n人工确认的当前镜头外观约束（{ref}）：{v['text']}" for ref, v in shot.get("appearance_notes", {}).items()
    )
