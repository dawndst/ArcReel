"""Cross-Note inquiry and evidence rereading, separate from reader-visible chronology."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import memory, retrieval, settings, store, synthesis
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.understanding_models import Findings, Inquiry

INQUIRY_INDEX_BUDGET = 14000


def inquiry_record(value):
    """Keep semantic fields, including nested dialogue; source locations stay in the corpus."""
    if isinstance(value, list):
        return [inquiry_record(item) for item in value]
    if isinstance(value, dict):
        return {
            key: inquiry_record(item)
            for key, item in value.items()
            if key not in {"evidence", "context_quote"} and item not in (None, "", [], {})
        }
    return value


def ground(value, supplied, anchor_note_ids, notebook):
    by_id = {f["id"]: f for f in supplied}
    notes = {n["id"]: n for n in notebook["notes"]}
    links = []
    unresolved = list(value.unresolved)
    for draft in value.links:
        evidence = []
        for citation in draft.citations:
            fragment = by_id.get(citation.fragment_id)
            if not fragment:
                raise ValueError("Citation is outside the source fragments actually reread")
            try:
                pos, end = locate(fragment["text"], citation.quote)
            except ValueError as exc:
                matches = {}
                for candidate in supplied:
                    try:
                        start, stop = locate(candidate["text"], citation.quote)
                    except ValueError:
                        continue
                    span = (candidate["source_file"], candidate["start"] + start, candidate["start"] + stop)
                    matches[span] = (candidate, start, stop)
                if len(matches) != 1:
                    raise ValueError(
                        f"fragment_id={citation.fragment_id} 的引文必须在原文中唯一出现：{citation.quote}。"
                        "请回到该原文片段复制一条连续短句；多处证据拆为多条 citations，禁止添加省略号。"
                    ) from exc
                fragment, pos, end = next(iter(matches.values()))
            evidence.append(
                {
                    "note_id": fragment["note_id"],
                    "source_file": fragment["source_file"],
                    "start": fragment["start"] + pos,
                    "end": fragment["start"] + end,
                    "quote": fragment["text"][pos:end],
                }
            )
        involved = {e["note_id"] for e in evidence}
        if not involved & anchor_note_ids:
            unresolved.append("关联未覆盖本次锚点 Note，尚不能确认：" + draft.subject + "；" + draft.description)
            continue
        if len(involved) < 2:
            unresolved.append("仅有本章依据，跨章关联待核对：" + draft.subject + "；" + draft.description)
            continue
        latest = max(evidence, key=lambda e: (notes[e["note_id"]]["order"], e["end"]))
        for note_id in (draft.story_start_note_id, draft.story_end_note_id):
            if note_id is not None and note_id not in involved:
                raise ValueError("Story applicability must be anchored in the cited Notes")
        if (
            draft.story_start_note_id
            and draft.story_end_note_id
            and notes[draft.story_start_note_id]["order"] > notes[draft.story_end_note_id]["order"]
        ):
            raise ValueError("Story applicability range is reversed")
        if draft.kind == "contradiction" and draft.status != "uncertain":
            raise ValueError("Contradictions remain uncertain until further evidence resolves them")
        data = draft.model_dump(exclude={"citations"})
        if draft.claim_type != "fact" or draft.source_kind != "narrative":
            data["status"] = "uncertain"
        data.update(
            id=digest([draft.kind, draft.subject, sorted((e["note_id"], e["start"], e["end"]) for e in evidence)])[:24],
            note_ids=sorted(involved, key=lambda i: notes[i]["order"]),
            evidence=evidence,
            revealed_at={
                "note_id": latest["note_id"],
                "order": notes[latest["note_id"]]["order"],
                "offset": latest["end"],
            },
        )
        links.append(data)
    return {"links": links, "unresolved": list(dict.fromkeys(unresolved)), "next_queries": value.next_queries}


def understanding_rules(path):
    return (
        store.effective_rule(path, "understand")
        + "\n关联汇总规则版本："
        + digest(store.effective_rule(path, "understand_reconcile"))
    )


def view(path: Path, notebook=None):
    notebook = notebook or store.state(path)
    if not notebook:
        return {"links": [], "reports": []}
    readings = store.valid_readings(path, notebook)
    from lib.novel_workflow import scope

    allowed = scope.available_ids(path, notebook)
    rule_basis = digest(understanding_rules(path))
    reports, links = [], {}
    for file in (store.root(path) / "understanding" / "reports").glob("*.json"):
        report = load_json(file)
        stale = (
            report["source_basis"] != notebook["source_basis"]
            or not set(report.get("selected_note_ids", [])) <= allowed
            or not set(report.get("inspected_note_ids", [])) <= allowed
            or any(not set(link["note_ids"]) <= allowed for link in report.get("links", []))
            or report.get("scope_rule_basis", digest(store.effective_rule(path, "scope")))
            != digest(store.effective_rule(path, "scope"))
            or report["rule_basis"] != rule_basis
            or any(readings.get(i, {}).get("basis") != b for i, b in report["note_bases"].items())
        )
        reports.append({**report, "stale": stale})
    reports.sort(key=lambda r: r["created_at"])
    for report in reports:
        if not report["stale"]:
            for link in report["links"]:
                links[link["id"]] = link
    return {"links": list(links.values()), "reports": list(reversed(reports))}


def production_context(path, selected_note_ids, *, source_offset=None):
    """Use only facts revealed before the supplied source position; episodes default to their start."""
    if not settings.get(path)["understanding_enabled"]:
        return {"links": [], "basis": digest([])}
    notebook = store.state(path)
    if not notebook:
        return {"links": [], "basis": digest([])}
    selected = [n for n in notebook["notes"] if n["id"] in selected_note_ids]
    if not selected:
        return {"links": [], "basis": digest([])}
    cutoff = min(n["order"] for n in selected)
    links = [
        v
        for v in view(path, notebook)["links"]
        if v["status"] == "supported"
        and v.get("claim_type") == "fact"
        and v.get("source_kind") == "narrative"
        and (v["revealed_at"]["order"], v["revealed_at"]["offset"])
        < (cutoff, source_offset if source_offset is not None and len(selected) == 1 else 0)
    ]
    relevant = []
    current_readings = store.valid_readings(path, notebook)
    names = {v["name"] for n in selected for v in current_readings.get(n["id"], {}).get("assets", [])}
    for link in links:
        if (set(link["note_ids"]) & set(selected_note_ids) or any(name in link["subject"] for name in names)) and len(
            json.dumps([*relevant, link], ensure_ascii=False)
        ) <= 10000:
            relevant.append(link)
    return {"links": relevant, "basis": digest(relevant), "before_order": cutoff}


async def understand_notes(path, generator, note_ids, expected):
    from lib.novel_understanding.service import NovelReadingInterrupted, check_stop
    from lib.novel_workflow.service import ask, current

    if not (await asyncio.to_thread(settings.get, path))["understanding_enabled"]:
        return {"disabled": True}
    notebook = await asyncio.to_thread(current, path, expected)
    wanted = set(note_ids)
    notes = [n for n in notebook["notes"] if n["id"] in wanted]
    if not notes or len(notes) != len(wanted):
        raise ValueError("Select existing Notes")
    readings = await asyncio.to_thread(store.valid_readings, path, notebook)
    if any(n["id"] not in readings for n in notes):
        raise ValueError("Read selected Notes before cross-chapter understanding")
    from lib.novel_workflow import scope

    await asyncio.to_thread(scope.require, path, notebook, note_ids)
    scope_basis = await asyncio.to_thread(scope.basis, path, notebook)
    allowed = await asyncio.to_thread(scope.available_ids, path, notebook)
    bases = {n["id"]: readings[n["id"]]["basis"] for n in notes}
    rules = await asyncio.to_thread(understanding_rules, path)
    scope_rule = await asyncio.to_thread(store.effective_rule, path, "scope")
    scope_hint = "\n" + scope_rule.strip()
    legacy_key = digest([expected, bases, rules, scope_basis, scope_hint, 2])
    key = digest([expected, bases, rules, scope_basis, scope_hint, "compact-source-index-v1"])
    target = store.root(path) / "understanding" / "reports" / f"{key}.json"
    if await asyncio.to_thread(target.exists):
        return {"report_id": key, "cached": True}
    project = await asyncio.to_thread(load_json, path / "project.json")
    corpus = await run_noninterruptible_sync(retrieval.index, path, project, notebook)
    units = []
    original_records = {}
    legacy_count = 0
    for note in notes:
        reading = readings[note["id"]]
        records = memory.records(reading)
        original_records[note["id"]] = {record["id"]: record for record in records}
        legacy_count += len(list(synthesis.packs(records, 7000)))
        units.extend(
            {"note_id": note["id"], "title": note["title"], "questions": reading["questions"], "records": batch}
            for batch in synthesis.packs([inquiry_record(record) for record in records], INQUIRY_INDEX_BUDGET)
        )
    checkpoint = store.root(path) / "understanding" / "runs" / f"{key}.json"
    run = (
        await asyncio.to_thread(load_json, checkpoint)
        if await asyncio.to_thread(checkpoint.exists)
        else {"cursor": 0, "links": [], "unresolved": [], "inspections": []}
    )
    if not await asyncio.to_thread(checkpoint.exists):
        # Reuse only completed units from the identical source, rules, Note bases and scope.
        # Every compact unit is still inspected; reconciliation deduplicates overlapping links.
        run["reused_units"] = 0
        for index in range(legacy_count):
            old_file = store.root(path) / "understanding" / "units" / f"{digest([legacy_key, index])}.json"
            if await asyncio.to_thread(old_file.exists):
                previous = await asyncio.to_thread(load_json, old_file)
                for field in ("links", "unresolved", "inspections"):
                    run[field].extend(previous[field])
                run["reused_units"] += 1
    progress = {"phase": "understanding", "total": len(units), "done": run["cursor"], "started_at": now()}
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)

    async def read_unit(unit_index):
        check_stop()
        await asyncio.to_thread(current, path, expected)
        if await asyncio.to_thread(scope.basis, path, notebook) != scope_basis:
            raise ValueError("可用章节范围已变化，请重新进行跨章理解")
        unit = units[unit_index]
        unit_key = digest([key, unit_index])
        unit_file = store.root(path) / "understanding" / "units" / f"{unit_key}.json"
        if await asyncio.to_thread(unit_file.exists):
            return await asyncio.to_thread(load_json, unit_file)
        result = {"links": [], "unresolved": [], "inspections": []}
        inquiry_file = store.root(path) / "understanding" / "inquiries" / f"{unit_key}.json"
        if await asyncio.to_thread(inquiry_file.exists):
            inquiry = await asyncio.to_thread(load_json, inquiry_file)
        else:
            inquiry = (
                await ask(
                    path,
                    generator,
                    Inquiry,
                    rules + scope_hint + "\n查询规划材料：" + json.dumps(unit, ensure_ascii=False),
                )
            ).model_dump()
            await run_noninterruptible_sync(store.write, inquiry_file, inquiry)
        anchor_records = [original_records[unit["note_id"]][record["id"]] for record in unit["records"]]
        anchors = await asyncio.to_thread(retrieval.anchors, corpus, anchor_records)
        # Split anchor material itself when dense chapters contain many source quotations.
        anchor_batches = list(synthesis.packs(anchors, 10000))
        unresolved = list(inquiry["questions"])
        for anchor_batch in anchor_batches:
            queries = inquiry["queries"] or [unit["title"]]
            seen = {f["id"] for f in anchor_batch}
            previous_matches = []
            for round_number in range(3):
                check_stop()
                if await asyncio.to_thread(scope.basis, path, notebook) != scope_basis:
                    raise ValueError("可用章节范围已变化，请重新进行跨章理解")
                matches = await asyncio.to_thread(retrieval.search, corpus, queries, exclude=seen, limit=6)
                supplied = anchor_batch + previous_matches[-2:] + matches
                previous_matches = matches
                round_key = digest([unit_key, supplied, queries, round_number])
                round_file = store.root(path) / "understanding" / "rounds" / f"{round_key}.json"
                if await asyncio.to_thread(round_file.exists):
                    findings = await asyncio.to_thread(load_json, round_file)
                else:

                    def validate(value, supplied=supplied, note_id=unit["note_id"]):
                        return ground(value, supplied, {note_id}, notebook)

                    findings = await ask(
                        path,
                        generator,
                        Findings,
                        rules
                        + scope_hint
                        + "\n回读问题："
                        + json.dumps(inquiry["questions"], ensure_ascii=False)
                        + "\n原文片段："
                        + json.dumps(supplied, ensure_ascii=False),
                        validate,
                        grow_output=True,
                    )
                    await run_noninterruptible_sync(store.write, round_file, findings)
                result["links"].extend(findings["links"])
                unresolved = findings["unresolved"]
                if not any(v["status"] == "supported" for v in findings["links"]) and not unresolved:
                    unresolved = list(inquiry["questions"])
                seen.update(f["id"] for f in matches)
                result["inspections"].append(
                    {
                        "anchor_note_id": unit["note_id"],
                        "queries": queries,
                        "fragment_ids": [f["id"] for f in supplied],
                        "note_ids": list(dict.fromkeys(f["note_id"] for f in supplied)),
                        "round": round_number + 1,
                    }
                )
                queries = findings["next_queries"]
                if not queries:
                    break
            if queries:
                unresolved += ["达到本次检索轮次上限，尚待回查：" + q for q in queries]
            result["unresolved"].extend({"note_id": unit["note_id"], "question": q} for q in unresolved)
        await run_noninterruptible_sync(store.write, unit_file, result)
        return result

    try:
        while run["cursor"] < len(units):
            check_stop()
            # Independent units finish their paid calls and persist before any sibling error propagates.
            results = await asyncio.gather(
                *(read_unit(i) for i in range(run["cursor"], min(run["cursor"] + 3, len(units)))),
                return_exceptions=True,
            )
            failure = None
            for result in results:
                if isinstance(result, BaseException):
                    failure = result
                    break
                for field in ("links", "unresolved", "inspections"):
                    run[field].extend(result[field])
                run["cursor"] += 1
            await run_noninterruptible_sync(store.write, checkpoint, run)
            progress["done"] = run["cursor"]
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
            if failure is not None:
                raise failure
        await asyncio.to_thread(current, path, expected)
        latest = await asyncio.to_thread(store.valid_readings, path, notebook)
        if (
            await asyncio.to_thread(scope.basis, path, notebook) != scope_basis
            or any(latest.get(i, {}).get("basis") != b for i, b in bases.items())
            or await asyncio.to_thread(understanding_rules, path) != rules
            or await asyncio.to_thread(store.effective_rule, path, "scope") != scope_rule
        ):
            raise ValueError("Understanding sources or rules changed; completed reread caches retained")
        from lib.novel_workflow.understanding_reconcile import reconcile

        reconciled, reconciliation_questions = await reconcile(path, generator, run["links"], notebook, wanted)
        await asyncio.to_thread(current, path, expected)
        latest = await asyncio.to_thread(store.valid_readings, path, notebook)
        if (
            await asyncio.to_thread(scope.basis, path, notebook) != scope_basis
            or any(latest.get(i, {}).get("basis") != b for i, b in bases.items())
            or await asyncio.to_thread(understanding_rules, path) != rules
            or await asyncio.to_thread(store.effective_rule, path, "scope") != scope_rule
        ):
            raise ValueError("汇总核对期间原文、范围或规则已变化；已完成缓存保留，请重试")
        report = {
            **run,
            "source_links": run["links"],
            "reconciliation_questions": reconciliation_questions,
            "id": key,
            "source_basis": expected,
            "rule_basis": digest(rules),
            "note_bases": bases,
            "links": reconciled,
            "unresolved": run["unresolved"]
            + [{"note_id": notes[0]["id"], "question": q} for q in reconciliation_questions],
            "created_at": now(),
            "selected_note_ids": [n["id"] for n in notes],
            "scope_note_ids": sorted(allowed),
            "scope_rule_basis": digest(scope_rule),
            "searched_note_count": len(allowed),
            "inspected_note_ids": list(dict.fromkeys(i for r in run["inspections"] for i in r["note_ids"])),
            "unread_inspected_note_ids": list(
                dict.fromkeys(i for r in run["inspections"] for i in r["note_ids"] if i not in readings)
            ),
        }
        await run_noninterruptible_sync(store.write, target, report)
        progress.update(phase="complete", done=len(units))
        return {"report_id": key, "links": len(report["links"])}
    except Exception as exc:
        progress.update(phase="stopped" if isinstance(exc, NovelReadingInterrupted) else "failed", error=str(exc))
        raise
    finally:
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)


def require_understood(path, note_ids):
    if not settings.get(path)["understanding_enabled"]:
        return
    reports = view(path)["reports"]
    completed = {i for r in reports if not r["stale"] for i in r["selected_note_ids"]}
    if not set(note_ids) <= completed:
        raise ValueError("所选章节的跨章理解尚未完成。先运行跨章理解与回查，或在阅读设置中关闭理解层。")
