"""Bounded, resumable reading and SVT aggregation. No model-controlled Note merging."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from lib.backends.text_backends.base import TextGenerationRequest, TextOutputTruncatedError
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.infra.text_utils import strip_json_code_fences
from lib.novel_understanding.service import NovelReadingInterrupted, check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import chapters, memory, store, synthesis
from lib.novel_workflow.models import Reading, SVTBatch


def current(path: Path, expected: str) -> dict:
    project = load_json(path / "project.json")
    return store.require_current(path, project, expected)


def evidence(text: str, quote: str, part: dict) -> dict:
    pos = text.find(quote)
    if pos < 0 or text.find(quote, pos + 1) >= 0:
        raise ValueError(f"Quote must occur exactly once in this fragment: {quote[:90]}")
    return {
        "source_file": part["source_file"],
        "start": part["start"] + pos,
        "end": part["start"] + pos + len(quote),
        "quote": quote,
        "note_id": part["note_id"],
    }


def ground(reading: Reading, part: dict, seed_ids=frozenset()) -> dict:
    data = reading.model_dump()
    for thread in data["threads"]:
        if thread["kind"] == "seed" and thread["seed_id"] is not None:
            raise ValueError("A new seed cannot resolve another seed")
        if thread["kind"] == "resolution" and thread["seed_id"] is not None and thread["seed_id"] not in seed_ids:
            raise ValueError("Resolution references a seed outside the supplied past evidence")
    for bucket in memory.BUCKETS:
        for item in data[bucket]:
            item["evidence"] = evidence(part["text"], item["quote"], part)
            item["id"] = digest([bucket, item])[:24]
            if bucket == "events":
                for dialogue in item["dialogues"]:
                    dialogue["evidence"] = evidence(part["text"], dialogue["quote"], part)
                    dialogue["id"] = digest(["dialogue", dialogue["evidence"]])[:24]
    return data


async def ask(path: Path, generator, schema, prompt: str, validate=lambda value: value):
    error = ""
    for _ in range(3):
        check_stop()
        response = await generator.generate(
            TextGenerationRequest(
                prompt=prompt
                + "\n只输出 JSON，结构："
                + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                + error,
                max_output_tokens=12000,
            ),
            project_name=path.name,
            require_complete=True,
        )
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "responses" / f"{uuid4().hex}.json",
            {"text": response.text, "created_at": now()},
        )
        try:
            return validate(schema.model_validate_json(strip_json_code_fences(response.text)))
        except (ValidationError, ValueError) as exc:
            error = "\n修正上次输出中的问题，不删掉原始事实：" + str(exc)[:2200]
    raise ValueError("Model output failed evidence or schema validation; responses saved")


async def read_part(path, generator, note, part, rules, rolling, expected, seed_ids=frozenset()):
    key = digest([note["basis"], rules, part["source_file"], part["start"], part["end"], rolling])
    target = store.root(path) / "parts" / f"{key}.json"
    if await asyncio.to_thread(target.exists):
        return [await asyncio.to_thread(load_json, target)]
    marker = target.with_suffix(".split.json")
    split = await asyncio.to_thread(marker.exists)
    if not split:
        prompt = rules + "\n已读片段提示（不能作为本段证据）：" + rolling + "\n当前原文：\n" + part["text"]
        try:
            data = await ask(
                path,
                generator,
                Reading,
                prompt,
                lambda value: ground(value, part, seed_ids) if value.complete else None,
            )
            await asyncio.to_thread(current, path, expected)
            if data is not None:
                await run_noninterruptible_sync(store.write, target, data)
                return [data]
        except TextOutputTruncatedError:
            pass
    if len(part["text"]) <= 700:
        raise ValueError("Reading still incomplete at minimum fragment size; revise reading rules")
    await run_noninterruptible_sync(store.write, marker, {"split": True})
    middle = len(part["text"]) // 2
    results = []
    for start, end in ((0, middle), (middle, len(part["text"]))):
        check_stop()
        child = {**part, "start": part["start"] + start, "end": part["start"] + end, "text": part["text"][start:end]}
        child_context = rolling + "\n" + "\n".join(v["summary"] for v in results[-2:])[-2500:]
        extra_records = []
        for previous in results:
            for record in previous["threads"] + previous["aliases"]:
                if len(json.dumps([*extra_records, record], ensure_ascii=False)) <= 5000:
                    extra_records.append(record)
        child_context += "\n已读子块台账：" + json.dumps(extra_records, ensure_ascii=False)
        child_seeds = seed_ids | {v["id"] for v in extra_records if v.get("kind") == "seed"}
        results.extend(await read_part(path, generator, note, child, rules, child_context, expected, child_seeds))
    return results


def prior_context(path: Path, notebook: dict, note: dict, text: str, extra=()) -> str:
    book = memory.ledger(path, notebook, through=note["order"] - 1, extra=extra)
    return json.dumps(memory.context(book, text), ensure_ascii=False)


async def read_notes(path: Path, generator, note_ids: list[str], expected: str) -> dict:
    from lib.novel_workflow import scope

    await run_noninterruptible_sync(scope.prepare_read, path, note_ids, expected)
    notebook = await asyncio.to_thread(current, path, expected)
    wanted = set(note_ids)
    notes = [n for n in notebook["notes"] if n["id"] in wanted]
    if not notes or len(notes) != len(wanted):
        raise ValueError("Select existing Notes")
    rules = await asyncio.to_thread(store.rule, path, "read")
    from lib.novel_workflow import settings

    chapter_rule = await asyncio.to_thread(settings.chapter_rule, path)
    progress = {"phase": "reading", "total": len(notes), "done": 0, "note_id": None, "started_at": now()}
    try:
        for index, note in enumerate(notes):
            check_stop()
            await asyncio.to_thread(current, path, expected)
            await asyncio.to_thread(scope.require, path, notebook, [note["id"]])
            progress.update(done=index, note_id=note["id"])
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
            if await asyncio.to_thread(store.note_result, path, note):
                continue
            context_basis = digest(await asyncio.to_thread(store.reading_context, path, note))
            project = await asyncio.to_thread(load_json, path / "project.json")
            parts = await asyncio.to_thread(chapters.chunks, path, project, note)
            extracted = []
            for i, part in enumerate(parts):
                check_stop()
                progress.update(part=i + 1, parts=len(parts))
                await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
                rolling = "\n".join(v["summary"] for v in extracted[-2:])[-2500:]
                rolling += await asyncio.to_thread(prior_context, path, notebook, note, part["text"], extracted)
                book = await asyncio.to_thread(
                    memory.ledger, path, notebook, through=note["order"] - 1, extra=extracted
                )
                supplied = memory.context(book, part["text"])
                seed_ids = {v["id"] for v in supplied["records"] if v.get("kind") == "seed"}
                extracted.extend(await read_part(path, generator, note, part, rules, rolling, expected, seed_ids))
            await asyncio.to_thread(current, path, expected)
            overview = await synthesis.chapter(path, generator, extracted, chapter_rule)
            await asyncio.to_thread(current, path, expected)
            live_rule = await asyncio.to_thread(store.rule, path, "read")
            if live_rule != rules or await asyncio.to_thread(settings.chapter_rule, path) != chapter_rule:
                raise ValueError("Reading rules changed during generation; completed fragment cache is preserved")
            result = {
                "basis": digest([note["basis"], rules, chapter_rule, context_basis, overview, extracted, 2]),
                "context_basis": context_basis,
                "overview": overview,
                "summaries": [v["summary"] for v in extracted],
                "created_at": now(),
                "chunks": len(extracted),
                **{key: [item for v in extracted for item in v[key]] for key in (*memory.BUCKETS, "questions")},
            }
            if context_basis != digest(await asyncio.to_thread(store.reading_context, path, note)):
                raise ValueError("Earlier reading context changed during generation")
            storage_key = await asyncio.to_thread(store.reading_key, path, note)
            target = store.root(path) / "notes" / note["id"] / f"{storage_key}.json"
            if await asyncio.to_thread(target.exists):
                previous = await asyncio.to_thread(load_json, target)
                await run_noninterruptible_sync(
                    store.write, store.root(path) / "history" / f"note-{uuid4().hex}.json", previous
                )
            await asyncio.to_thread(scope.require, path, notebook, [note["id"]])
            await run_noninterruptible_sync(store.write, target, result)
            from lib.novel_workflow.assets import synchronize

            await run_noninterruptible_sync(synchronize, path)
        from lib.novel_workflow.assets import synchronize

        await run_noninterruptible_sync(synchronize, path)
        book = await asyncio.to_thread(memory.ledger, path, notebook)
        await run_noninterruptible_sync(store.write, store.root(path) / "ledger.json", book)
        if (await asyncio.to_thread(settings.get, path))["understanding_enabled"]:
            from lib.novel_workflow.understanding import understand_notes

            progress.update(phase="understanding", done=0)
            await understand_notes(path, generator, note_ids, expected)
        progress.update(phase="complete", done=len(notes), completed_at=now())
        return {"read_notes": len(notes)}
    except Exception as exc:
        progress.update(phase="stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", error=str(exc))
        raise
    finally:
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)


def validate_svt(
    batch: SVTBatch,
    event_ids: set[str],
    new_ids: set[str],
    dialogue_ids: set[str],
    existing: set[str],
    dialogue_events: dict[str, str] | None = None,
    event_owners: dict[str, set[str]] | None = None,
):
    assigned = set(batch.supporting_event_ids)
    continued = set()
    if not assigned <= new_ids:
        raise ValueError("Unknown supporting event ID")
    for svt in batch.svts:
        ids = set(svt.event_ids)
        if svt.existing_id:
            if svt.existing_id in continued:
                raise ValueError("An existing SVT must be updated once per batch")
            continued.add(svt.existing_id)
        if event_owners and any(event_owners.get(i) and svt.existing_id not in event_owners[i] for i in ids):
            raise ValueError("Already classified events must reuse their existing SVT identity")
        if not ids <= event_ids or not ids:
            raise ValueError("SVT references an event outside supplied evidence")
        if svt.existing_id and svt.existing_id not in existing:
            raise ValueError("Unknown existing SVT")
        if not set(svt.dialogue_ids) <= dialogue_ids:
            raise ValueError("Unknown dialogue ID")
        if dialogue_events is not None and any(dialogue_events.get(i) not in ids for i in svt.dialogue_ids):
            raise ValueError("Dialogue must belong to an event in this SVT")
        for moment in svt.climaxes + svt.payoffs:
            if not set(moment.event_ids) <= ids:
                raise ValueError("Climax/payoff must cite events in its SVT")
        assigned |= ids
    if not new_ids <= assigned:
        raise ValueError("Some current events were not classified; preserve them as supporting events if appropriate")
    return batch.model_dump()


async def generate_svts(path: Path, generator, note_ids: list[str], expected: str) -> dict:
    from lib.novel_workflow.understanding import require_understood

    await asyncio.to_thread(require_understood, path, note_ids)
    notebook = await asyncio.to_thread(current, path, expected)
    wanted = set(note_ids)
    notes = [n for n in notebook["notes"] if n["id"] in wanted]
    if not notes or len(notes) != len(wanted):
        raise ValueError("Select existing Notes")
    events = []
    bases = {}
    for note in notes:
        result = await asyncio.to_thread(store.note_result, path, note)
        if not result:
            raise ValueError("Read all selected Notes before generating SVTs")
        bases[note["id"]] = result["basis"]
        events.extend({**e, "note_id": note["id"], "note_title": note["title"]} for e in result["events"])
    # Every event is retained; deduplicate only repeated extraction of the same exact source evidence.
    events = list({e["id"]: e for e in events}.values())
    rules = await asyncio.to_thread(store.rule, path, "svt")
    target = store.root(path) / "svts.json"
    previous = await asyncio.to_thread(load_json, target) if await asyncio.to_thread(target.exists) else {}
    # Include only past/current valid Notes. Future SVT summaries must never enter an earlier scope.
    cutoff = max(n["order"] for n in notes)
    context_events = list(events)
    context_bases = dict(bases)
    for note in notebook["notes"]:
        if note["order"] > cutoff or note["id"] in wanted:
            continue
        reading = await asyncio.to_thread(store.note_result, path, note)
        if reading:
            context_bases[note["id"]] = reading["basis"]
            context_events.extend({**e, "note_id": note["id"], "note_title": note["title"]} for e in reading["events"])
    valid_ids = {e["id"] for e in context_events}
    prior_svts = [
        s
        for s in previous.get("svts", [])
        if not s.get("stale")
        and previous.get("rule_basis") == digest(rules)
        and set(s["event_ids"]) <= valid_ids
        and all(
            previous.get("note_bases", {}).get(i) == context_bases.get(i) and i in context_bases for i in s["note_ids"]
        )
    ]
    run_key = digest([bases, rules, prior_svts])
    run_file = store.root(path) / "svt_runs" / f"{run_key}.json"
    run = (
        await asyncio.to_thread(load_json, run_file)
        if await asyncio.to_thread(run_file.exists)
        else {
            "cursor": 0,
            "svts": prior_svts,
            "suggestions": [],
            "supporting_event_ids": [],
            "note_bases": context_bases,
            "rule_basis": digest(rules),
        }
    )
    by_event = {e["id"]: e for e in context_events}
    dialogues = {d["id"]: d for e in context_events for d in e["dialogues"]}
    progress = {"phase": "svt", "total": len(events), "done": run["cursor"], "started_at": now()}
    try:
        while run["cursor"] < len(events):
            check_stop()
            await asyncio.to_thread(current, path, expected)
            batch = events[run["cursor"] : run["cursor"] + 8]
            characters = {c for e in batch for c in e["characters"]}
            candidates = sorted(
                run["svts"],
                key=lambda s: (
                    bool(set(s["event_ids"]) & {e["id"] for e in batch}),
                    s["status"] == "open",
                    sum(c in s["summary"] for c in characters),
                ),
                reverse=True,
            )[:12]
            # Bounded retrieved context. Full SVTs remain on disk, never discarded for prompt size.
            supplied = []
            for candidate in candidates:
                # Full evidence/quotes grow indefinitely; send an index, keep full history on disk.
                batch_ids = {e["id"] for e in batch}
                refs = list(
                    dict.fromkeys([i for i in candidate["event_ids"] if i in batch_ids] + candidate["event_ids"][-16:])
                )
                compact = {
                    "id": candidate["id"],
                    "title": candidate["title"],
                    "summary": candidate["summary"][:3000],
                    "status": candidate["status"],
                    "event_ids": refs,
                    "history_event_count": len(candidate["event_ids"]),
                    "dialogues": candidate["dialogues"][-3:],
                }
                if len(json.dumps([*supplied, compact], ensure_ascii=False)) <= 14000:
                    supplied.append(compact)
            old_ids = {i for s in supplied for i in s["event_ids"]}
            available = {e["id"] for e in batch} | old_ids
            allowed_dialogues = {d["id"] for i in available for d in by_event[i]["dialogues"]}
            prompt = (
                rules
                + "\n本批事件："
                + json.dumps(batch, ensure_ascii=False)
                + "\n可续接SVT："
                + json.dumps(supplied, ensure_ascii=False)
            )
            result = await ask(
                path,
                generator,
                SVTBatch,
                prompt,
                partial(
                    validate_svt,
                    event_ids=available,
                    new_ids={e["id"] for e in batch},
                    dialogue_ids=allowed_dialogues,
                    existing={s["id"] for s in supplied},
                    dialogue_events={d["id"]: e["id"] for e in context_events for d in e["dialogues"]},
                    event_owners={i: {s["id"] for s in supplied if i in s["event_ids"]} for i in old_ids},
                ),
            )
            await asyncio.to_thread(current, path, expected)
            for proposed in result["svts"]:
                old = next((s for s in run["svts"] if s["id"] == proposed["existing_id"]), None)
                if old:
                    ids = list(dict.fromkeys(old["event_ids"] + proposed["event_ids"]))
                    proposed["event_ids"] = ids
                    proposed["climaxes"] = list({digest(v): v for v in old["climaxes"] + proposed["climaxes"]}.values())
                    proposed["payoffs"] = list({digest(v): v for v in old["payoffs"] + proposed["payoffs"]}.values())
                    proposed["dialogue_ids"] = list(dict.fromkeys(old["dialogue_ids"] + proposed["dialogue_ids"]))
                proposed["id"] = proposed.pop("existing_id") or uuid4().hex
                proposed["note_ids"] = list(dict.fromkeys(by_event[i]["note_id"] for i in proposed["event_ids"]))
                proposed["dialogues"] = [dialogues[i] for i in proposed["dialogue_ids"]]
                proposed["evidence"] = [by_event[i]["evidence"] for i in proposed["event_ids"]]
                run["svts"] = [s for s in run["svts"] if s["id"] != proposed["id"]] + [proposed]
            run["supporting_event_ids"].extend(result["supporting_event_ids"])
            run["suggestions"].extend(result["merge_suggestions"])
            run["cursor"] += len(batch)
            await run_noninterruptible_sync(store.write, run_file, run)
            progress["done"] = run["cursor"]
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
        await asyncio.to_thread(current, path, expected)
        if await asyncio.to_thread(store.rule, path, "svt") != rules:
            raise ValueError("SVT rules changed; rerun with current rules")
        for note in notebook["notes"]:
            if note["id"] not in context_bases:
                continue
            live = await asyncio.to_thread(store.note_result, path, note)
            if not live or live["basis"] != context_bases[note["id"]]:
                raise ValueError("Note reading rules or evidence changed during SVT generation")
        target = store.root(path) / "svts.json"
        old = await asyncio.to_thread(load_json, target) if await asyncio.to_thread(target.exists) else {}
        retained = []
        for svt in old.get("svts", []):
            involved = set(svt["note_ids"])
            if svt["id"] not in {v["id"] for v in run["svts"]} and not involved <= wanted:
                retained.append({**svt, "stale": bool(involved & wanted)})
        combined = {
            **run,
            "svts": retained + run["svts"],
            "note_bases": {**old.get("note_bases", {}), **context_bases},
            "completed_at": now(),
        }
        if old:
            await run_noninterruptible_sync(store.write, store.root(path) / "history" / f"svt-{uuid4().hex}.json", old)
        await run_noninterruptible_sync(store.write, target, combined)
        progress.update(phase="complete", done=len(events))
        return {"svts": len(run["svts"])}
    except Exception as exc:
        progress.update(phase="stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", error=str(exc))
        raise
    finally:
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
