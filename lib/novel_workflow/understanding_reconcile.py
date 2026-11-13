"""Bounded reconciliation of links sharing a kind and chapter pair; originals stay on disk."""

import asyncio
import json
from collections import defaultdict

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest
from lib.novel_workflow import store, synthesis
from lib.novel_workflow.storage import load_json
from lib.novel_workflow.understanding_models import Findings


async def reconcile(path, generator, links, notebook, anchors):
    from lib.novel_workflow.service import ask

    rules = await asyncio.to_thread(store.effective_rule, path, "understand_reconcile")
    groups = defaultdict(list)
    for link in links:
        groups[(link["kind"], tuple(sorted(link["note_ids"])))].append(link)
    batches = []
    for group in groups.values():
        unique = list({digest(link): link for link in group}.values())
        batches.extend(synthesis.packs(unique, 12000))
    semaphore = asyncio.Semaphore(3)

    async def examine(batch):
        async with semaphore:
            check_stop()
            if len(batch) == 1:
                return {"links": batch, "unresolved": [], "next_queries": []}
            fragments = {}
            for link in batch:
                for evidence in link["evidence"]:
                    fragment_id = digest(evidence)[:24]
                    fragments[fragment_id] = {**evidence, "id": fragment_id, "text": evidence["quote"]}
            supplied = list(fragments.values())
            key = digest([rules, batch])
            cache = store.root(path) / "understanding" / "reconciliations" / f"{key}.json"
            if await asyncio.to_thread(cache.exists):
                return await asyncio.to_thread(load_json, cache)

            async def validate(draft):
                from lib.novel_workflow.citation_repair import verify

                return await verify(path, generator, draft, supplied, anchors, notebook)

            value = await ask(
                path,
                generator,
                Findings,
                rules + "\n关联汇总材料：" + json.dumps({"drafts": batch, "fragments": supplied}, ensure_ascii=False),
                validate,
                grow_output=True,
            )
            await run_noninterruptible_sync(store.write, cache, value)
            return value

    # Persist successful paid calls before reporting a sibling failure, as in the reread stage.
    values = await asyncio.gather(*(examine(batch) for batch in batches), return_exceptions=True)
    result, unresolved = [], []
    for value in values:
        if isinstance(value, BaseException):
            raise value
        result.extend(value["links"])
        unresolved.extend(value["unresolved"])
        unresolved.extend("汇总核对仍需回查：" + q for q in value.get("next_queries", []))
    return deduplicate(result), list(dict.fromkeys(unresolved))


def deduplicate(links):
    """Never silently overwrite conflicting prose over the exact same source spans."""
    by_id = {}
    for link in links:
        old = by_id.get(link["id"])
        if old and old["description"] != link["description"]:
            link = {
                **link,
                "status": "uncertain",
                "description": old["description"] + "；另有待核实表述：" + link["description"],
            }
        by_id[link["id"]] = link
    return list(by_id.values())
