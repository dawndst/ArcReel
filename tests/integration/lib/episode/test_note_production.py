import asyncio
from pathlib import Path

from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, store
from lib.novel_workflow.production import arrange_episode, validate_binding
from lib.project.project_manager import ProjectManager


def setup(tmp_path: Path):
    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "drama")
    path = pm.get_project_path("demo")
    from lib.novel_workflow.settings import update

    update(path, {"understanding_enabled": False})
    (path / "source/book.txt").write_text("# 第一章\n甲取剑。\n# 第二章\n乙开门。\n")
    pm.update_project(
        "demo", lambda p: p.update(whole_source_files=[{"source_file": "source/book.txt"}], novel_workflow_enabled=True)
    )
    project = pm.load_project("demo")
    indexed = chapters.index(path, project)
    store.initialize(path, project, indexed["source_basis"])
    for note in indexed["notes"]:
        basis = store.reading_key(path, note)
        store.write(
            store.root(path) / "notes" / note["id"] / f"{basis}.json",
            {"basis": basis, "summaries": ["本章事件"], "assets": [], "changes": [], "events": [], "questions": []},
        )
    group = store.group_notes(path, project, [n["id"] for n in indexed["notes"]], "人工编排", indexed["source_basis"])
    return pm, path, group


async def test_arrangement_reuses_same_episode_and_freezes_note_sources(tmp_path):
    pm, path, group = await asyncio.to_thread(setup, tmp_path)
    episode = await asyncio.to_thread(arrange_episode, pm, "demo", group["id"])
    again = await asyncio.to_thread(arrange_episode, pm, "demo", group["id"])
    assert again == episode
    project = await asyncio.to_thread(pm.load_project, "demo")
    assert len(project["episodes"]) == 1
    binding = project["episodes"][0]["note_source"]
    assert len(binding["note_bases"]) == 2
    _, readings = await asyncio.to_thread(validate_binding, path, episode, binding)
    assert len(readings) == 2
    assert binding["text_basis"] == digest(await asyncio.to_thread((path / f"source/episode_{episode}.txt").read_text))


async def test_enabled_understanding_is_required_and_bound_to_production(tmp_path):
    import pytest

    from lib.novel_workflow import settings

    pm, path, group = await asyncio.to_thread(setup, tmp_path)
    await asyncio.to_thread(settings.update, path, {"understanding_enabled": True})
    with pytest.raises(ValueError, match="尚未完成"):
        await asyncio.to_thread(arrange_episode, pm, "demo", group["id"])

    def save_report():
        notebook = store.state(path)
        bases = {n["id"]: store.note_result(path, n)["basis"] for n in notebook["notes"]}
        store.write(
            store.root(path) / "understanding/reports/test.json",
            {
                "id": "test",
                "source_basis": notebook["source_basis"],
                "rule_basis": digest(store.rule(path, "understand")),
                "note_bases": bases,
                "created_at": "2026-11-09T00:00:00Z",
                "selected_note_ids": list(bases),
                "links": [],
            },
        )

    await asyncio.to_thread(save_report)
    episode = await asyncio.to_thread(arrange_episode, pm, "demo", group["id"])
    project = await asyncio.to_thread(pm.load_project, "demo")
    binding = project["episodes"][0]["note_source"]
    assert binding["understanding_basis"] == digest([])
    await asyncio.to_thread(validate_binding, path, episode, binding)
    await asyncio.to_thread((store.root(path) / "rules/understand.md").write_text, "New understanding rule")
    with pytest.raises(ValueError, match="尚未完成"):
        await asyncio.to_thread(validate_binding, path, episode, binding)
