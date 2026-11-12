"""Repair malformed cross-chapter citations by selecting literal source paragraphs."""

import asyncio
import json

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.understanding_models import Citation


class Selection(StrictModel):
    candidate_ids: list[str] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=500)


def candidates(text):
    result = {}
    offset = 0
    for line in text.splitlines(keepends=True):
        quote = line.strip()
        if len(quote) >= 2:
            try:
                start, end = locate(text, quote)
            except ValueError:
                quote = text[max(0, offset - 120) : min(len(text), offset + len(line) + 120)].strip()
                try:
                    start, end = locate(text, quote)
                except ValueError:
                    offset += len(line)
                    continue
            if end - start <= 1200:
                result[str(len(result))] = text[start:end]
        offset += len(line)
    return result


async def repair(path, generator, findings, supplied):
    from lib.novel_workflow.service import ask

    fragments = {v["id"]: v for v in supplied}
    for link in findings.links:
        repaired = []
        for citation in link.citations:
            fragment = fragments.get(citation.fragment_id)
            if fragment is None:
                repaired.append(citation)
                continue
            try:
                locate(fragment["text"], citation.quote)
                repaired.append(citation)
                continue
            except ValueError:
                pass
            # A mistyped fragment ID is handled by the existing unique-span grounding path.
            if any(_literal(other["text"], citation.quote) for other in supplied):
                repaired.append(citation)
                continue
            options = candidates(fragment["text"])
            if not options:
                raise ValueError("没有可唯一定位的连续原文候选")
            rule = await asyncio.to_thread(store.effective_rule, path, "understand_citations")
            material = {
                "claim": link.model_dump(exclude={"citations"}),
                "invalid_quote": citation.quote,
                "candidates": options,
            }
            cache = store.root(path) / "citation_repairs" / f"{digest([rule, material])}.json"
            if await asyncio.to_thread(cache.exists):
                selected = await asyncio.to_thread(load_json, cache)
            else:

                def validate(value, options=options):
                    if not value.candidate_ids or not set(value.candidate_ids) <= options.keys():
                        raise ValueError("原文不足以支持该引用，或选择了不存在的候选：" + value.reason)
                    if len(set(value.candidate_ids)) != len(value.candidate_ids):
                        raise ValueError("原文候选不可重复")
                    return value.model_dump()

                selected = await ask(
                    path,
                    generator,
                    Selection,
                    rule + "\n引文修复材料：" + json.dumps(material, ensure_ascii=False),
                    validate,
                    max_output_tokens=2000,
                )
                await run_noninterruptible_sync(store.write, cache, selected)
            repaired.extend(Citation(fragment_id=fragment["id"], quote=options[i]) for i in selected["candidate_ids"])
        link.citations = list({(v.fragment_id, v.quote): v for v in repaired}.values())
        if not 2 <= len(link.citations) <= 8:
            raise ValueError("修复后仍需二至八条独立原文引用")
    return findings


def _literal(text, quote):
    try:
        locate(text, quote)
        return True
    except ValueError:
        return False
