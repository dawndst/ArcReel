"""Range-limited adaptation advice with citations and no mutation authority."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from uuid import uuid4

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.service import NovelReadingInterrupted, check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import memory, store, synthesis
from lib.novel_workflow.models import RangeConclusion, ScopeReview


def validate(value, facts, note_ids):
    covered = set()
    for advice in value.advice:
        selected = set(advice.note_ids)
        if not selected <= note_ids:
            raise ValueError("Advice references a Note outside this range")
        if advice.action == "combine" and len(selected) < 2:
            raise ValueError("Combining requires two distinct Notes")
        if any(i not in facts or facts[i]["evidence"]["note_id"] not in selected for i in advice.evidence_ids):
            raise ValueError("Advice evidence must belong to its referenced Notes")
        if {facts[i]["evidence"]["note_id"] for i in advice.evidence_ids} != selected:
            raise ValueError("Every advised Note needs supporting evidence")
        covered |= selected
    if covered != note_ids:
        raise ValueError("Every supplied Note needs an explicit adaptation recommendation")
    return value.model_dump()


async def review_scope(path, generator, note_ids, expected):
    from lib.novel_workflow.service import ask, current
    from lib.novel_workflow.understanding import require_understood

    await asyncio.to_thread(require_understood, path, note_ids)
    notebook = await asyncio.to_thread(current, path, expected)
    wanted = set(note_ids)
    notes = [n for n in notebook["notes"] if n["id"] in wanted]
    if not notes or len(notes) != len(wanted):
        raise ValueError("Select existing Notes")
    rules = await asyncio.to_thread(store.rule, path, "review")
    facts, bases, inputs = {}, {}, []
    for note in notes:
        reading = await asyncio.to_thread(store.note_result, path, note)
        if not reading or not reading.get("overview"):
            raise ValueError("Complete chapter reading before range review")
        bases[note["id"]] = reading["basis"]
        items = memory.records(reading)
        facts.update({v["id"]: v for v in items})
        # All detail records remain available to bounded batches; never silently truncate Notes.
        inputs.extend(
            {"note_id": note["id"], "title": note["title"], "overview": reading["overview"], "records": batch}
            for batch in synthesis.packs(items, 14000)
        )
    key = digest([bases, rules])
    checkpoint = store.root(path) / "review_runs" / f"{key}.json"
    run = (
        await asyncio.to_thread(load_json, checkpoint)
        if await asyncio.to_thread(checkpoint.exists)
        else {"cursor": 0, "sections": []}
    )
    batches = list(synthesis.packs(inputs, 26000))
    progress = {"phase": "review", "total": len(batches), "done": run["cursor"], "started_at": now()}
    try:
        while run["cursor"] < len(batches):
            check_stop()
            batch = batches[run["cursor"]]
            batch_facts = {v["id"]: v for node in batch for v in node["records"]}
            ids = {n["note_id"] for n in batch}
            result = await ask(
                path,
                generator,
                ScopeReview,
                rules + "\n本次已读范围材料：" + json.dumps(batch, ensure_ascii=False),
                partial(validate, facts=batch_facts, note_ids=ids),
            )
            run["sections"].append(result)
            run["cursor"] += 1
            await run_noninterruptible_sync(store.write, checkpoint, run)
            progress["done"] = run["cursor"]
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
        # A second bounded pass reviews advice across batch boundaries, retaining first-pass details.
        overview_nodes = []
        for note in notes:
            advice = [a for section in run["sections"] for a in section["advice"] if note["id"] in a["note_ids"]]
            for advice_batch in synthesis.packs(advice, 16000):
                evidence_ids = list(
                    dict.fromkeys(
                        i
                        for a in advice_batch
                        for i in a["evidence_ids"]
                        if facts[i]["evidence"]["note_id"] == note["id"]
                    )
                )
                overview_nodes.append(
                    {
                        "note_id": note["id"],
                        "title": note["title"],
                        "evidence_ids": evidence_ids,
                        "advice": advice_batch,
                    }
                )
        overview = []
        for batch in synthesis.packs(overview_nodes, 26000):
            check_stop()
            ids = {v["note_id"] for v in batch}
            allowed = {i: facts[i] for v in batch for i in v["evidence_ids"]}
            await asyncio.to_thread(current, path, expected)
            summary_key = digest([rules, batch, "advice"])
            cache = store.root(path) / "review_summaries" / f"{summary_key}.json"
            if await asyncio.to_thread(cache.exists):
                result = await asyncio.to_thread(load_json, cache)
            else:
                result = await ask(
                    path,
                    generator,
                    ScopeReview,
                    rules + "\n汇总已完成的取舍分析，检查跨章因果与组合建议：" + json.dumps(batch, ensure_ascii=False),
                    partial(validate, facts=allowed, note_ids=ids),
                )
                await run_noninterruptible_sync(store.write, cache, result)
            overview.append(result)
        nodes = [
            {
                "theme": section["theme"],
                "mainline": section["mainline"],
                "advice": advice_batch,
                "evidence_ids": list(dict.fromkeys(i for a in advice_batch for i in a["evidence_ids"])),
            }
            for section in overview
            for advice_batch in synthesis.packs(section["advice"], 16000)
        ]
        while True:
            next_level = []
            for batch in synthesis.packs(nodes, 24000):
                allowed_ids = {i for node in batch for i in node["evidence_ids"]}

                def valid_conclusion(value, allowed_ids=allowed_ids):
                    if not set(value.evidence_ids) <= allowed_ids:
                        raise ValueError("Range conclusion cites evidence outside its inputs")
                    return value.model_dump()

                summary_key = digest([rules, batch])
                cache = store.root(path) / "review_summaries" / f"{summary_key}.json"
                if await asyncio.to_thread(cache.exists):
                    conclusion = await asyncio.to_thread(load_json, cache)
                else:
                    conclusion = await ask(
                        path,
                        generator,
                        RangeConclusion,
                        rules + "\n范围总览材料：" + json.dumps(batch, ensure_ascii=False),
                        valid_conclusion,
                    )
                    await run_noninterruptible_sync(store.write, cache, conclusion)
                next_level.append(conclusion)
            if len(next_level) == 1:
                conclusion = next_level[0]
                break
            if len(next_level) >= len(nodes) and all("advice" not in n for n in nodes):
                raise ValueError("Range conclusion cannot fit bounded context")
            nodes = next_level
        await asyncio.to_thread(current, path, expected)
        if await asyncio.to_thread(store.rule, path, "review") != rules:
            raise ValueError("Review rules changed during generation")
        for note in notes:
            reading = await asyncio.to_thread(store.note_result, path, note)
            if not reading or reading["basis"] != bases[note["id"]]:
                raise ValueError("Reading changed during range review")
        result = {
            "id": key,
            "note_ids": [n["id"] for n in notes],
            "note_bases": bases,
            "rule_basis": digest(rules),
            "source_basis": expected,
            "conclusion": conclusion,
            "sections": run["sections"],
            "overview": overview,
            "created_at": now(),
            "applied": False,
            "evidence": facts,
            "scope_kind": "whole_book" if len(notes) == len(notebook["notes"]) else "selected",
        }
        target = store.root(path) / "reviews" / f"{key}.json"
        if await asyncio.to_thread(target.exists):
            old = await asyncio.to_thread(load_json, target)
            await run_noninterruptible_sync(
                store.write, store.root(path) / "history" / f"review-{uuid4().hex}.json", old
            )
        await run_noninterruptible_sync(store.write, target, result)
        progress.update(phase="complete", done=len(batches))
        return {"review_id": key, "notes": len(notes)}
    except Exception as exc:
        progress.update(phase="stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", error=str(exc))
        raise
    finally:
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
