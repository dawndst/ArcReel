"""Source-indexed chapter editions; original text remains the evidence authority."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import chapters, memory, store
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json


class Passage(StrictModel):
    unit: int = Field(ge=0)
    treatment: Literal["retain", "condense", "omit", "uncertain"]
    text: str = Field(max_length=5000)
    reason: str = Field(min_length=1, max_length=500)


class Edition(StrictModel):
    passages: list[Passage] = Field(min_length=1)


def units(chunk):
    text = chunk["text"]
    result, start = [], 0
    while start < len(text):
        end = min(start + 900, len(text))
        if end < len(text):
            split = text.rfind("\n", start + 450, end)
            if split >= 0:
                end = split + 1
        result.append(
            {
                "unit": len(result),
                "text": text[start:end],
                "start": chunk["start"] + start,
                "end": chunk["start"] + end,
                "source_file": chunk["source_file"],
            }
        )
        start = end
    return result


def protected(reading, chunk):
    claims = memory.records(reading)
    refs = [v["evidence"] for v in claims if v.get("evidence")]
    refs += [d["evidence"] for e in reading.get("events", []) for d in e.get("dialogues", []) if d.get("evidence")]
    return [
        e
        for e in refs
        if e["source_file"] == chunk["source_file"] and e["start"] < chunk["end"] and e["end"] > chunk["start"]
    ]


def validate(value, source_units, anchors):
    rows = sorted(value.passages, key=lambda p: p.unit)
    if [p.unit for p in rows] != [u["unit"] for u in source_units]:
        raise ValueError("精编必须逐段覆盖全部原文单元，不得漏段或重复")
    result = []
    for p, unit in zip(rows, source_units, strict=True):
        locked = any(e["start"] < unit["end"] and e["end"] > unit["start"] for e in anchors)
        if p.treatment == "omit" and (locked or p.text.strip()):
            raise ValueError("含已登记事实、线索或台词的单元不能省略；省略单元正文必须为空")
        if p.treatment != "omit" and not p.text.strip():
            raise ValueError("保留、压缩或待定单元必须有正文")
        # Uncertain material stays verbatim; this decision is reversible without another model call.
        text = unit["text"] if p.treatment in {"retain", "uncertain"} else p.text
        if p.treatment == "condense" and locked:
            compact = "".join(text.split())
            spans = [
                (max(e["start"], unit["start"]) - unit["start"], min(e["end"], unit["end"]) - unit["start"])
                for e in anchors
                if e["start"] < unit["end"] and e["end"] > unit["start"]
            ]
            if any("".join(unit["text"][a:b].split()) not in compact for a, b in spans):
                p.treatment = "retain"
                p.reason = "受保护原文未被逐字保留，系统保留本单元原文"
                text = unit["text"]
        result.append(
            {
                **p.model_dump(),
                "text": text,
                "evidence": {k: unit[k] for k in ("source_file", "start", "end")},
                "original_quote": unit["text"],
                "protected": locked,
            }
        )
    return result


def edition_key(reading, rule):
    return digest([reading["basis"], rule, 1])


def load(path, note, reading, *, history=False):
    if not reading:
        return None
    key = edition_key(reading, store.effective_rule(path, "condense"))
    file = store.root(path) / "editions" / note["id"] / f"{key}.json"
    if file.exists():
        return load_json(file)
    if history:
        files = sorted(file.parent.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for previous in files:
            value = load_json(previous)
            if value.get("reading_basis") == reading["basis"]:
                return value
    return None


async def ensure(path, generator, note, reading, project, expected):
    from lib.novel_workflow.service import ask, current

    rule = await asyncio.to_thread(store.effective_rule, path, "condense")
    cached = await asyncio.to_thread(load, path, note, reading)
    if cached:
        return cached
    chunks = await asyncio.to_thread(chapters.chunks, path, project, note)
    parts = []
    for index, chunk in enumerate(chunks):
        check_stop()
        source_units, anchors = units(chunk), protected(reading, chunk)
        key = digest([rule, source_units, anchors])
        file = store.root(path) / "edition_parts" / f"{key}.json"
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "condensing", "done": index, "total": len(chunks), "note_id": note["id"]},
        )
        if await asyncio.to_thread(file.exists):
            passages = await asyncio.to_thread(load_json, file)
        else:
            passages = []
            offset = 0
            while offset < len(source_units):
                check_stop()
                await run_noninterruptible_sync(
                    store.write,
                    store.root(path) / "progress.json",
                    {
                        "phase": "condensing",
                        "done": index,
                        "total": len(chunks),
                        "note_id": note["id"],
                        "part": offset + 1,
                        "parts": len(source_units),
                    },
                )
                group = source_units[offset : offset + 2]
                # Reuse existing two-unit checkpoints; new material is processed in larger bounded groups.
                small_refs = [e for e in anchors if e["start"] < group[-1]["end"] and e["end"] > group[0]["start"]]
                small_cache = store.root(path) / "edition_parts" / f"{digest([rule, group, small_refs])}.json"
                if not await asyncio.to_thread(small_cache.exists):
                    end = min(offset + 8, len(source_units))
                    for candidate in range(offset + 2, end, 2):
                        prior_group = source_units[candidate : candidate + 2]
                        prior_refs = [
                            e
                            for e in anchors
                            if e["start"] < prior_group[-1]["end"] and e["end"] > prior_group[0]["start"]
                        ]
                        prior_file = (
                            store.root(path) / "edition_parts" / f"{digest([rule, prior_group, prior_refs])}.json"
                        )
                        if await asyncio.to_thread(prior_file.exists):
                            end = candidate
                            break
                    group = source_units[offset:end]
                refs = [e for e in anchors if e["start"] < group[-1]["end"] and e["end"] > group[0]["start"]]
                subfile = store.root(path) / "edition_parts" / f"{digest([rule, group, refs])}.json"
                if await asyncio.to_thread(subfile.exists):
                    rows = await asyncio.to_thread(load_json, subfile)
                else:
                    rows = await ask(
                        path,
                        generator,
                        Edition,
                        rule
                        + "\nretain或uncertain的text可仅填写保留原文，程序会逐字回填原文；condense仍输出完整精简正文。\n"
                        + json.dumps({"source_units": group, "protected_evidence": refs}, ensure_ascii=False),
                        lambda v, group=group, refs=refs: validate(v, group, refs),
                        max_output_tokens=8000,
                        grow_output=True,
                    )
                    await run_noninterruptible_sync(store.write, subfile, rows)
                passages.extend(rows)
                offset += len(group)
            await run_noninterruptible_sync(store.write, file, passages)
        parts.append(
            {"source_file": chunk["source_file"], "start": chunk["start"], "end": chunk["end"], "passages": passages}
        )
    await asyncio.to_thread(current, path, expected)
    if rule != await asyncio.to_thread(store.effective_rule, path, "condense"):
        raise ValueError("精编规则已变化，已完成片段保留，请重试")
    live = await asyncio.to_thread(store.note_result, path, note)
    if not live or live["basis"] != reading["basis"]:
        raise ValueError("Note已变化，请刷新后重新生成精编稿")
    result = {
        "basis": edition_key(reading, rule),
        "reading_basis": reading["basis"],
        "created_at": now(),
        "parts": parts,
        "original_chars": sum(len(c["text"]) for c in chunks),
        "edited_chars": sum(len(p["text"]) for part in parts for p in part["passages"]),
    }
    await run_noninterruptible_sync(
        store.write, store.root(path) / "editions" / note["id"] / f"{result['basis']}.json", result
    )
    return result


async def generate(path, generator, note_ids, expected):
    from lib.novel_workflow import scope
    from lib.novel_workflow.service import current

    notebook = await asyncio.to_thread(current, path, expected)
    await asyncio.to_thread(scope.require, path, notebook, note_ids)
    readings = await asyncio.to_thread(store.valid_readings, path, notebook)
    notes = [n for n in notebook["notes"] if n["id"] in note_ids]
    if not notes or len(notes) != len(set(note_ids)) or any(n["id"] not in readings for n in notes):
        raise ValueError("请先生成所选章节的 Note")
    project = await asyncio.to_thread(load_json, path / "project.json")
    for note in notes:
        await ensure(path, generator, note, readings[note["id"]], project, expected)
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "idle", "done": len(notes), "total": len(notes)}
    )
    return {"condensed": len(notes)}


def material(edition, reading, chunk):
    """Only current-chunk prose and exact evidence enter production; no future passages."""
    part = next((p for p in edition["parts"] if all(p[k] == chunk[k] for k in ("source_file", "start", "end"))), None)
    if not part:
        raise ValueError("精编稿原文分块已变化，请更新精编稿")
    prose = "\n".join(p["text"] for p in part["passages"] if p["text"])
    anchors = protected(reading, chunk)
    # Every excerpt is clipped to this request's reveal boundary.
    spans = sorted({(max(e["start"], chunk["start"]), min(e["end"], chunk["end"])) for e in anchors})
    quotes = [chunk["text"][a - chunk["start"] : b - chunk["start"]] for a, b in spans]
    return {
        "edition": prose,
        "source_excerpts": quotes,
        "source_policy": "精编是改编阅读材料；事实及逐字引文只取原文摘录，不得把精编转述当作原句。",
    }


def metadata(path, note, reading):
    value = load(path, note, reading, history=True)
    return {k: value[k] for k in ("basis", "created_at", "original_chars", "edited_chars")} if value else None
