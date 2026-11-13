"""Versioned chapter conclusions; raw readings and retrieval reports remain immutable."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from functools import partial
from typing import Literal

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import memory, settings, store
from lib.novel_workflow.models import ChapterSynthesis, EvidencedClaim, StrictModel


class Conclusion(EvidencedClaim):
    question: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(min_length=1)
    status: Literal["resolved", "partial", "unrevealed", "check", "conflict"]
    answer: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    support: Literal["explicit", "inference", "none"]
    impact: Literal["none", "identity", "causal", "dialogue"]
    production_constraint: str = Field(min_length=1, max_length=700)


class Consolidation(StrictModel):
    overview: ChapterSynthesis
    conclusions: list[Conclusion] = Field(min_length=1)


def enabled(path):
    return settings.get(path).get("conclusions_enabled", True)


def active_register(path, report):
    from lib.novel_workflow import question_register

    value = question_register.load(path, report) if report else None
    return value if value and not value["stale"] else None


def inputs(path, note, reading, report):
    """One source pool shared across identity, state, causality and question types."""
    from lib.novel_workflow import scope

    notebook = store.state(path)
    scope.require(path, notebook, [note["id"]])
    questions = {}

    def question(text, origin):
        key = digest([note["id"], "".join(text.split())])[:24]
        questions.setdefault(key, {"id": key, "text": text, "origins": []})["origins"].append(origin)
        return questions[key]

    for q in reading.get("reading_questions", []):
        question(q["text"], "reading")
    for q in reading.get("questions", []):
        question(q, "reading_legacy")
    for q in reading.get("overview", {}).get("questions", []):
        question(q, "overview")
    register = active_register(path, report)
    groups = [g for g in register["groups"] if note["id"] in g["note_ids"]] if register else []
    if register:
        for group in groups:
            item = question(group["question"] + "：" + group["explanation"], "question_register:" + group["id"])
            item.setdefault("original_ids", []).extend(group["original_ids"])
    else:
        for q in (report or {}).get("unresolved", []):
            if q["note_id"] == note["id"]:
                question(q["question"], "reread")
    links = [v for v in (report or {}).get("links", []) if note["id"] in v["note_ids"]]
    covered_links = {i for group in groups for i in group.get("link_ids", [])}
    for link in links:
        if link["id"] not in covered_links:
            text = link["subject"] if register else link["subject"] + "：" + link["description"]
            question(text, "link:" + link["id"])
    if not questions:
        question("本章是否存在影响改编的未解信息或结论冲突？", "chapter_review")
    evidence = {}
    records = memory.records(reading)
    for record in records + [d for e in reading.get("events", []) for d in e.get("dialogues", [])]:
        ev = record.get("evidence")
        if ev:
            evidence[record["id"]] = ev
    for link in links:
        for ev in link["evidence"]:
            evidence.setdefault(digest(ev)[:24], ev)
    manual = decisions(path, note["id"], reading)
    for decision in manual:
        for original in decision.get("source_questions", []):
            questions.setdefault(original["id"], original)
        evidence.update(decision.get("evidence_pool", {}))
    scope.require(
        path,
        notebook,
        {e["note_id"] for e in evidence.values()}
        | {i for link in links for i in link["note_ids"]}
        | set((report or {}).get("inspected_note_ids", [])),
    )
    material = {
        "manual_decisions": manual,
        "note_id": note["id"],
        "note_order": note["order"],
        "overview": reading["overview"],
        "events": [
            {k: e.get(k) for k in ("id", "title", "cause", "action", "outcome", "claim_type", "perspective")}
            for e in reading.get("events", [])
        ],
        "draft_links": [
            {k: v.get(k) for k in ("id", "kind", "subject", "description", "status", "claim_type")} for v in links
        ],
        "evidence": [{"id": key, **ev} for key, ev in evidence.items()],
        "questions": list(questions.values()),
    }
    return material, evidence, questions


def basis(path, reading, report):
    records = memory.records(reading)
    note_id = records[0]["evidence"]["note_id"] if records else ""
    material = [
        reading["basis"],
        (report or {}).get("id"),
        store.effective_rule(path, "conclusions"),
        settings.get(path)["summary_max_chars"],
        decisions(path, note_id, reading),
    ]
    register = active_register(path, report)
    if register:
        material.append(register["basis"])
    return digest(material)


def load(path, note, reading, report=None, *, notebook=None, readings=None):
    if not enabled(path) or not reading:
        return None
    file = store.root(path) / "conclusions" / f"{note['id']}.json"
    if not file.exists():
        return None
    value = load_json(file)
    notebook = notebook if notebook is not None else store.state(path)
    # A saved report reference is checked independently; callers need not recursively load understanding.view.
    if report is None and value.get("report_id"):
        target = store.root(path) / "understanding/reports" / f"{value['report_id']}.json"
        if not target.exists():
            return None
        report = load_json(target)
    if report:
        from lib.novel_workflow.understanding import understanding_rules

        current_readings = readings if readings is not None else store.valid_readings(path, notebook)
        if (
            report.get("source_basis") != notebook["source_basis"]
            or report.get("scope_rule_basis", digest(store.effective_rule(path, "scope")))
            != digest(store.effective_rule(path, "scope"))
            or report["rule_basis"] != digest(understanding_rules(path))
        ) or any(current_readings.get(i, {}).get("basis") != b for i, b in report["note_bases"].items()):
            return None
    if value["basis"] != basis(path, reading, report):
        return None
    from lib.novel_workflow import scope

    allowed = scope.available_ids(path, notebook)
    if not set(value.get("inspected_note_ids", [])) <= allowed:
        return None
    if note["id"] not in allowed or any(
        e["note_id"] not in allowed for c in value["conclusions"] for e in c["evidence"]
    ):
        return None
    return value


def validate(value, note, reading, evidence, questions, notebook, limit):
    assigned = [key for c in value.conclusions for key in c.source_ids]
    if set(assigned) != set(questions) or len(assigned) != len(set(assigned)):
        missing = sorted(set(questions) - set(assigned))
        extra = sorted(set(assigned) - set(questions))
        repeated = sorted({i for i in assigned if assigned.count(i) > 1})
        raise ValueError(
            "每个输入问题必须恰好归入一个结论；缺少source_ids="
            + str(missing)
            + "；不存在="
            + str(extra)
            + "；重复="
            + str(repeated)
        )
    records = {r["id"] for r in memory.records(reading)}
    if not set(value.overview.evidence_ids) <= records or len(value.overview.summary) > limit:
        raise ValueError("概况引用必须来自本章记录，且遵守摘要字数上限。")
    orders = {n["id"]: n["order"] for n in notebook["notes"]}
    conclusions = []
    for c in value.conclusions:
        if not set(c.evidence_ids) <= set(evidence):
            raise ValueError("结论引用了未提供的证据编号。")
        refs = [evidence[key] for key in c.evidence_ids]
        if c.status == "resolved" and (
            not refs or c.support != "explicit" or c.claim_type != "fact" or c.source_kind != "narrative"
        ):
            raise ValueError("已解释结论必须有直接正文依据；人物推测和外观相似只能标部分解释或待核对。")
        if c.status in {"unrevealed", "resolved"}:
            c.impact = "none"
        latest = max(refs, key=lambda e: (orders[e["note_id"]], e["end"])) if refs else None
        conclusions.append(
            {
                **c.model_dump(),
                "id": digest([note["id"], sorted(c.source_ids)])[:24],
                "evidence": refs,
                "revealed_at": {
                    "note_id": latest["note_id"],
                    "order": orders[latest["note_id"]],
                    "offset": latest["end"],
                }
                if latest
                else None,
                "blocking": c.impact != "none" and c.status in {"check", "conflict"},
            }
        )
    for decision in reading.get("_manual_decisions", []):
        matches = [c for c in conclusions if set(c["source_ids"]) & set(decision["source_ids"])]
        if (
            len(matches) != 1
            or set(matches[0]["source_ids"]) != set(decision["source_ids"])
            or matches[0]["status"] != decision["status"]
            or matches[0]["answer"] != decision["answer"]
            or set(matches[0]["evidence_ids"]) != set(decision["evidence_ids"])
        ):
            raise ValueError("必须保留人工处理的source_ids、status和answer；不能合并掉或反转人工决定。")
    overview = value.overview.model_dump()
    # Hooks and pending questions use the same statuses as the register, never an independent model list.
    pending = [c["question"] for c in conclusions if c["status"] != "resolved"]
    overview["questions"] = pending
    overview["hook"] = "；".join(pending) if pending else "当前阅读范围内，本章登记的问题均已有解释。"
    return {"overview": overview, "conclusions": conclusions}


def model_input(material):
    # Short IDs reduce transcription errors; persisted provenance retains its stable identifiers.
    aliases = {q["id"]: f"Q{i + 1:03d}" for i, q in enumerate(material["questions"])}
    aliases.update({e["id"]: f"E{i + 1:03d}" for i, e in enumerate(material["evidence"])})
    original_ids = list(dict.fromkeys(i for q in material["questions"] for i in q.get("original_ids", [])))
    aliases.update({key: f"R{i + 1:04d}" for i, key in enumerate(original_ids)})
    return remap(material, aliases), aliases


def remap(value, aliases):
    if isinstance(value, str):
        return aliases.get(value, value)
    if isinstance(value, list):
        return [remap(v, aliases) for v in value]
    if isinstance(value, dict):
        return {aliases.get(k, k): remap(v, aliases) for k, v in value.items()}
    return value


def validate_model(value, aliases, **kwargs):
    try:
        return validate(
            Consolidation.model_validate(remap(value.model_dump(), {v: k for k, v in aliases.items()})), **kwargs
        )
    except ValueError as exc:
        message = str(exc)
        for original, alias in aliases.items():
            message = message.replace(original, alias)
        raise ValueError(message) from exc


async def ensure(path, generator, note_ids, expected, report=None):
    from lib.novel_workflow.service import ask, current

    if not await asyncio.to_thread(enabled, path):
        return {"disabled": True}
    notebook = await asyncio.to_thread(current, path, expected)
    readings = await asyncio.to_thread(store.valid_readings, path, notebook)
    selected = [n for n in notebook["notes"] if n["id"] in note_ids]
    if len(selected) != len(set(note_ids)) or any(n["id"] not in readings for n in selected):
        raise ValueError("请先完成所选章节的 Note。")
    result = []
    for note in selected:
        reading = readings[note["id"]]
        cached = await asyncio.to_thread(load, path, note, reading, report, notebook=notebook, readings=readings)
        if cached:
            result.append(cached)
            continue
        material, evidence, questions = await asyncio.to_thread(inputs, path, note, reading, report)
        rule = await asyncio.to_thread(store.effective_rule, path, "conclusions")
        limit = (await asyncio.to_thread(settings.get, path))["summary_max_chars"]
        key = await asyncio.to_thread(basis, path, reading, report)
        # Oversized material must be explicitly partitioned, never silently truncated.
        presented, aliases = model_input(material)
        payload = json.dumps(presented, ensure_ascii=False)
        if len(payload) > 160000:
            raise ValueError("本章结论材料超过16万字符处理上限；已保留阅读结果，请缩小回查范围后重试。")
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "conclusions", "done": len(result), "total": len(selected), "note_id": note["id"]},
        )
        validate_draft = partial(
            validate_model,
            aliases=aliases,
            note=note,
            reading={**reading, "_manual_decisions": material["manual_decisions"]},
            evidence=evidence,
            questions=questions,
            notebook=notebook,
            limit=limit,
        )
        checkpoint = store.root(path) / "conclusions" / "drafts" / f"{key}.json"
        repair = {}

        async def checked(value, checkpoint=checkpoint, validate_draft=validate_draft, repair=repair):
            await run_noninterruptible_sync(store.write, checkpoint, value.model_dump())
            try:
                return validate_draft(value)
            except ValueError as exc:
                repair.update(draft=value.model_dump(), error=str(exc))
                raise

        class RepairGenerator:
            def __init__(self, repair):
                self.repair = repair

            def __getattr__(self, name):
                return getattr(generator, name)

            async def generate(self, request, **kwargs):
                if self.repair:
                    request = replace(
                        request,
                        prompt=request.prompt
                        + "\n仅修复以下草稿中的精确校验错误，保留其余结论与依据："
                        + json.dumps(self.repair, ensure_ascii=False),
                    )
                return await generator.generate(request, **kwargs)

        draft = None
        saved = await asyncio.to_thread(
            lambda checkpoint=checkpoint: load_json(checkpoint) if checkpoint.exists() else None
        )
        if saved:
            try:
                draft = await checked(Consolidation.model_validate(saved))
            except ValueError as exc:
                repair.update(draft=saved, error=str(exc))
        if draft is None:
            draft = await ask(
                path,
                RepairGenerator(repair),
                Consolidation,
                rule + f"\nsummary上限{limit}字。\n结论整理材料：" + payload,
                checked,
                max_output_tokens=16000,
            )
        value = {
            **draft,
            "basis": key,
            "reading_basis": reading["basis"],
            "report_id": (report or {}).get("id"),
            "note_id": note["id"],
            "created_at": now(),
            "source_questions": list(questions.values()),
            "available_evidence": [{"id": key, **ev} for key, ev in evidence.items()],
            "inspected_note_ids": sorted(
                {e["note_id"] for e in evidence.values()} | set((report or {}).get("inspected_note_ids", []))
            ),
        }
        await run_noninterruptible_sync(commit, path, note, expected, report, key, value)
        result.append(value)
    return {"notes": len(result), "blocking": sum(c["blocking"] for r in result for c in r["conclusions"])}


def commit(path, note, expected, report, key, value):
    from lib.artifacts.formal_write import project_metadata_lock
    from lib.novel_workflow.service import current

    with project_metadata_lock(path):
        current(path, expected)
        latest = store.note_result(path, note)
        if not latest or basis(path, latest, report) != key:
            raise ValueError("结论整理期间来源或规则发生变化，已保存模型响应，请重试。")
        inputs(path, note, latest, report)
        target = store.root(path) / "conclusions" / f"{note['id']}.json"
        if target.exists():
            old = load_json(target)
            store.write(store.root(path) / "history" / f"conclusions-{note['id']}-{old['basis']}.json", old)
        store.write(target, value)


def require_ready(path, note_ids):
    if not enabled(path):
        return
    notebook = store.state(path)
    readings = store.valid_readings(path, notebook)
    for note in notebook["notes"]:
        if note["id"] not in note_ids:
            continue
        value = load(path, note, readings.get(note["id"]), notebook=notebook, readings=readings)
        if not value:
            raise ValueError("请先完成所选章节的问题与结论整理。")
        blocking = [c["question"] for c in value["conclusions"] if c["blocking"]]
        if blocking:
            raise ValueError("这些结论影响人物身份、因果或对白，请先处理：" + "；".join(blocking))


def effective_reading(path, note, reading, *, notebook=None, readings=None):
    value = load(path, note, reading, notebook=notebook, readings=readings)
    if not value:
        return reading
    pending = [c for c in value["conclusions"] if c["status"] != "resolved"]
    return {
        **reading,
        "overview": value["overview"],
        "conclusion_basis": value["basis"],
        "conclusion_review": value,
        "reading_questions": [
            {"text": c["question"], "kind": "plot_unrevealed" if c["status"] == "unrevealed" else "extraction_check"}
            for c in pending
        ],
        "questions": [c["question"] for c in pending],
    }


async def prepare(path, generator, note_ids, expected):
    from lib.novel_understanding.service import NovelReadingInterrupted
    from lib.novel_workflow import understanding

    try:
        view = await asyncio.to_thread(understanding.view, path)
        for note_id in note_ids:
            report = next((r for r in view["reports"] if not r["stale"] and note_id in r["selected_note_ids"]), None)
            await ensure(path, generator, [note_id], expected, report)
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "complete", "done": len(note_ids), "total": len(note_ids)},
        )
        return {"notes": len(note_ids)}
    except (ValueError, NovelReadingInterrupted) as exc:
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", "error": str(exc)},
        )
        raise


def production_links(path, notebook, readings):
    result = []
    for note in notebook["notes"]:
        value = load(path, note, readings.get(note["id"]), notebook=notebook, readings=readings)
        if not value:
            continue
        for c in value["conclusions"]:
            if (
                c["status"] != "resolved"
                or c["claim_type"] != "fact"
                or c["source_kind"] != "narrative"
                or not c["revealed_at"]
            ):
                continue
            result.append(
                {
                    **c,
                    "subject": c["question"],
                    "description": c["answer"],
                    "status": "supported",
                    "kind": "reviewed_fact",
                    "note_ids": list(dict.fromkeys(e["note_id"] for e in c["evidence"])),
                    "story_time": "未明确",
                }
            )
    return result


def input_bases(path, note_ids):
    if not enabled(path):
        return {"enabled": False}
    notebook = store.state(path)
    readings = store.valid_readings(path, notebook)
    return {
        n["id"]: (load(path, n, readings.get(n["id"]), notebook=notebook, readings=readings) or {}).get("basis")
        for n in notebook["notes"]
        if n["id"] in note_ids
    }


def decision_file(path, note_id):
    return store.root(path) / "conclusion_decisions" / f"{note_id}.json"


def decisions(path, note_id, reading):
    file = decision_file(path, note_id)
    value = load_json(file) if file.exists() else {}
    return value.get("items", []) if value.get("reading_basis") == reading["basis"] else []


def decide(path, note_id, conclusion_id, status, answer, evidence_ids, reason, expected):
    from lib.artifacts.formal_write import project_metadata_lock
    from lib.novel_workflow.service import current

    with project_metadata_lock(path):
        notebook = current(path, expected)
        note = next((n for n in notebook["notes"] if n["id"] == note_id), None)
        if not note:
            raise ValueError("章节不存在")
        reading = store.note_result(path, note)
        value = load(path, note, reading)
        if not value:
            raise ValueError("结论来源已变化，请先重新整理。")
        item = next((c for c in value["conclusions"] if c["id"] == conclusion_id), None)
        if not item or not reason.strip() or not answer.strip():
            raise ValueError("请选择结论并填写处理结果与依据说明。")
        if status not in {"resolved", "partial", "unrevealed", "check", "conflict"}:
            raise ValueError("不支持的结论状态")
        pool = (
            {e["id"]: {key: field for key, field in e.items() if key != "id"} for e in value["available_evidence"]}
            if "available_evidence" in value
            else dict(zip(item["evidence_ids"], item["evidence"], strict=True))
        )
        if not set(evidence_ids) <= set(pool) or (status == "resolved" and not evidence_ids):
            raise ValueError("确认已解释时必须选择该结论的原文依据；依据不足请先回查原文。")
        items = decisions(path, note_id, reading)
        items = [d for d in items if not set(d["source_ids"]) & set(item["source_ids"])]
        items.append(
            {
                "source_ids": item["source_ids"],
                "source_questions": [q for q in value["source_questions"] if q["id"] in item["source_ids"]],
                "evidence_pool": {key: pool[key] for key in evidence_ids},
                "status": status,
                "answer": answer,
                "evidence_ids": evidence_ids,
                "reason": reason,
                "created_at": now(),
            }
        )
        file = decision_file(path, note_id)
        if file.exists():
            old = load_json(file)
            store.write(store.root(path) / "history" / f"conclusion-decision-{digest(old)}.json", old)
        store.write(file, {"reading_basis": reading["basis"], "items": items})
        return {"saved": True, "needs_consolidation": True}
