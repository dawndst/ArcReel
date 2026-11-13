"""Group reread prompts without discarding originals or turning questions into facts."""

import asyncio
import json
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
from lib.novel_workflow import store
from lib.novel_workflow.models import StrictModel

RULE = "understand_questions"
MAX_MODEL_CALLS = 2
MAX_INPUT_CHARS = 120000


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


class Topic(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    kind: Literal["plot_unrevealed", "extraction_check"]
    explanation: str = Field(min_length=1, max_length=300)
    evidence_ids: list[int] = Field(default_factory=list, max_length=12)


class SingleGrouping(StrictModel):
    groups: list[Topic] = Field(min_length=1)
    assignments: list[int] = Field(min_length=1)


class QuestionBudgetExceeded(RuntimeError):
    """Stop before additional paid generations; caller must explicitly retry."""


class LimitedGenerator:
    def __init__(self, generator):
        self.generator = generator
        self.calls = 0

    async def generate(self, request, **kwargs):
        if self.calls >= MAX_MODEL_CALLS:
            raise QuestionBudgetExceeded("问题整理已达到本次2次生成上限，原始提示和既有台账已保留，未继续调用模型")
        self.calls += 1
        return await self.generator.generate(request, **kwargs)


def single_material(cards, links, notebook):
    orders = {n["id"]: n["order"] for n in notebook["notes"]}
    return {
        "questions": [{"question": c["question"], "chapters": [orders.get(n) for n in c["note_ids"]]} for c in cards],
        "existing_evidence": [
            {
                **{k: link.get(k) for k in ("subject", "description", "status", "claim_type", "source_kind")},
                "evidence_id": i,
                "chapters": [orders.get(n) for n in link["note_ids"]],
            }
            for i, link in enumerate(links)
        ],
    }


def assignments_to_cards(value, cards, links):
    if len(value.assignments) != len(cards):
        raise ValueError(
            f"assignments必须恰好包含{len(cards)}个整数，按输入顺序逐项分配；当前有{len(value.assignments)}个"
        )
    if any(i < 0 or i >= len(value.groups) for i in value.assignments):
        raise ValueError("assignments只能引用实际返回的groups数组下标")
    groups = []
    for index, topic in enumerate(value.groups):
        sources = [i for i, assigned in enumerate(value.assignments) if assigned == index]
        if sources:
            groups.append(QuestionGroup(**topic.model_dump(), source_ids=sources))
    return regroup(Grouping(groups=groups), cards, links)


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


def publish(path, report, value, rule):
    from lib.novel_workflow.understanding import view

    with project_metadata_lock(path):
        current = next((r for r in view(path)["reports"] if r["id"] == report["id"] and not r["stale"]), None)
        if not current or basis(current, rule) != value["basis"] or store.effective_rule(path, RULE) != rule:
            raise ValueError("回查来源、阅读范围或归并规则已变化，已完成缓存保留，请重新整理")
        store.write(target(path, report), value)


async def build(path, generator, report, notebook, *, allow_model=False):
    from lib.novel_workflow.service import ask

    rule = await asyncio.to_thread(store.effective_rule, path, RULE)
    previous = await asyncio.to_thread(load, path, report)
    if previous and not previous["stale"]:
        return previous
    originals = original_items(report)
    allowed = set(report.get("scope_note_ids", report["selected_note_ids"]))
    if any(item["note_id"] not in allowed for item in originals):
        raise ValueError("原始待查提示引用了报告范围之外的章节，请核对回查记录")
    if originals and not allow_model:
        # Finishing a reread never silently starts another paid question-processing pipeline.
        return None
    cards = initial_cards(originals)
    grouped = []
    model_calls = 0
    if cards:
        check_stop()
        links = report.get("links", [])
        material = single_material(cards, links, notebook)
        prompt = rule + "\n问题归并材料：" + json.dumps(material, ensure_ascii=False)
        if len(prompt) + len(json.dumps(SingleGrouping.model_json_schema(), ensure_ascii=False)) > MAX_INPUT_CHARS:
            raise QuestionBudgetExceeded("问题整理输入超出本次长度上限；原始提示已保留，请缩小范围，不自动分批追加调用")
        key = digest([rule, cards, links])
        cache = store.root(path) / "understanding/question_single" / f"{key}.json"
        if await asyncio.to_thread(cache.exists):
            grouped = await asyncio.to_thread(load_json, cache)
        else:
            limited = LimitedGenerator(generator)
            await run_noninterruptible_sync(
                store.write,
                store.root(path) / "progress.json",
                {
                    "phase": "question_register",
                    "step": "grouping",
                    "total": len(originals),
                    "done": 0,
                    "started_at": now(),
                },
            )
            grouped = await ask(
                path,
                limited,
                SingleGrouping,
                prompt,
                lambda draft: assignments_to_cards(draft, cards, links),
                max_output_tokens=12000,
            )
            model_calls = limited.calls
            await run_noninterruptible_sync(store.write, cache, grouped)
    grouped = [
        {**card, "id": digest(sorted(card["original_ids"]))[:24], "original_count": len(card["original_ids"])}
        for card in grouped
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
        "model_calls": model_calls,
    }
    await run_noninterruptible_sync(publish, path, report, value, rule)
    return value


async def organize_notes(path: Path, generator, note_ids, expected, report_id=None, *, allow_model=False):
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
        result = await build(path, generator, report, notebook, allow_model=allow_model)
        if result is None:
            await run_noninterruptible_sync(
                store.write,
                store.root(path) / "progress.json",
                {
                    "phase": "complete",
                    "total": 0,
                    "done": 0,
                },
            )
            return {"report_id": report["id"], "requires_explicit_ai": True, "model_calls": 0}
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
