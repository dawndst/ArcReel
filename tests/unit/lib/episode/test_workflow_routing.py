import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.novel_understanding import service as legacy
from lib.novel_workflow import overview, scope, store
from lib.novel_workflow.routing import WorkflowError
from lib.novel_workflow.service import read_notes
from tests.unit.lib.episode.test_novel_workflow import Reader, project


def setup_project(path):
    data, book = project(path)
    data.update(content_mode="drama", novel_workflow_enabled=True)
    store.write(path / "project.json", data)
    return data, book


def test_overview_requires_explicit_scope_and_readings(tmp_path):
    data, book = setup_project(tmp_path)
    with pytest.raises(WorkflowError, match="可用章节范围"):
        overview.snapshot(tmp_path, data)
    scope.configure(tmp_path, data, [book["notes"][0]["id"]], book["source_basis"])
    with pytest.raises(WorkflowError, match="未精读"):
        overview.snapshot(tmp_path, data)


async def test_overview_uses_only_current_notes_and_rechecks_before_save(tmp_path, monkeypatch):
    data, book = await asyncio.to_thread(setup_project, tmp_path)
    first, second = [n["id"] for n in book["notes"]]
    await read_notes(tmp_path, Reader(), [first], book["source_basis"])
    legacy_ensure = AsyncMock(side_effect=AssertionError("legacy reader called"))
    monkeypatch.setattr(legacy, "ensure", legacy_ensure)
    captured = {}

    async def generate(name, **kwargs):
        captured.update(kwargs)
        await asyncio.to_thread(kwargs["source_check"], data)
        return {"synopsis": "范围内设定"}

    manager = SimpleNamespace(
        load_project=lambda name: data, get_project_path=lambda name: tmp_path, generate_overview=generate
    )
    assert await legacy.generate_project_overview(manager, "demo") == {"synopsis": "范围内设定"}
    assert first in captured["source_content_override"]
    assert second not in captured["source_content_override"]
    assert "乙推开城门" not in captured["source_content_override"]
    legacy_ensure.assert_not_called()
    scope.configure(tmp_path, data, [second], book["source_basis"])
    with pytest.raises(WorkflowError):
        captured["source_check"](data)


async def test_legacy_memory_and_unbound_scripts_fail_before_model_calls(tmp_path):
    data, _ = await asyncio.to_thread(setup_project, tmp_path)
    generator = SimpleNamespace(generate=AsyncMock())
    assert not legacy.applicable(data)
    with pytest.raises(WorkflowError, match="旧的全书阅读"):
        await legacy.ensure(tmp_path, data, generator)
    with pytest.raises(WorkflowError, match="Note 来源绑定"):
        await legacy.prepare(tmp_path, data, 1, "", {}, generator=generator)
    generator.generate.assert_not_called()
    assert not legacy.applicable({**data, "novel_workflow_enabled": False})


async def test_large_overview_is_reduced_in_bounded_cached_batches(tmp_path, monkeypatch):
    nodes = [{"note_ids": [str(i)], "overview": "已读内容" * 700} for i in range(20)]
    monkeypatch.setattr(overview, "snapshot", lambda path, project: {"basis": "same", "rule": "规则", "nodes": nodes})
    prompts = []

    async def generate(request, **kwargs):
        prompts.append(request.prompt)
        material = json.loads(request.prompt.split("Note 材料：", 1)[1].split("\n只输出 JSON", 1)[0])
        return SimpleNamespace(
            text=json.dumps(
                {"summary": "归纳人物关系与未解线索", "note_ids": [i for n in material for i in n["note_ids"]]}
            )
        )

    from lib.backends.text_generator import TextGenerator

    monkeypatch.setattr(TextGenerator, "create", AsyncMock(return_value=SimpleNamespace(generate=generate)))
    final = []

    async def save(name, **kwargs):
        final.append(kwargs["source_content_override"])
        kwargs["source_check"]({})
        return {}

    manager = SimpleNamespace(
        load_project=lambda name: {}, get_project_path=lambda name: tmp_path, generate_overview=save
    )
    await overview.generate(manager, "demo")
    assert len(prompts) > 1
    assert all(len(p) < 22000 for p in prompts)
    assert len(final[0]) < 18000
    calls = len(prompts)
    await overview.generate(manager, "demo")
    assert len(prompts) == calls
    material = json.loads(final[0].split("当前范围的 Note 理解成果：\n", 1)[1])
    assert {i for n in material for i in n["note_ids"]} == {str(i) for i in range(20)}






async def test_status_does_not_recommend_legacy_planning(tmp_path):
    from lib.workflow.workflow_state import WorkflowStateService
    from tests.integration.lib.workflow.test_workflow_state import _make_project, _write_source

    pm, path = await asyncio.to_thread(_make_project, tmp_path, "drama")
    await asyncio.to_thread(_write_source, pm, path)
    await asyncio.to_thread(pm.update_project, "demo", lambda p: p.update(novel_workflow_enabled=True))
    status = await asyncio.to_thread(WorkflowStateService(pm).get_status, "demo")
    assert status.next_action.type == "fix_input"
    assert "小说工作台" in status.next_action.reason
    assert "plan_episodes" not in status.operations
    assert not status.next_alternatives
