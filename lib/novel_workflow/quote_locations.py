"""Resolve ambiguous literal citations using explicit source candidates, never nearest-position guessing."""

import asyncio
import json

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.store import digest
from lib.novel_workflow import memory, store, synthesis
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json


class Location(StrictModel):
    record_id: str
    candidate_id: str | None
    reason: str = Field(min_length=1, max_length=500)


class Locations(StrictModel):
    locations: list[Location]


def candidates(text, quote):
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[i] for i in positions)
    needle = "".join(quote.split())
    if needle not in compact:
        needle = needle.strip('「」『』“”‘’"')
    if not needle:
        return []
    spans, offset = [], compact.find(needle)
    while offset >= 0:
        spans.append((positions[offset], positions[offset + len(needle) - 1] + 1))
        offset = compact.find(needle, offset + 1)
    result = []
    for i, (start, end) in enumerate(spans):
        left = max(0, start - 150, spans[i - 1][1] if i else 0)
        right = min(len(text), end + 150, spans[i + 1][0] if i + 1 < len(spans) else len(text))
        context = text[left:right]
        try:
            locate(text, context)
            locate(context, quote)
        except ValueError:
            continue
        result.append({"id": str(i), "context_quote": context})
    return result


async def resolve(path, generator, reading, part):
    from lib.novel_workflow.service import ask

    records = []
    for bucket in memory.BUCKETS:
        for i, item in enumerate(getattr(reading, bucket)):
            records.append((f"{bucket}.{i}", item, ""))
            if bucket == "events":
                records.extend(
                    (f"events.{i}.dialogues.{j}", d, item.title + "；" + item.action)
                    for j, d in enumerate(item.dialogues)
                )
    pending, by_id = [], {}
    for record_id, item, parent in records:
        try:
            locate(part["text"], item.quote)
            item.context_quote = ""
            continue
        except ValueError:
            pass
        if item.context_quote:
            try:
                start, end = locate(part["text"], item.context_quote)
                locate(part["text"][start:end], item.quote)
                continue
            except ValueError:
                pass
        options = candidates(part["text"], item.quote)
        if not options:
            # Non-literal quotes still go through the ordinary model correction path.
            continue
        claim = {k: v[:700] for k, v in item.model_dump().items() if isinstance(v, str) and k != "context_quote"}
        pending.append({"record_id": record_id, "claim": claim, "event": parent[:1000], "candidates": options})
        by_id[record_id] = item
    if not pending:
        return reading
    rule = await asyncio.to_thread(store.effective_rule, path, "quote_locations")
    for batch in synthesis.packs(pending, 10000):
        options = {v["record_id"]: {c["id"]: c["context_quote"] for c in v["candidates"]} for v in batch}
        key = digest([rule, batch])
        cache = store.root(path) / "quote_locations" / f"{key}.json"
        if await asyncio.to_thread(cache.exists):
            selected = await asyncio.to_thread(load_json, cache)
        else:

            def validate(value, options=options):
                ids = [v.record_id for v in value.locations]
                if len(ids) != len(options) or set(ids) != set(options):
                    raise ValueError("每个待定位记录必须且只能返回一次")
                for item in value.locations:
                    if item.candidate_id is not None and item.candidate_id not in options[item.record_id]:
                        raise ValueError("只能选择本记录给定的候选位置")
                return value.model_dump()

            selected = await ask(
                path,
                generator,
                Locations,
                rule + "\n引用定位候选：" + json.dumps(batch, ensure_ascii=False),
                validate,
                max_output_tokens=4000,
                include_fidelity=False,
            )
            await run_noninterruptible_sync(store.write, cache, selected)
        for selection in selected["locations"]:
            if selection["candidate_id"] is None:
                raise ValueError("引文归属仍不能可靠定位：" + selection["reason"])
            by_id[selection["record_id"]].context_quote = options[selection["record_id"]][selection["candidate_id"]]
    return reading
