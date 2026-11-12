"""Bounded reconciliation of links sharing a kind and chapter pair; originals stay on disk."""

import asyncio
import json
from collections import defaultdict

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest
from lib.novel_workflow import store, synthesis
from lib.novel_workflow.understanding_models import Findings


async def reconcile(path, generator, links, notebook, anchors):
    from lib.novel_workflow.service import ask
    from lib.novel_workflow.understanding import ground

    rules = await asyncio.to_thread(store.effective_rule, path, "understand_reconcile")
    groups = defaultdict(list)
    for link in links:
        groups[(link["kind"], tuple(sorted(link["note_ids"])))].append(link)
    result, unresolved = [], []
    for group in groups.values():
        unique = list({digest(link): link for link in group}.values())
        for batch in synthesis.packs(unique, 12000):
            check_stop()
            if len(batch) == 1:
                result.extend(batch)
                continue
            fragments = {}
            for link in batch:
                for evidence in link["evidence"]:
                    fragment_id = digest(evidence)[:24]
                    fragments[fragment_id] = {**evidence, "id": fragment_id, "text": evidence["quote"]}
            supplied = list(fragments.values())
            key = digest([rules, batch])
            cache = store.root(path) / "understanding" / "reconciliations" / f"{key}.json"
            if await asyncio.to_thread(cache.exists):
                value = await asyncio.to_thread(load_json, cache)
            else:

                async def validate(draft, supplied=supplied):
                    from lib.novel_workflow.citation_repair import repair

                    draft = await repair(path, generator, draft, supplied)
                    return ground(draft, supplied, anchors, notebook)

                value = await ask(
                    path,
                    generator,
                    Findings,
                    rules
                    + "\n关联汇总材料："
                    + json.dumps({"drafts": batch, "fragments": supplied}, ensure_ascii=False),
                    validate,
                    grow_output=True,
                )
                await run_noninterruptible_sync(store.write, cache, value)
            result.extend(value["links"])
            unresolved.extend(value["unresolved"])
            unresolved.extend("汇总核对仍需回查：" + q for q in value.get("next_queries", []))
    # Conflicting prose over the exact same source span must never be silently overwritten.
    by_id = {}
    for link in result:
        old = by_id.get(link["id"])
        if old and old["description"] != link["description"]:
            link = {
                **link,
                "status": "uncertain",
                "description": old["description"] + "；另有待核实表述：" + link["description"],
            }
        by_id[link["id"]] = link
    return list(by_id.values()), list(dict.fromkeys(unresolved))
