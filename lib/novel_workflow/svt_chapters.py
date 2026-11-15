"""Chapter-specific SVT stories remain distinct from a shared mainline synopsis."""

import asyncio
import json

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_workflow import store
from lib.novel_workflow.common import digest
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json


class ChapterStory(StrictModel):
    note_id: str
    title: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=2, max_length=1500)
    advancement: str = Field(min_length=2, max_length=800)
    event_ids: list[str] = Field(min_length=1)


async def generate(path, generator, note, reading):
    from lib.novel_workflow.service import ask

    rule = await asyncio.to_thread(store.effective_rule, path, "svt_chapter")
    # The reviewed whole-chapter overview supplies causality; the complete title
    # index supplies grounded IDs without repeatedly sending all dialogue/raw prose.
    material = {
        "note_id": note["id"],
        "chapter_title": note["title"],
        "overview": reading["overview"],
        "events": [{"id": e["id"], "title": e["title"]} for e in reading["events"]],
    }
    basis = digest([rule, reading["basis"], material])
    target = store.root(path) / "svt_chapters" / f"{basis}.json"
    if await asyncio.to_thread(target.exists):
        return await asyncio.to_thread(load_json, target)

    def validate(value):
        if value.note_id != note["id"]:
            raise ValueError("本章 SVT 不得引用其他 Note")
        if len(value.event_ids) != len(set(value.event_ids)) or not set(value.event_ids) <= {
            e["id"] for e in reading["events"]
        }:
            raise ValueError("本章核心剧情必须关联本 Note 中不重复的有效事件")
        return value.model_dump()

    value = await ask(
        path, generator, ChapterStory,
        rule + "\n本章SVT材料：" + json.dumps(material, ensure_ascii=False),
        validate, max_output_tokens=3500,
    )
    if await asyncio.to_thread(store.effective_rule, path, "svt_chapter") != rule:
        raise ValueError("本章 SVT 规则已变化，请重新生成")
    value.update(basis=basis, reading_basis=reading["basis"], rule_basis=digest(rule))
    await run_noninterruptible_sync(store.write, target, value)
    return value
