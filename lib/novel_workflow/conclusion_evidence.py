"""Question-specific, source-verified evidence; retrieval is not semantic approval."""

import asyncio
import json
import re
from typing import Literal

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_workflow import memory, scope, store
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json


class Finding(StrictModel):
    evidence_id: str
    relation: Literal["supports", "refutes", "context", "insufficient"]
    explanation: str = Field(min_length=1, max_length=1000)


class EvidenceReview(StrictModel):
    status: Literal["resolved", "partial", "unrevealed", "check", "conflict"]
    answer: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str]
    findings: list[Finding]


def catalog(path, note, reading, value):
    book = store.state(path)
    allowed = scope.available_ids(path, book)
    readings = store.valid_readings(path, book)
    originals = {
        (e["source_file"], e["start"], e["end"], e["quote"]): e["id"] for e in value.get("available_evidence", [])
    }
    rows, texts = {}, {}
    for other in book["notes"]:
        if other["id"] not in allowed or other["order"] > note["order"]:
            continue
        data = readings.get(other["id"])
        if not data:
            continue
        for record in memory.records(data) + [
            d for event in data.get("events", []) for d in event.get("dialogues", [])
        ]:
            ev = record.get("evidence")
            if not ev or ev["note_id"] != other["id"]:
                continue
            if not any(
                section["source_file"] == ev["source_file"]
                and section["start"] <= ev["start"] < ev["end"] <= section["end"]
                for section in other.get("sections", [])
            ):
                continue
            if ev["source_file"] not in texts:
                target = (path / ev["source_file"]).resolve()
                if not target.is_relative_to(path.resolve()):
                    continue
                texts[ev["source_file"]] = target.read_text()
            if texts[ev["source_file"]][ev["start"] : ev["end"]] != ev["quote"]:
                continue
            key = (ev["source_file"], ev["start"], ev["end"], ev["quote"])
            identity = originals.get(key, record["id"])
            start_bound = min(s["start"] for s in other.get("sections", [{"start": 0}]))
            end_bound = max(s["end"] for s in other.get("sections", [{"end": len(texts[ev["source_file"]])}]))
            context = texts[ev["source_file"]][max(start_bound, ev["start"] - 200) : min(end_bound, ev["end"] + 200)]
            rows[key] = {**ev, "id": identity, "note_title": other["title"], "context_quote": context}
        # Recover literal passages omitted by Note extraction; never search unread/future chapters.
        for section in other.get("sections", []):
            source = section["source_file"]
            if source not in texts:
                target = (path / source).resolve()
                if not target.is_relative_to(path.resolve()):
                    continue
                texts[source] = target.read_text()
            text = texts[source]
            for match in re.finditer(r"\S[^\r\n]*", text[section["start"] : section["end"]]):
                quote = match.group().rstrip()
                if len(quote) < 6:
                    continue
                start = section["start"] + match.start()
                ev = {
                    "note_id": other["id"],
                    "source_file": source,
                    "start": start,
                    "end": start + len(quote),
                    "quote": quote,
                }
                key = (source, start, ev["end"], quote)
                rows.setdefault(
                    key,
                    {
                        **ev,
                        "id": originals.get(key, digest(ev)[:24]),
                        "note_title": other["title"],
                        "context_quote": text[
                            max(section["start"], start - 200) : min(section["end"], ev["end"] + 200)
                        ],
                    },
                )
    return list(rows.values())


def related(item, rows):
    text = item["question"]
    quoted = re.findall(r"[‘“『「]([^‘’“”『』「」]{4,})[’”』」]", text)

    def compact(x):
        return re.sub(r"\s+", "", x)

    terms = {text[i : i + 2] for i in range(len(text) - 1) if re.fullmatch(r"[\u4e00-\u9fff]{2}", text[i : i + 2])}
    terms -= {
        "中的",
        "是否",
        "什么",
        "一个",
        "这个",
        "可以",
        "如何",
        "因为",
        "所以",
        "他们",
        "这里",
        "那里",
        "目前",
        "还是",
        "不是",
        "已经",
    }
    ranked = []
    for row in rows:
        hits = sorted(t for t in terms if t in row["quote"])
        exact = any(compact(q) in compact(row["quote"]) for q in quoted)
        linked = row["id"] in item.get("evidence_ids", [])
        if not (exact or linked or len(hits) >= 4):
            continue
        reason = (
            "包含疑点中的原句；仍需区分人物说法与客观规则"
            if exact
            else "原检查关联的引文，尚需核对支持关系"
            if linked
            else "检索候选，包含关键词：" + "、".join(hits[:5])
        )
        ranked.append((1000 * exact + 100 * linked + len(hits), {**row, "retrieval_reason": reason}))
    ranked.sort(key=lambda x: (-x[0], x[1]["start"]))
    if any(score >= 1000 for score, _ in ranked):
        ranked = [(score, row) for score, row in ranked if score >= 1000]
    return [r for _, r in ranked[:6]]


