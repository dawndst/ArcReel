"""Bounded story settings from current Note readings; never triggers full-book reading."""

import asyncio
import json

from pydantic import Field

from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import scope, store, synthesis
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.routing import WorkflowError, enabled


class OverviewMaterial(StrictModel):
    summary: str = Field(min_length=1, max_length=6000)
    note_ids: list[str] = Field(min_length=1)


def snapshot(path, project):
    if not enabled(project):
        raise WorkflowError("项目模式已变化，请刷新后重试")
    notebook = store.state(path)
    if not notebook:
        raise WorkflowError("请先在小说工作台建立章节 Notes、选择可用范围并泛读生成 Notes，再生成故事设定。")
    try:
        store.require_current(path, project, notebook["source_basis"])
    except ValueError as exc:
        raise WorkflowError("原文已变化，请先更新章节 Notes 并泛读生成 Notes。") from exc
    if not scope.get(path):
        raise WorkflowError("请先在小说工作台选择可用章节范围并泛读生成 Notes，再生成故事设定。")
    allowed = scope.available_ids(path, notebook)
    readings = store.valid_readings(path, notebook)
    notes = [n for n in notebook["notes"] if n["id"] in allowed]
    if not notes or any(n["id"] not in readings or not readings[n["id"]].get("overview") for n in notes):
        raise WorkflowError(
            "当前可用范围还有未生成或已过期的 Notes。请泛读生成 Notes，或缩小可用范围，再生成故事设定。"
        )
    rule = store.effective_rule(path, "overview")
    bases = {n["id"]: readings[n["id"]]["basis"] for n in notes}
    nodes = []
    for note in notes:
        content = json.dumps(
            {k: v for k, v in readings[note["id"]]["overview"].items() if k != "evidence_ids"}, ensure_ascii=False
        )
        nodes.extend(
            {"note_ids": [note["id"]], "title": note["title"], "material": content[offset : offset + 6000]}
            for offset in range(0, len(content), 6000)
        )
    return {
        "basis": digest([notebook["source_basis"], scope.basis(path, notebook), bases, rule]),
        "rule": rule,
        "nodes": nodes,
    }


async def generate(manager, name):
    from lib.backends.providers import CallPurpose
    from lib.backends.text_backends.base import TextTaskType
    from lib.backends.text_generator import TextGenerator
    from lib.novel_workflow.service import ask

    path = await asyncio.to_thread(manager.get_project_path, name)
    project = await asyncio.to_thread(manager.load_project, name)
    initial = await asyncio.to_thread(snapshot, path, project)
    generator = None
    nodes = initial["nodes"]
    while len(json.dumps(nodes, ensure_ascii=False)) > 18000:
        reduced = []
        for batch in synthesis.packs(nodes, 18000):
            allowed = {i for n in batch for i in n["note_ids"]}
            cache = store.root(path) / "overview_summaries" / (digest([initial["rule"], batch]) + ".json")
            if await asyncio.to_thread(cache.exists):
                result = await asyncio.to_thread(load_json, cache)
            else:
                if generator is None:
                    generator = await TextGenerator.create(
                        TextTaskType.OVERVIEW, name, purpose=CallPurpose.PROJECT_OVERVIEW
                    )

                def validate(value, allowed=allowed):
                    if set(value.note_ids) != allowed or len(value.note_ids) != len(allowed):
                        raise ValueError("故事设定归纳必须保留本批全部 Note 来源，不能新增或遗漏章节")
                    return value.model_dump()

                result = await ask(
                    path,
                    generator,
                    OverviewMaterial,
                    initial["rule"] + "\nNote 材料：" + json.dumps(batch, ensure_ascii=False),
                    validate,
                )
                await run_noninterruptible_sync(store.write, cache, result)
            reduced.append(result)
        if len(json.dumps(reduced, ensure_ascii=False)) >= len(json.dumps(nodes, ensure_ascii=False)):
            raise WorkflowError("故事设定归纳未能缩小上下文，请缩小可用章节范围后重试。")
        nodes = reduced

    def check(current):
        if snapshot(path, current)["basis"] != initial["basis"]:
            raise WorkflowError("生成期间 Note、可用范围或提示词已变化，请重新生成故事设定。")

    await asyncio.to_thread(check, await asyncio.to_thread(manager.load_project, name))
    return await manager.generate_overview(
        name,
        source_content_override=initial["rule"]
        + "\n当前范围的 Note 理解成果：\n"
        + json.dumps(nodes, ensure_ascii=False),
        source_check=check,
    )
