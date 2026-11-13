"""Bounded hierarchical chapter summaries; raw evidence is never discarded."""

from __future__ import annotations

import asyncio
import json

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store
from lib.novel_workflow.memory import records
from lib.novel_workflow.models import ChapterSynthesis


def packs(values, budget=18000):
    group, size = [], 0
    for value in values:
        length = len(json.dumps(value, ensure_ascii=False))
        if group and size + length > budget:
            yield group
            group, size = [], 0
        group.append(value)
        size += length
    if group:
        yield group


async def chapter(path, generator, extracted, rule):
    from lib.novel_workflow.service import ask
    from lib.novel_workflow.settings import get

    limit = (await asyncio.to_thread(get, path))["summary_max_chars"]

    facts = {v["id"]: v for part in extracted for v in records(part)}
    if not facts:
        raise ValueError("No evidence records extracted; chapter cannot be marked complete")
    from lib.novel_workflow.understanding import inquiry_record

    nodes = [
        {"summary": part["summary"], "records": batch}
        for part in extracted
        for batch in packs([inquiry_record(record) for record in records(part)], 40000)
    ]
    while True:
        reduced = []
        for batch in packs(nodes, 48000):
            allowed = {v["id"] for node in batch for v in node.get("records", [])} | {
                i for node in batch for i in node.get("evidence_ids", [])
            }
            dialogue_owners = {
                dialogue["id"]: record["id"]
                for node in batch
                for record in node.get("records", [])
                for dialogue in record.get("dialogues", [])
            }
            key = digest([rule, batch])
            target = store.root(path) / "chapter_summaries" / f"{key}.json"
            if await asyncio.to_thread(target.exists):
                result = await asyncio.to_thread(load_json, target)
            else:

                def validate(value, allowed=allowed, dialogue_owners=dialogue_owners):
                    if len(value.summary) > limit:
                        raise ValueError(
                            f"Chapter summary exceeds configured limit {limit}; condense without losing core causality"
                        )
                    # Nested dialogue is supplied evidence; retain its parent event as the stable summary anchor.
                    value.evidence_ids = list(dict.fromkeys(dialogue_owners.get(i, i) for i in value.evidence_ids))
                    if not set(value.evidence_ids) <= allowed:
                        raise ValueError(
                            "Chapter summary cited unknown evidence: " + ", ".join(set(value.evidence_ids) - allowed)
                        )
                    return value.model_dump()

                result = await ask(
                    path,
                    generator,
                    ChapterSynthesis,
                    rule + "\n章节材料：" + json.dumps(batch, ensure_ascii=False),
                    validate,
                )
                await run_noninterruptible_sync(store.write, target, result)
            reduced.append(result)
        if len(reduced) == 1:
            return reduced[0]
        if len(reduced) >= len(nodes) and all("records" not in n for n in nodes):
            raise ValueError("Chapter synthesis exceeds context budget; reduce summary verbosity")
        nodes = reduced
