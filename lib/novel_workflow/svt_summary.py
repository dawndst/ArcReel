"""Publish a cumulative SVT synopsis, never the last event batch's rolling summary."""

import asyncio
import json

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.store import digest
from lib.novel_workflow import store, synthesis
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json


class Synopsis(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=3000)
    mainline_reason: str = Field(min_length=1, max_length=1500)
    note_ids: list[str] = Field(min_length=1)


async def finalize(path, generator, svts, notebook):
    from lib.novel_workflow.service import ask

    rule = await asyncio.to_thread(store.effective_rule, path, "svt_summary")
    result = []
    for svt in svts:
        cards, bases = [], {}
        for note in notebook["notes"]:
            if note["id"] not in svt["note_ids"]:
                continue
            reading = await asyncio.to_thread(store.note_result, path, note)
            if not reading:
                raise ValueError("SVT 概况缺少有效的来源 Note")
            from lib.novel_workflow.conclusions import effective_reading

            reading = await asyncio.to_thread(effective_reading, path, note, reading)
            bases[note["id"]] = reading["basis"]
            cards.append({"note_ids": [note["id"]], "order": note["order"], "summary": reading["overview"]["summary"]})
        if set(bases) != set(svt["note_ids"]):
            raise ValueError("SVT 概况包含当前章节索引以外的 Note")
        # One Note has exactly one primary SVT, including all its events. Its
        # validated overview already covers the complete source; do not resummarize it.
        if len(cards) == 1:
            result.append(
                {
                    **svt,
                    "summary": cards[0]["summary"],
                    "summary_rule_basis": digest(rule),
                    "summary_note_bases": bases,
                    "summary_mode": "chapter_overview",
                }
            )
            continue
        while True:
            reduced = []
            for batch in synthesis.packs(cards, 14000):
                expected = {i for card in batch for i in card["note_ids"]}
                material = {
                    "direction": {"title": svt["title"], "mainline_reason": svt["mainline_reason"]},
                    "opening_context": batch[0]["summary"].split("。", 1)[0] + "。",
                    "sources": batch,
                }
                key = digest([rule, material])
                target = store.root(path) / "svt_summaries" / f"{key}.json"
                if await asyncio.to_thread(target.exists):
                    value = await asyncio.to_thread(load_json, target)
                else:

                    def validate(value, expected=expected):
                        if set(value.note_ids) != expected or len(value.note_ids) != len(expected):
                            raise ValueError("累计概况必须覆盖本批所有来源 Note，不能只保留末章")
                        return value.model_dump()

                    value = await ask(
                        path,
                        generator,
                        Synopsis,
                        rule + "\nSVT累计概况材料：" + json.dumps(material, ensure_ascii=False),
                        validate,
                        max_output_tokens=6000,
                    )
                    await run_noninterruptible_sync(store.write, target, value)
                reduced.append(value)
            if len(reduced) == 1:
                break
            cards = reduced
        if await asyncio.to_thread(store.effective_rule, path, "svt_summary") != rule:
            raise ValueError("SVT 累计概况规则已变化，请重试")
        result.append(
            {
                **svt,
                **{k: reduced[0][k] for k in ("title", "summary", "mainline_reason")},
                "summary_mode": "cumulative",
                "summary_rule_basis": digest(rule),
                "summary_note_bases": bases,
            }
        )
    return result
