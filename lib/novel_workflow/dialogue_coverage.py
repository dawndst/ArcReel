"""Trace extracted key dialogue to shots without treating omission as a production veto."""

from __future__ import annotations

from collections import Counter
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store


def normalized(text):
    return "".join(text.split()).strip('「」『』“”‘’"')


def source_dialogues(reading, chunk):
    """Retain source positions: identical words on different occasions are different dialogue."""
    records = list(reading.get("dialogues", [])) + [
        d for event in reading.get("events", []) for d in event.get("dialogues", [])
    ]
    grouped = {}
    for d in records:
        ev = d.get("evidence", {})
        if (
            not d.get("id")
            or ev.get("source_file") != chunk["source_file"]
            or not chunk["start"] <= ev.get("start", -1) < ev.get("end", -1) <= chunk["end"]
        ):
            continue
        key = (ev["start"], ev["end"], d.get("speaker"), normalized(d["quote"]))
        item = grouped.setdefault(key, {**d, "source_ids": [], "purposes": []})
        if d["id"] not in item["source_ids"]:
            item["source_ids"].append(d["id"])
        if d.get("value") and d["value"] not in item["purposes"]:
            item["purposes"].append(d["value"])
    return sorted(grouped.values(), key=lambda d: (d["evidence"]["start"], d["evidence"]["end"]))


def report(batch, reading, chunk):
    entries = [
        {
            "dialogue_id": d["id"],
            "source_ids": d["source_ids"],
            "quote": d["quote"],
            "speaker": d.get("speaker", "未明确"),
            "purposes": d["purposes"],
            "evidence": d["evidence"],
            "locations": [],
            "status": "unassigned",
        }
        for d in source_dialogues(reading, chunk)
    ]
    intervals = {e["dialogue_id"]: [] for e in entries}
    for scene in batch["scenes"]:
        for shot in scene["shots"]:
            ev = shot.get("evidence", {})
            for si, segment in enumerate(shot["segments"]):
                for ui, u in enumerate(segment.get("utterances", [])):
                    if u.get("origin", "source") != "source":
                        continue  # Adaptation must not masquerade as retention of the original wording.
                    text = normalized(u["text"])
                    candidates = [
                        e
                        for e in entries
                        if text
                        and ev.get("start", -1) <= e["evidence"]["start"] < e["evidence"]["end"] <= ev.get("end", -1)
                        and (text in normalized(e["quote"]) or normalized(e["quote"]) in text)
                    ]
                    if len(candidates) > 1:
                        candidates = [e for e in candidates if e["speaker"] == u.get("speaker")]
                    if len(candidates) != 1:
                        continue  # Repeated short quotations need explicit source disambiguation.
                    e = candidates[0]
                    quote = normalized(e["quote"])
                    if quote in text:
                        span = (0, len(quote))
                    elif quote.count(text) == 1:
                        begin = quote.index(text)
                        span = (begin, begin + len(text))
                    else:
                        continue
                    intervals[e["dialogue_id"]].append(span)
                    e["locations"].append({"shot_id": shot["id"], "segment_index": si, "utterance_index": ui})
    decisions = batch.get("dialogue_decisions", {})
    for e in entries:
        spans = sorted(intervals[e["dialogue_id"]])
        end = 0
        for begin, finish in spans:
            if begin > end:
                break
            end = max(end, finish)
        e["status"] = "retained" if end >= len(normalized(e["quote"])) else "partial" if spans else "unassigned"
        decision = decisions.get(e["dialogue_id"])
        if decision and decision.get("decision") == "omit" and e["status"] != "retained":
            e["reason"] = decision["reason"]
            e["status"] = "omitted"
    counts = Counter(e["status"] for e in entries)
    value = {"entries": entries, "counts": {s: counts[s] for s in ("retained", "partial", "unassigned", "omitted")}}
    value["revision"] = digest([batch["basis"], reading["basis"], value, decisions])
    return value


def decide(path, project, batch_basis, expected, coverage_revision, dialogue_id, decision, reason):
    from lib.novel_workflow import chapters, scene_library

    if decision not in {"omit", "restore"} or len(reason.strip()) < 10:
        raise ValueError("请选择省略或恢复，并填写至少10字的处理理由")
    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        readings = store.valid_readings(path, notebook)
        library = scene_library.catalog(path)
        batch = next((b for b in library["batches"].values() if b["basis"] == batch_basis), None)
        if not batch or not scene_library.valid_batch(path, batch, notebook, readings):
            raise ValueError("场镜依据已变化，请刷新后处理对白")
        note = next(n for n in notebook["notes"] if n["id"] == batch["note_id"])
        chunk = chapters.chunks(path, project, note)[batch["part"]]
        current = report(batch, readings[batch["note_id"]], chunk)
        if current["revision"] != coverage_revision:
            raise ValueError("对白去向已变化，请刷新后确认")
        entry = next((e for e in current["entries"] if e["dialogue_id"] == dialogue_id), None)
        if entry is None:
            raise ValueError("对白不属于当前原文片段")
        if decision == "omit" and entry["status"] == "retained":
            raise ValueError("这句对白已完整安排；省略决定不会删除镜头，请先编辑镜头内容")
        store.write(store.root(path) / "history" / f"dialogue-decision-{uuid4().hex}.json", batch)
        batch.setdefault("dialogue_decisions", {})[dialogue_id] = {
            "decision": decision,
            "reason": reason.strip(),
            "actor": "human",
            "at": now(),
        }
        store.write(store.root(path) / "scene_library.json", library)
        return {"saved": True}
