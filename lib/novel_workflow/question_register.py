"""Group reread prompts without discarding originals or turning questions into facts."""

import asyncio
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import retrieval, store, synthesis
from lib.novel_workflow.models import StrictModel

RULE = "understand_questions"
BATCH_BUDGET = 14000


class QuestionGroup(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    kind: Literal["plot_unrevealed", "extraction_check"]
    explanation: str = Field(min_length=1, max_length=500)
    source_ids: list[int] = Field(min_length=1)
    evidence_ids: list[int] = Field(default_factory=list, max_length=12)


class Grouping(StrictModel):
    groups: list[QuestionGroup] = Field(min_length=1)


def basis(report, rule):
    return digest(
        [
            rule,
            {
                k: report.get(k)
                for k in (
                    "id",
                    "source_basis",
                    "rule_basis",
                    "note_bases",
                    "scope_rule_basis",
                    "scope_note_ids",
                    "unresolved",
                    "links",
                )
            },
        ]
    )


def target(path, report):
    # Report IDs come from persisted workflow hashes, never arbitrary path segments.
    return store.root(path) / "understanding/question_register" / f"{digest(report['id'])}.json"


def load(path, report):
    file = target(path, report)
    if not file.exists():
        return None
    value = load_json(file)
    return {**value, "stale": value["basis"] != basis(report, store.effective_rule(path, RULE))}


def original_items(report):
    return [
        {"id": digest([report["id"], index])[:24], "index": index, **item}
        for index, item in enumerate(report.get("unresolved", []))
    ]


def initial_cards(originals):
    cards = {}
    for item in originals:
        key = (item["note_id"], re.sub(r"\s+", "", item["question"]))
        if key not in cards:
            cards[key] = {
                "question": item["question"],
                "original_ids": [],
                "note_ids": [item["note_id"]],
                "link_ids": [],
            }
        cards[key]["original_ids"].append(item["id"])
    return list(cards.values())


def relevant_links(cards, links):
    query = Counter(retrieval.tokens(" ".join(c["question"] for c in cards)))
    documents = [(link, set(retrieval.tokens(link["subject"] + " " + link["description"]))) for link in links]
    frequencies = Counter(token for _, words in documents for token in words)
    ranked = sorted(
        documents,
        key=lambda row: sum(math.log(1 + len(documents) / frequencies[word]) for word in row[1] & query.keys()),
        reverse=True,
    )
    selected, size = [], 0
    inherited = {i for card in cards for i in card["link_ids"]}
    ranked.sort(key=lambda row: row[0]["id"] not in inherited)
    for link, words in ranked:
        if not words & query.keys() and link["id"] not in inherited:
            continue
        card = {
            key: link.get(key)
            for key in ("id", "subject", "description", "status", "claim_type", "source_kind", "note_ids")
        }
        length = len(json.dumps(card, ensure_ascii=False))
        if size + length > 6000:
            continue
        selected.append(card)
        size += length
        if len(selected) == 12:
            break
    return selected


def prompt_card(card, index, titles):
    return {
        "source_id": index,
        "question": card["question"],
        "kind_hint": card.get("kind"),
        "chapters": [titles.get(n, n) for n in card["note_ids"]],
        "original_count": len(card["original_ids"]),
    }


def batches_for(cards, titles):
    indexed = [{"index": i, "prompt": prompt_card(card, i, titles)} for i, card in enumerate(cards)]
    return [[cards[item["index"]] for item in batch] for batch in synthesis.packs(indexed, BATCH_BUDGET)]


def material_for(cards, links, titles):
    relevant = relevant_links(cards, links)
    material = {
        "questions": [prompt_card(c, i, titles) for i, c in enumerate(cards)],
        "existing_evidence": [
            {**{k: v for k, v in link.items() if k != "id"}, "evidence_id": i} for i, link in enumerate(relevant)
        ],
    }
    return material, relevant


def regroup(value, cards, relevant):
    seen = [i for group in value.groups for i in group.source_ids]
    if len(seen) != len(cards) or set(seen) != set(range(len(cards))):
        counts = Counter(seen)
        raise ValueError(
            f"每条输入提示必须且只能归入一个问题；缺少来源编号：{sorted(set(range(len(cards))) - set(seen))}；"
            f"重复编号：{[i for i, n in counts.items() if n > 1]}；越界编号：{sorted(set(seen) - set(range(len(cards))))}"
        )
    result = []
    for group in value.groups:
        if len(set(group.source_ids)) != len(group.source_ids):
            raise ValueError("同一问题内的来源编号不能重复")
        if any(i < 0 or i >= len(relevant) for i in group.evidence_ids):
            raise ValueError("只能关联本批实际提供的已有证据")
        members = [cards[i] for i in group.source_ids]
        result.append(
            {
                "question": group.title,
                "kind": group.kind,
                "explanation": group.explanation,
                "original_ids": list(dict.fromkeys(i for c in members for i in c["original_ids"])),
                "note_ids": list(dict.fromkeys(i for c in members for i in c["note_ids"])),
                "link_ids": list(
                    dict.fromkeys(
                        [i for c in members for i in c["link_ids"]] + [relevant[i]["id"] for i in group.evidence_ids]
                    )
                ),
            }
        )
    return result


def partial_groups(value, cards, relevant):
    counts = Counter(i for group in value.groups for i in group.source_ids)
    affected = {i for i in range(len(cards)) if counts[i] != 1}
    for group in value.groups:
        if any(i < 0 or i >= len(cards) for i in group.source_ids) or any(
            i < 0 or i >= len(relevant) for i in group.evidence_ids
        ):
            affected.update(i for i in group.source_ids if 0 <= i < len(cards))
    good = [i for i in range(len(cards)) if i not in affected]
    positions = {original: index for index, original in enumerate(good)}
    groups = [
        group.model_copy(update={"source_ids": [positions[i] for i in group.source_ids if i in positions]})
        for group in value.groups
        if any(i in positions for i in group.source_ids)
    ]
    complete = regroup(Grouping(groups=groups), [cards[i] for i in good], relevant) if good else []
    return complete, [cards[i] for i in sorted(affected)]


async def group_cards(path, generator, cards, links, titles, rule):
    """Keep complete assignments and repair only missing or multiply assigned inputs."""
    from lib.novel_workflow.service import ask

    check_stop()
    material, relevant = material_for(cards, links, titles)
    key = digest([rule, cards, relevant])
    cache = store.root(path) / "understanding/question_groups" / f"{key}.json"
    if await asyncio.to_thread(cache.exists):
        return await asyncio.to_thread(load_json, cache)
    prompt = rule + "\n问题归并材料：" + json.dumps(material, ensure_ascii=False)
    candidate_file = store.root(path) / "understanding/question_candidates" / f"{key}.json"
    if len(cards) == 1:
        grouped = await ask(
            path, generator, Grouping, prompt, lambda draft: regroup(draft, cards, relevant), grow_output=True
        )
    else:
        if await asyncio.to_thread(candidate_file.exists):
            candidate = await asyncio.to_thread(load_json, candidate_file)
        else:
            candidate = await ask(path, generator, Grouping, prompt, lambda draft: draft.model_dump(), grow_output=True)
            await run_noninterruptible_sync(store.write, candidate_file, candidate)
        grouped, remaining = partial_groups(Grouping.model_validate(candidate), cards, relevant)
        if remaining:
            # Smaller requests avoid regenerating dozens of correct groups for one omitted ID.
            # If none were assigned safely, halve the input so recursive repair always terminates.
            chunks = (
                [remaining]
                if len(remaining) < len(cards)
                else [
                    remaining[: len(remaining) // 2],
                    remaining[len(remaining) // 2 :],
                ]
            )
            for batch in chunks:
                grouped.extend(await group_cards(path, generator, batch, links, titles, rule))
    await run_noninterruptible_sync(store.write, cache, grouped)
    return grouped


def publish(path, report, value, rule):
    from lib.novel_workflow.understanding import view

    with project_metadata_lock(path):
        current = next((r for r in view(path)["reports"] if r["id"] == report["id"] and not r["stale"]), None)
        if not current or basis(current, rule) != value["basis"] or store.effective_rule(path, RULE) != rule:
            raise ValueError("回查来源、阅读范围或归并规则已变化，已完成缓存保留，请重新整理")
        store.write(target(path, report), value)


async def build(path, generator, report, notebook):
    rule = await asyncio.to_thread(store.effective_rule, path, RULE)
    previous = await asyncio.to_thread(load, path, report)
    if previous and not previous["stale"]:
        return previous
    originals = original_items(report)
    allowed = set(report.get("scope_note_ids", report["selected_note_ids"]))
    if any(item["note_id"] not in allowed for item in originals):
        raise ValueError("原始待查提示引用了报告范围之外的章节，请核对回查记录")
    cards = initial_cards(originals)
    titles = {n["id"]: n["title"] for n in notebook["notes"]}
    links = report.get("links", [])
    level = 0
    global_checked = False
    progress = {
        "phase": "question_register",
        "step": "grouping",
        "total": len(originals),
        "done": 0,
        "started_at": now(),
    }
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
    while cards:
        # Only the compact question cards enter the next level; complete originals remain on disk.
        batches = batches_for(cards, titles)
        semaphore = asyncio.Semaphore(3)
        completed = 0
        progress.update(
            step="grouping" if level == 0 else "merge", total=len(originals) if level == 0 else len(cards), done=0
        )
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)

        async def group_batch(batch, semaphore=semaphore, level=level):
            nonlocal completed
            async with semaphore:
                check_stop()
                grouped = await group_cards(path, generator, batch, links, titles, rule)
                completed += sum(len(c["original_ids"]) for c in batch) if level == 0 else len(batch)
                progress["done"] = completed
                await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
                return grouped

        values = await asyncio.gather(*(group_batch(batch) for batch in batches), return_exceptions=True)
        reduced = []
        for value in values:
            if isinstance(value, BaseException):
                raise value
            reduced.extend(value)
        if len(batches) == 1:
            cards = reduced
            if level > 0 and len(cards) > 1 and not global_checked:
                # Recheck the global list after distributed grouping and isolated repairs.
                global_checked = True
                level += 1
                continue
            break
        # Never force unrelated topics together just to reduce a count or loop indefinitely.
        if len(reduced) >= len(cards):
            cards = reduced
            break
        cards = reduced
        level += 1
    grouped = [
        {**card, "id": digest(sorted(card["original_ids"]))[:24], "original_count": len(card["original_ids"])}
        for card in cards
    ]
    all_ids = [i for c in grouped for i in c["original_ids"]]
    if len(all_ids) != len(originals) or set(all_ids) != {o["id"] for o in originals}:
        raise ValueError("问题归并来源覆盖不完整，原始回查保留")
    value = {
        "basis": basis(report, rule),
        "report_id": report["id"],
        "created_at": now(),
        "original_count": len(originals),
        "group_count": len(grouped),
        "counts": {kind: sum(c["kind"] == kind for c in grouped) for kind in ("plot_unrevealed", "extraction_check")},
        "groups": grouped,
        "originals": originals,
        "rule_basis": digest(rule),
    }
    await run_noninterruptible_sync(publish, path, report, value, rule)
    return value


async def organize_notes(path: Path, generator, note_ids, expected, report_id=None):
    from lib.novel_workflow.service import current
    from lib.novel_workflow.understanding import view

    notebook = await asyncio.to_thread(current, path, expected)
    reports = (await asyncio.to_thread(view, path, notebook))["reports"]
    report = next(
        (
            r
            for r in reports
            if not r["stale"] and (r["id"] == report_id if report_id else set(r["selected_note_ids"]) == set(note_ids))
        ),
        None,
    )
    if not report or set(report["selected_note_ids"]) != set(note_ids):
        raise ValueError("请先完成所选章节的跨章回查，再整理对应报告的问题")
    try:
        result = await build(path, generator, report, notebook)
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {
                "phase": "complete",
                "total": result["original_count"],
                "done": result["original_count"],
            },
        )
        return {"report_id": report["id"], "groups": result["group_count"], "originals": result["original_count"]}
    except Exception as exc:
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {
                "phase": "failed",
                "error": str(exc),
            },
        )
        raise
