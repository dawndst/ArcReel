"""Bounded, resumable reading and SVT aggregation. No model-controlled Note merging."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from inspect import isawaitable
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from lib.backends.text_backends.base import TextGenerationRequest, TextOutputTruncatedError
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.text_utils import strip_json_code_fences
from lib.novel_understanding.service import NovelReadingInterrupted, check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import chapters, memory, settings, store, synthesis, understanding
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import Reading, SVTBatch
from lib.novel_workflow.storage import load_json


def current(path: Path, expected: str) -> dict:
    project = load_json(path / "project.json")
    return store.require_current(path, project, expected)


def evidence(text: str, quote: str, part: dict) -> dict:
    pos, end = locate(text, quote)
    return {
        "source_file": part["source_file"],
        "start": part["start"] + pos,
        "end": part["start"] + end,
        "quote": text[pos:end],
        "note_id": part["note_id"],
    }


def claim_evidence(part, dialogue):
    context = dialogue.get("context_quote", "")
    if context:
        start, end = locate(part["text"], context)
        return evidence(part["text"][start:end], dialogue["quote"], {**part, "start": part["start"] + start})
    try:
        return evidence(part["text"], dialogue["quote"], part)
    except ValueError as exc:
        raise ValueError(
            "引句可能重复或不精确；逐项检查所有记录和对白的重复quote，并填写context_quote：包含本次引用及前后叙述、能唯一定位的连续原文。quote仍保留原句。当前引句："
            + dialogue["quote"][:100]
        ) from exc


def ground(reading: Reading, part: dict, seed_ids=frozenset(), identity_ids=frozenset()) -> dict:
    data = reading.model_dump()
    data["questions"] = list(dict.fromkeys([*data["questions"], *(q["text"] for q in data["reading_questions"])]))
    for mention in data["assets"]:
        if mention.get("same_entity_as") and mention["same_entity_as"] not in identity_ids:
            raise ValueError("Asset identity anchor must refer to a supplied earlier asset record")
    for thread in data["threads"]:
        if thread["kind"] == "seed" and thread["seed_id"] is not None:
            raise ValueError("A new seed cannot resolve another seed")
        if thread["kind"] == "resolution" and thread["seed_id"] is not None and thread["seed_id"] not in seed_ids:
            raise ValueError("Resolution references a seed outside the supplied past evidence")
    for bucket in memory.BUCKETS:
        for item in data[bucket]:
            item["evidence"] = claim_evidence(part, item)
            item["quote"] = item["evidence"]["quote"]
            item["id"] = digest([bucket, item])[:24]
            if bucket == "events":
                for dialogue in item["dialogues"]:
                    dialogue["evidence"] = claim_evidence(part, dialogue)
                    dialogue["quote"] = dialogue["evidence"]["quote"]
                    dialogue["id"] = digest(["dialogue", dialogue["evidence"]])[:24]
    return data


def output_schema(schema):
    value = schema.model_json_schema()
    for definition in [value, *value.get("$defs", {}).values()]:
        properties = definition.get("properties", {})
        if "claim_type" in properties:
            definition["required"] = list(
                dict.fromkeys([*definition.get("required", []), "claim_type", "perspective", "source_kind"])
            )
    return value


async def ask(
    path: Path,
    generator,
    schema,
    prompt: str | dict,
    validate=lambda value: value,
    *,
    grow_output=False,
    max_output_tokens=12000,
    include_fidelity=True,
):
    fidelity = await asyncio.to_thread(store.effective_rule, path, "fidelity") if include_fidelity else ""
    if isinstance(prompt, dict):
        prompt = {
            **prompt,
            "instructions": prompt.get("instructions", "")
            + ("" if fidelity in prompt.get("instructions", "") else "\n" + fidelity),
        }
    else:
        prompt = prompt if fidelity in prompt else fidelity + "\n" + prompt
    if isinstance(prompt, dict):
        prompt = (
            "请按 instructions 规则处理 source；memory 仅为上下文，不作为证据。只输出符合 schema 的 JSON。\n"
            + json.dumps({**prompt, "schema": output_schema(schema)}, ensure_ascii=False)
        )
    else:
        prompt += "\n只输出 JSON 数据实例（不是 schema 本身），结构：" + json.dumps(
            output_schema(schema), ensure_ascii=False
        )
    error = ""
    output_limit = max_output_tokens
    validation_failures = 0
    while validation_failures < 3:
        check_stop()
        try:
            response = await generator.generate(
                TextGenerationRequest(prompt=prompt + error, max_output_tokens=output_limit),
                project_name=path.name,
                require_complete=True,
            )
        except TextOutputTruncatedError:
            larger = min(output_limit * 2, generator.max_output_tokens, 48000) if grow_output else output_limit
            if larger <= output_limit:
                raise
            output_limit = larger
            continue
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "responses" / f"{uuid4().hex}.json",
            {"text": response.text, "created_at": now()},
        )
        try:
            result = validate(
                schema.model_validate_json(strip_json_code_fences(response.text), context={"model_output": True})
            )
            return await result if isawaitable(result) else result
        except (ValidationError, ValueError) as exc:
            validation_failures += 1
            error = "\n修正上次输出中的问题，不删掉原始事实：" + str(exc)[:2200]
    raise ValueError("模型输出未通过原文或结构校验，已保留响应及完成片段，可修正后重试。" + error)


def reading_rules(path):
    return (
        store.effective_rule(path, "read") + "\n抽取审核规则版本：" + digest(store.effective_rule(path, "read_review"))
    )


async def read_part(
    path, generator, note, part, rules, rolling, expected, seed_ids=frozenset(), identity_ids=frozenset()
):
    key = digest([note["basis"], rules, part["source_file"], part["start"], part["end"], rolling])
    target = store.root(path) / "parts" / f"{key}.json"
    if await asyncio.to_thread(target.exists):
        return [await asyncio.to_thread(load_json, target)]
    marker = target.with_suffix(".split.json")
    split = await asyncio.to_thread(marker.exists)
    if not split:
        prompt = {
            "instructions": rules,
            "memory": rolling,
            "source": part["text"],
            "surrounding_context": {"before": part.get("before_context", ""), "after": part.get("after_context", "")},
        }
        try:
            draft_file = store.root(path) / "reading_drafts" / f"{key}.json"
            candidate_file = store.root(path) / "reading_candidates" / f"{key}.json"

            async def validate_reading(value):
                if not value.complete:
                    return None
                from lib.novel_workflow.quote_locations import resolve

                await run_noninterruptible_sync(store.write, candidate_file, value.model_dump())
                value = await resolve(path, generator, value, part)
                return ground(value, part, seed_ids, identity_ids)

            if await asyncio.to_thread(draft_file.exists):
                data = await asyncio.to_thread(load_json, draft_file)
            else:
                if await asyncio.to_thread(candidate_file.exists):
                    candidate = Reading.model_validate(
                        await asyncio.to_thread(load_json, candidate_file), context={"model_output": True}
                    )
                    try:
                        data = await validate_reading(candidate)
                    except ValueError as exc:
                        data = await ask(
                            path,
                            generator,
                            Reading,
                            {**prompt, "repair": str(exc), "draft": candidate.model_dump()},
                            validate_reading,
                            grow_output=True,
                            max_output_tokens=min(
                                getattr(generator, "max_output_tokens", 24000), max(12000, len(part["text"]) * 4)
                            ),
                        )
                else:
                    data = await ask(
                        path,
                        generator,
                        Reading,
                        prompt,
                        validate_reading,
                        grow_output=True,
                        max_output_tokens=min(
                            getattr(generator, "max_output_tokens", 24000), max(12000, len(part["text"]) * 4)
                        ),
                    )
                if data is not None:
                    await run_noninterruptible_sync(store.write, draft_file, data)
            await asyncio.to_thread(current, path, expected)
            if data is not None:
                from lib.novel_workflow.reading_audit import audit

                data = await audit(path, generator, data, part, seed_ids, identity_ids)
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
        child = {
            **part,
            "start": part["start"] + start,
            "end": part["start"] + end,
            "text": part["text"][start:end],
            "before_context": (part.get("before_context", "") + part["text"][:start])[-600:],
            "after_context": (part["text"][end:] + part.get("after_context", ""))[:400],
        }
        child_context = rolling + "\n" + "\n".join(v["summary"] for v in results[-2:])[-2500:]
        extra_records = []
        for previous in results:
            for record in previous["threads"] + previous["aliases"] + previous["assets"]:
                if len(json.dumps([*extra_records, record], ensure_ascii=False)) <= 5000:
                    extra_records.append(record)
        child_context += "\n已读子块台账：" + json.dumps(extra_records, ensure_ascii=False)
        child_seeds = seed_ids | {v["id"] for v in extra_records if v.get("kind") == "seed"}
        child_identities = identity_ids | {
            v["id"] for v in extra_records if v.get("kind") in {"character", "scene", "prop"}
        }
        results.extend(
            await read_part(path, generator, note, child, rules, child_context, expected, child_seeds, child_identities)
        )
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
    rules = await asyncio.to_thread(reading_rules, path)
    from lib.novel_workflow import settings

    chapter_rule = await asyncio.to_thread(settings.chapter_rule, path)
    progress = {"phase": "reading", "total": len(notes), "done": 0, "note_id": None, "started_at": now()}
    try:
        for index, note in enumerate(notes):
            check_stop()
            await asyncio.to_thread(current, path, expected)
            await asyncio.to_thread(scope.require, path, notebook, [note["id"]])
            progress.update(phase="reading", done=index, note_id=note["id"], part=0, parts=0)
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
            existing_reading = await asyncio.to_thread(store.note_result, path, note)
            if existing_reading:
                from lib.novel_workflow.condensation import ensure

                project = await asyncio.to_thread(load_json, path / "project.json")
                await ensure(path, generator, note, existing_reading, project, expected)
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
                identity_ids = {v["id"] for v in supplied["records"] if v.get("kind") in {"character", "scene", "prop"}}
                extracted.extend(
                    await read_part(path, generator, note, part, rules, rolling, expected, seed_ids, identity_ids)
                )
            await asyncio.to_thread(current, path, expected)
            progress.update(phase="summarizing", part=0, parts=0)
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
            overview = await synthesis.chapter(path, generator, extracted, chapter_rule)
            await asyncio.to_thread(current, path, expected)
            live_rule = await asyncio.to_thread(reading_rules, path)
            if live_rule != rules or await asyncio.to_thread(settings.chapter_rule, path) != chapter_rule:
                raise ValueError("Reading rules changed during generation; completed fragment cache is preserved")
            result = {
                "basis": digest([note["basis"], rules, chapter_rule, context_basis, overview, extracted, 2]),
                "context_basis": context_basis,
                "overview": overview,
                "reading_questions": [q for v in extracted for q in v.get("reading_questions", [])],
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
            from lib.novel_workflow.condensation import ensure

            await run_noninterruptible_sync(synchronize, path)
            await ensure(path, generator, note, result, project, expected)
        from lib.novel_workflow.assets import synchronize

        await run_noninterruptible_sync(synchronize, path)
        book = await asyncio.to_thread(memory.ledger, path, notebook)
        await run_noninterruptible_sync(store.write, store.root(path) / "ledger.json", book)
        if (await asyncio.to_thread(settings.get, path))["understanding_enabled"]:
            from lib.novel_workflow.understanding import understand_notes

            progress.update(phase="understanding", done=0)
            try:
                await understand_notes(path, generator, note_ids, expected)
            except Exception:
                latest_progress = await asyncio.to_thread(load_json, store.root(path) / "progress.json")
                if latest_progress.get("phase") in {"understanding", "failed", "stopped"}:
                    progress = latest_progress
                raise
        else:
            from lib.novel_workflow.conclusions import prepare

            await prepare(path, generator, note_ids, expected)
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
    event_notes: dict[str, str] | None = None,
    note_owners: dict[str, str] | None = None,
):
    assigned = set()
    primary = dict(note_owners or {})
    primary_titles = {}
    continued = set()
    if not set(batch.supporting_event_ids) <= new_ids:
        raise ValueError("Unknown supporting event ID")
    for index, svt in enumerate(batch.svts):
        ids = set(svt.event_ids)
        identity = svt.existing_id or f"new-{index}"
        if event_notes:
            for event_id in ids:
                note_id = event_notes.get(event_id)
                if note_id and note_id in primary and primary[note_id] != identity:
                    raise ValueError("每个 Note 只能有一个主归属 SVT；其他方向请放 alternatives")
                if note_id:
                    primary[note_id] = identity
                    primary_titles[note_id] = svt.title.strip().casefold()
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
        for kind in (svt.climaxes, svt.payoffs):
            keys = [digest([sorted(m.event_ids), sorted(m.dialogue_ids)]) for m in kind]
            if len(set(keys)) != len(keys):
                raise ValueError("同一组场面和台词依据不能重复计作多个爆点")
        for moment in svt.climaxes + svt.payoffs:
            if len(set(moment.note_ids)) != len(moment.note_ids) or len(set(moment.dialogue_ids)) != len(
                moment.dialogue_ids
            ):
                raise ValueError("爆点来源 Note 和台词不能重复")
            if not set(moment.event_ids) <= ids:
                raise ValueError("Climax/payoff must cite events in its SVT")
            if not set(moment.dialogue_ids) <= dialogue_ids:
                raise ValueError("爆点台词必须引用已提供的原文对白")
            if dialogue_events and any(dialogue_events.get(i) not in moment.event_ids for i in moment.dialogue_ids):
                raise ValueError("爆点场面与台词必须属于同一组来源事件")
            if event_notes and set(moment.note_ids) != {event_notes[i] for i in moment.event_ids}:
                raise ValueError("爆点必须准确标注其来源 Note")
        assigned |= ids
    if not new_ids <= assigned:
        raise ValueError(
            "Some current events were not classified: "
            + ", ".join(sorted(new_ids - assigned))
            + "。以上ID必须全部加入当前Note唯一主归属SVT的event_ids；supporting_event_ids不能代替正式归属。"
            "梦境、未判定和过渡事件也保留来源性质归入同一Note，归属不表示它们属于同一现实因果链。"
        )
    candidate_notes = set()
    for alternatives in batch.alternatives:
        if alternatives.note_id in candidate_notes or (
            event_notes and alternatives.note_id not in {event_notes[i] for i in new_ids}
        ):
            raise ValueError("备选必须属于当前 Note，不能重复列出")
        candidate_notes.add(alternatives.note_id)
        seen = set()
        for candidate in alternatives.candidates:
            key = candidate.existing_id or candidate.title.strip().casefold()
            if not candidate.existing_id and key == primary_titles.get(alternatives.note_id):
                raise ValueError("不能把主归属本身重复列为备选")
            if key in seen or (
                candidate.existing_id
                and (
                    candidate.existing_id not in existing or candidate.existing_id == primary.get(alternatives.note_id)
                )
            ):
                raise ValueError("SVT 备选不能重复、越界或与主归属相同")
            seen.add(key)
    return batch.model_dump()


def note_events(note, result):
    values = [{**e, "note_id": note["id"], "note_title": note["title"]} for e in result["events"]]
    if values:
        return values
    records = memory.records(result)
    if not records:
        raise ValueError("Note 缺少可追溯资料，请重新精读后分配 SVT")
    anchor = records[0]["evidence"]
    return [
        {
            "id": digest([note["id"], "context-event", anchor]),
            "note_id": note["id"],
            "note_title": note["title"],
            "title": note["title"] + " · 背景与铺垫",
            "cause": "未明确",
            "conflict": "未明确",
            "action": anchor["quote"],
            "outcome": "当前章节提供背景或铺垫",
            "characters": [],
            "dialogues": [],
            "open_thread": "",
            "evidence": anchor,
        }
    ]


async def generate_svts(path: Path, generator, note_ids: list[str], expected: str) -> dict:
    from lib.novel_workflow.understanding import require_understood

    await asyncio.to_thread(require_understood, path, note_ids)
    from lib.novel_workflow.conclusions import effective_reading, prepare, require_ready

    await prepare(path, generator, note_ids, expected)
    await asyncio.to_thread(require_ready, path, note_ids)
    notebook = await asyncio.to_thread(current, path, expected)
    wanted = set(note_ids)
    notes = [n for n in notebook["notes"] if n["id"] in wanted]
    if not notes or len(notes) != len(wanted):
        raise ValueError("Select existing Notes")
    events = []
    bases = {}
    edition_bases = {}
    editions = {}
    for note in notes:
        result = await asyncio.to_thread(store.note_result, path, note)
        if not result:
            raise ValueError("Read all selected Notes before generating SVTs")
        bases[note["id"]] = result["basis"]
        from lib.novel_workflow.condensation import ensure

        project = await asyncio.to_thread(load_json, path / "project.json")
        edition = await ensure(path, generator, note, result, project, expected)
        edition_bases[note["id"]] = edition["basis"]
        editions[note["id"]] = edition
        events.extend(note_events(note, result))
    # Every event is retained; deduplicate only repeated extraction of the same exact source evidence.
    events = list({e["id"]: e for e in events}.values())
    rules = await asyncio.to_thread(store.effective_rule, path, "svt")
    target = store.root(path) / "svts.json"
    previous = await asyncio.to_thread(load_json, target) if await asyncio.to_thread(target.exists) else {}
    # Include only past/current valid Notes. Future SVT summaries must never enter an earlier scope.
    cutoff = min(n["order"] for n in notes)
    context_events = list(events)
    context_bases = dict(bases)
    for note in notebook["notes"]:
        if note["order"] > cutoff or note["id"] in wanted:
            continue
        reading = await asyncio.to_thread(store.note_result, path, note)
        if reading:
            context_bases[note["id"]] = reading["basis"]
            context_events.extend(note_events(note, reading))
    valid_ids = {e["id"] for e in context_events}
    from lib.novel_workflow.conclusions import input_bases

    conclusion_bases = await asyncio.to_thread(input_bases, path, list(context_bases))
    prior_svts = [
        s
        for s in previous.get("svts", [])
        if previous.get("schema_version") == 2
        and not s.get("stale")
        and all(previous.get("conclusion_bases", {}).get(i) == conclusion_bases.get(i) for i in s["note_ids"])
        and previous.get("rule_basis") == digest(rules)
        and set(s["event_ids"]) <= valid_ids
        and all(
            previous.get("note_bases", {}).get(i) == context_bases.get(i) and i in context_bases for i in s["note_ids"]
        )
    ]
    summary_rules = await asyncio.to_thread(store.effective_rule, path, "svt_summary")
    run_key = digest(
        [
            bases,
            rules,
            prior_svts,
            edition_bases,
            await asyncio.to_thread(understanding.view, path),
            summary_rules,
            conclusion_bases,
            4,
        ]
    )
    run_file = store.root(path) / "svt_runs" / f"{run_key}.json"
    run = (
        await asyncio.to_thread(load_json, run_file)
        if await asyncio.to_thread(run_file.exists)
        else {
            "schema_version": 2,
            "cursor": 0,
            "note_candidates": {},
            "svts": prior_svts,
            "suggestions": [],
            "supporting_event_ids": [],
            "note_bases": context_bases,
            "rule_basis": digest(rules),
        }
    )
    directions = {}
    for note in notes:
        reading = await asyncio.to_thread(store.note_result, path, note)
        note_events_index = [{"id": e["id"], "title": e["title"]} for e in events if e["note_id"] == note["id"]]
        # Summaries cover all records; compact title indices are packed rather than truncated.
        index_batches = list(synthesis.packs(note_events_index, 9000))
        if len(index_batches) > 1:
            direction = await synthesis.chapter(
                path, generator, [reading], await asyncio.to_thread(settings.chapter_rule, path)
            )
            index_value = {"summary": direction, "event_count": len(note_events_index)}
        else:
            index_value = {"events": note_events_index}
        end = max(section["end"] for section in note["sections"])
        related = await asyncio.to_thread(understanding.production_context, path, [note["id"]], source_offset=end)
        reviewed = await asyncio.to_thread(effective_reading, path, note, reading)
        directions[note["id"]] = {
            "note_id": note["id"],
            "overview": reviewed.get("overview"),
            "conclusions": [
                {k: c.get(k) for k in ("question", "status", "answer", "production_constraint")}
                for c in reviewed.get("conclusion_review", {}).get("conclusions", [])
            ],
            "index": index_value,
            "verified_links": related["links"],
        }
    by_event = {e["id"]: e for e in context_events}
    dialogues = {d["id"]: d for e in context_events for d in e["dialogues"]}
    progress = {"phase": "svt", "total": len(events), "done": run["cursor"], "started_at": now()}
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
    try:
        while run["cursor"] < len(events):
            check_stop()
            await asyncio.to_thread(current, path, expected)
            # A Note is one primary assignment, even when its events require several bounded requests.
            current_note = events[run["cursor"]]["note_id"]
            batch = [e for e in events[run["cursor"] : run["cursor"] + 8] if e["note_id"] == current_note]
            note_owners = {i: svt["id"] for svt in run["svts"] for i in svt["note_ids"]}
            characters = {c for e in batch for c in e["characters"]}
            candidates = sorted(
                run["svts"],
                key=lambda s: (
                    current_note in s["note_ids"],
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
                    "note_ids": candidate["note_ids"],
                    "summary": candidate["summary"][:3000],
                    "status": candidate["status"],
                    "event_ids": refs,
                    "history_event_count": len(candidate["event_ids"]),
                    "dialogues": [
                        {"id": d["id"], "speaker": d["speaker"], "quote": d["quote"][:1000]}
                        for d in candidate["dialogues"][-3:]
                    ],
                }
                if len(json.dumps([*supplied, compact], ensure_ascii=False)) <= 14000:
                    supplied.append(compact)
            old_ids = {i for s in supplied for i in s["event_ids"]}
            available = {e["id"] for e in batch} | old_ids
            allowed_dialogues = {d["id"] for i in available for d in by_event[i]["dialogues"]}
            from lib.novel_workflow.svt_material import generate as generate_from_edition

            result, material_stats = await generate_from_edition(
                path,
                generator,
                rules,
                directions[current_note],
                batch,
                editions[current_note],
                supplied,
                partial(
                    validate_svt,
                    event_ids=available,
                    new_ids={e["id"] for e in batch},
                    dialogue_ids=allowed_dialogues,
                    existing={s["id"] for s in supplied},
                    dialogue_events={d["id"]: e["id"] for e in context_events for d in e["dialogues"]},
                    event_owners={i: {s["id"] for s in supplied if i in s["event_ids"]} for i in old_ids},
                    event_notes={e["id"]: e["note_id"] for e in context_events},
                    note_owners=note_owners,
                ),
            )
            await asyncio.to_thread(current, path, expected)
            run.setdefault("material_stats", []).append(material_stats)
            for alternative in result["alternatives"]:
                run["note_candidates"][alternative["note_id"]] = [
                    {**c, "candidate_id": digest([alternative["note_id"], c]), "basis": bases[alternative["note_id"]]}
                    for c in alternative["candidates"]
                ]
            for proposed in result["svts"]:
                for moment in proposed["climaxes"] + proposed["payoffs"]:
                    moment["dialogues"] = [dialogues[i] for i in moment["dialogue_ids"]]
                    moment["evidence"] = [by_event[i]["evidence"] for i in moment["event_ids"]]
                old = next((s for s in run["svts"] if s["id"] == proposed["existing_id"]), None)
                if old:
                    ids = list(dict.fromkeys(old["event_ids"] + proposed["event_ids"]))
                    proposed["event_ids"] = ids
                    for kind in ("climaxes", "payoffs"):
                        proposed[kind] = list(
                            {
                                digest([sorted(v["event_ids"]), sorted(v["dialogue_ids"])]): v
                                for v in old[kind] + proposed[kind]
                            }.values()
                        )
                    proposed["dialogue_ids"] = list(dict.fromkeys(old["dialogue_ids"] + proposed["dialogue_ids"]))
                proposed["id"] = proposed.pop("existing_id") or uuid4().hex
                proposed["note_ids"] = list(dict.fromkeys(by_event[i]["note_id"] for i in proposed["event_ids"]))
                proposed["dialogue_ids"] = list(
                    dict.fromkeys(
                        proposed["dialogue_ids"]
                        + [i for m in proposed["climaxes"] + proposed["payoffs"] for i in m["dialogue_ids"]]
                    )
                )
                proposed["dialogues"] = [dialogues[i] for i in proposed["dialogue_ids"]]
                proposed["breakdown_status"] = "complete" if len(proposed["climaxes"]) >= 2 else "needs_details"
                proposed["evidence"] = [by_event[i]["evidence"] for i in proposed["event_ids"]]
                run["svts"] = [s for s in run["svts"] if s["id"] != proposed["id"]] + [proposed]
            run["supporting_event_ids"].extend(result["supporting_event_ids"])
            run["suggestions"].extend(result["merge_suggestions"])
            run["cursor"] += len(batch)
            await run_noninterruptible_sync(store.write, run_file, run)
            progress["done"] = run["cursor"]
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
        from lib.novel_workflow.svt_summary import finalize

        run["svts"] = await finalize(path, generator, run["svts"], notebook)
        await asyncio.to_thread(current, path, expected)
        if await asyncio.to_thread(store.effective_rule, path, "svt_summary") != summary_rules:
            raise ValueError("SVT 累计概况规则已变化，请重新生成")
        if await asyncio.to_thread(store.effective_rule, path, "svt") != rules:
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
                retained.append(
                    {
                        **svt,
                        "stale": bool(involved & wanted)
                        or old.get("rule_basis") != digest(rules)
                        or old.get("schema_version") != 2,
                    }
                )
        combined = {
            **run,
            "svts": retained + run["svts"],
            "note_candidates": {**old.get("note_candidates", {}), **run["note_candidates"]},
            "note_bases": {**old.get("note_bases", {}), **context_bases},
            "completed_at": now(),
            "conclusion_bases": conclusion_bases,
        }
        if await asyncio.to_thread(input_bases, path, list(context_bases)) != conclusion_bases:
            raise ValueError("结论整理版本已变化，请从已保存进度继续生成SVT。")
        from lib.novel_workflow.svt_contract import assignments

        combined["note_assignments"] = assignments(combined["svts"])
        if not wanted <= set(combined["note_assignments"]):
            raise ValueError("每个 Note 都必须有一个主归属 SVT，当前结果不完整")

        def commit():
            from lib.artifacts.formal_write import project_metadata_lock

            with project_metadata_lock(path):
                current(path, expected)
                live_svt = load_json(target) if target.exists() else {}
                if digest(live_svt) != digest(previous):
                    raise ValueError("SVT 主归属在生成期间已变化，请刷新后重新运行")
                if store.effective_rule(path, "svt") != rules:
                    raise ValueError("SVT 规则已变化，请使用当前规则重新拆分")
                if store.effective_rule(path, "svt_summary") != summary_rules:
                    raise ValueError("SVT 累计概况规则已变化，请重新生成")
                if live_svt:
                    store.write(store.root(path) / "history" / f"svt-{uuid4().hex}.json", live_svt)
                store.write(target, combined)

        await run_noninterruptible_sync(commit)
        progress.update(phase="complete", done=len(events))
        return {"svts": len(run["svts"])}
    except Exception as exc:
        progress.update(phase="stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", error=str(exc))
        raise
    finally:
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
