from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_removed_planning_routes_tools_and_implementation():
    from server.agent_toolset.toolset import ARCREEL_MCP_TOOL_IDS
    from server.app import app

    paths = set(app.openapi()["paths"])
    assert not any("episode-planning" in p or "episode-replan" in p or "manual-split" in p for p in paths)
    assert "/api/v1/projects/{name}/novel-workflow/run" in paths
    assert "/api/v1/projects/{name}/novel-workflow/stop" in paths
    assert "plan_episodes" not in ARCREEL_MCP_TOOL_IDS
    assert "reset_episode_planning" not in ARCREEL_MCP_TOOL_IDS
    root = Path(__file__).resolve().parents[4]
    for name in ("episode_planner", "episode_replan", "episode_reset", "episode_manual_split"):
        assert not (root / "lib/episode" / (name + ".py")).exists()


async def test_note_task_has_own_queue_and_only_reads_requested_chapters(tmp_path, monkeypatch):
    from lib.backends.text_generator import TextGenerator
    from lib.novel_workflow import service
    from server import tool_runtime

    generator = object()
    monkeypatch.setattr(TextGenerator, "create", AsyncMock(return_value=generator))
    read = AsyncMock(return_value={"notes": 2})
    monkeypatch.setattr(service, "read_notes", read)
    services = SimpleNamespace(
        projects=SimpleNamespace(
            load_project=lambda name: {"content_mode": "drama"}, get_project_path=lambda name: tmp_path
        )
    )
    result = await tool_runtime.execute_queued_text_task(
        {
            "task_id": "note-test",
            "project_name": "demo",
            "task_type": "text_novel_workflow",
            "payload": {"action": "read", "note_ids": ["chapter-3", "chapter-4"], "source_basis": "source-v1"},
        },
        services=services,
    )
    assert result == {"notes": 2}
    read.assert_awaited_once_with(tmp_path, generator, ["chapter-3", "chapter-4"], "source-v1")


async def test_note_submission_uses_independent_slot(monkeypatch):
    from server import tool_runtime

    monkeypatch.setattr(tool_runtime, "migration_gate", AsyncMock(return_value=None))
    submit = AsyncMock(return_value="queued")
    monkeypatch.setattr(tool_runtime, "_submit_text_task", submit)
    assert await tool_runtime.submit_note_workflow(None, None, None, {"action": "read", "note_ids": ["n1"]}) == "queued"
    assert submit.call_args.kwargs["task_type"] == "text_novel_workflow"
    assert submit.call_args.kwargs["unit_id"] == "novel-workflow"
    assert submit.call_args.kwargs["operation"] == "read_novel"
