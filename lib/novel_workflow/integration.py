"""Bind director-selected Note evidence to the native production pipeline."""

import asyncio
import json

from lib.novel_workflow.production import NoteProductionGuard
from lib.novel_workflow.routing import WorkflowError


def encode(value):
    return json.dumps(value, ensure_ascii=False)


async def prepare(
    path, project, episode, text, inputs, *, dry_run=False, generator=None
) -> tuple[dict, NoteProductionGuard | None]:
    if project.get("content_mode") != "drama":
        return inputs, None
    entry = next((e for e in project.get("episodes", []) if e.get("episode") == episode), {})
    if not entry.get("note_source"):
        raise WorkflowError("本集缺少 Note 来源绑定。请从场镜素材库选择场和镜头，由导演组集后再生成脚本。")
    from lib.backends.providers import CallPurpose
    from lib.backends.text_backends.base import TextTaskType
    from lib.backends.text_generator import TextGenerator
    from lib.novel_workflow.production import prepare as prepare_notes

    if generator is None and not dry_run:
        generator = await TextGenerator.create(TextTaskType.SCRIPT, path.name, purpose=CallPurpose.SCRIPT_GENERATION)
    return await prepare_notes(path, episode, entry["note_source"], inputs, generator, dry_run=dry_run)


async def generate_project_overview(manager, name):
    project = await asyncio.to_thread(manager.load_project, name)
    if project.get("content_mode") == "drama":
        from lib.novel_workflow.overview import generate

        return await generate(manager, name)
    return await manager.generate_overview(name)