def enrich(path, note, reading, value):
    rows = catalog(path, note, reading, value)
    items = []
    for item in value["conclusions"]:
        candidates = related(item, rows)
        key = digest([value["basis"], item, candidates, store.effective_rule(path, "conclusion_evidence")])
        file = store.root(path) / "conclusion_evidence" / f"{key}.json"
        saved = load_json(file) if file.exists() else None
        items.append({**item, "related_evidence": candidates, "evidence_review": saved, "evidence_review_basis": key})
    return {**value, "conclusions": items}


async def generate(path, generator, note_ids, expected, conclusion_id):
    from lib.novel_workflow import conclusions
    from lib.novel_workflow.service import ask, current

    book = await asyncio.to_thread(current, path, expected)
    if len(note_ids) != 1:
        raise ValueError("定向回查每次只处理一章中的一个疑点")
    note = next(n for n in book["notes"] if n["id"] == note_ids[0])
    reading = await asyncio.to_thread(store.note_result, path, note)
    value = await asyncio.to_thread(conclusions.load, path, note, reading)
    if not value:
        raise ValueError("本章结论已变化，请刷新")
    enriched = await asyncio.to_thread(enrich, path, note, reading, value)
    item = next((x for x in enriched["conclusions"] if x["id"] == conclusion_id), None)
    if not item:
        raise ValueError("待核对疑点不存在")
    candidates = item["related_evidence"]
    if not candidates:
        raise ValueError("当前及已读前章未找到相关原文；请检查可用范围或继续阅读，不能据此认定问题为真或为假")
    if item["evidence_review"]:
        return {"cached": True}
    payload = json.dumps(
        {"question": item["question"], "previous_answer": item["answer"], "sources": candidates}, ensure_ascii=False
    )
    if len(payload) > 18000:
        raise ValueError("本疑点相关材料超过18000字符上限；未调用模型，请缩小问题范围")
    ids = {e["id"] for e in candidates}

    def validate(result):
        found = [f.evidence_id for f in result.findings]
        if len(found) != len(ids) or set(found) != ids or not set(result.evidence_ids) <= ids:
            raise ValueError("必须逐条说明每段候选原文的支持关系，且只能引用给定ID")
        if result.status == "resolved" and not result.evidence_ids:
            raise ValueError("已解释必须提供依据；不确定则保留部分解释或待核对")
        return result.model_dump()

    await run_noninterruptible_sync(
        store.write,
        store.root(path) / "progress.json",
        {"phase": "conclusion_evidence", "done": 0, "total": 1, "note_id": note["id"]},
    )
    try:
        rule = await asyncio.to_thread(store.effective_rule, path, "conclusion_evidence")
        result = await ask(
            path,
            generator,
            EvidenceReview,
            rule + "\n本次疑点与候选原文：" + payload,
            validate,
            max_output_tokens=5000,
        )
        from lib.artifacts.formal_write import project_metadata_lock

        def commit():
            with project_metadata_lock(path):
                current(path, expected)
                latest_reading = store.note_result(path, note)
                latest = conclusions.load(path, note, latest_reading)
                if not latest:
                    raise ValueError("回查期间章节结论已变化，请刷新")
                fresh = enrich(path, note, latest_reading, latest)
                target = next(x for x in fresh["conclusions"] if x["id"] == conclusion_id)
                if target["evidence_review_basis"] != item["evidence_review_basis"]:
                    raise ValueError("回查期间原文或疑点已变化，未采用旧建议")
                store.write(
                    store.root(path) / "conclusion_evidence" / f"{item['evidence_review_basis']}.json",
                    {**result, "created_at": now()},
                )

        await run_noninterruptible_sync(commit)
        await run_noninterruptible_sync(
            store.write, store.root(path) / "progress.json", {"phase": "complete", "done": 1, "total": 1}
        )
        return {"reviewed": conclusion_id}
    except Exception as exc:
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "failed", "done": 0, "total": 1, "error": str(exc)},
        )
        raise
