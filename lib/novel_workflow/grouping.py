"""Management groups summarize Notes; they never create episodes."""

import asyncio

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store, synthesis


def set_usage(path, project, group_id, usage, expected):
    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        group = next((g for g in notebook["groups"] if g["id"] == group_id), None)
        if group is None or usage not in ("reference", "candidate"):
            raise ValueError("资料组不存在或用途无效")
        group["usage"] = usage
        store.write(store.root(path) / "index.json", notebook)
        return group


async def summarize(path, generator, note_ids, expected, group_id):
    from lib.novel_workflow.service import current

    notebook = await asyncio.to_thread(current, path, expected)
    group = next((g for g in notebook["groups"] if g["id"] == group_id), None)
    if not group or set(group["note_ids"]) != set(note_ids):
        raise ValueError("资料组已变化，请刷新后重新归纳")
    readings = await asyncio.to_thread(store.valid_readings, path, notebook)
    if any(i not in readings for i in note_ids):
        raise ValueError("请先为组合内的章节生成 Notes，再重新归纳组合梗概")
    bases = {i: readings[i]["basis"] for i in note_ids}
    rules = await asyncio.to_thread(store.rule, path, "group")
    extracted = [{**readings[i], "summary": "\n".join(readings[i].get("summaries", []))} for i in group["note_ids"]]
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "group_summary", "done": 0, "total": 1}
    )
    try:
        result = await synthesis.chapter(path, generator, extracted, rules)
    except BaseException as exc:
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "group_summary", "done": 0, "total": 1, "error": str(exc)},
        )
        raise

    def commit():
        with project_metadata_lock(path):
            latest = current(path, expected)
            fresh = store.valid_readings(path, latest)
            target = next((g for g in latest["groups"] if g["id"] == group_id), None)
            if (
                not target
                or target["note_ids"] != group["note_ids"]
                or any(fresh.get(i, {}).get("basis") != b for i, b in bases.items())
                or store.rule(path, "group") != rules
            ):
                raise ValueError("资料或规则已变化，梗概未覆盖当前资料组")
            target["synopsis"] = result
            target["summary_bases"] = bases
            target["summary_rule_basis"] = digest(rules)
            target["summarized_at"] = now()
            store.write(store.root(path) / "index.json", latest)

    await run_noninterruptible_sync(commit)
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "idle", "done": 1, "total": 1}
    )
    return {"group_id": group_id}
