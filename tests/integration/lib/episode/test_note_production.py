import asyncio
import json
from pathlib import Path

import pytest

from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, scene_library, scope, store, understanding
from lib.novel_workflow.director import assemble
from lib.novel_workflow.production import validate_binding
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
    library = {"batches": {}}
    for index, note in enumerate(indexed["notes"]):
        basis = store.reading_key(path, note)
        store.write(
            store.root(path) / "notes" / note["id"] / f"{basis}.json",
            {"basis": basis, "summaries": ["本章事件"], "assets": [], "changes": [], "events": [], "questions": []},
        )
        quote = ["甲取剑。", "乙开门。"][index]
        segments = [
            {
                "duration_seconds": 8,
                "scene_description": f"动作{j}",
                "characters_in_scene": [],
                "scenes": [],
                "props": [],
                "utterances": [],
            }
            for j in range(index + 1)
        ]
        shot = {
            "id": f"SH-{index}",
            "title": quote,
            "quote": quote,
            "segments": segments,
            "evidence": {
                "quote": quote,
                "note_id": note["id"],
                "source_file": "source/book.txt",
                "start": index * 10 + 6,
                "end": index * 10 + 10,
            },
        }
        library["batches"][str(index)] = {
            "basis": str(index),
            "note_id": note["id"],
            "note_order": index,
            "part": 0,
            "source_basis": indexed["source_basis"],
            "rule_basis": digest(store.rule(path, "scenes")),
            "note_bases": {note["id"]: basis},
            "understanding_basis": understanding.production_context(path, [note["id"]])["basis"],
            "scenes": [
                {
                    "id": f"SCN-{index}",
                    "title": quote,
                    "location": "未明",
                    "time": "未明",
                    "purpose": "行动",
                    "shots": [shot],
                }
            ],
            "skipped_reason": "",
        }
    store.write(store.root(path) / "scene_library.json", library)
    return pm, path, indexed


async def test_director_order_preserves_segments_and_retry_does_not_duplicate_episode(tmp_path):
    pm, path, indexed = await asyncio.to_thread(setup, tmp_path)
    args = (pm, "demo", ["SH-1", "SH-0"], "导演编排", indexed["source_basis"], "request-one")
    episode = await asyncio.to_thread(assemble, *args)
    assert await asyncio.to_thread(assemble, *args) == episode
    project = await asyncio.to_thread(pm.load_project, "demo")
    assert len(project["episodes"]) == 1
    plan = json.loads((path / f"drafts/episode_{episode}/script_plan_normalized_script.json").read_text())
    assert [(s["scene_number"], s["shot_number"], s["segment_number"]) for s in plan["scenes"]] == [
        (1, 1, 1),
        (1, 1, 2),
        (2, 1, None),
    ]
    assert plan["scenes"][0]["source_text"] == "乙开门。"
    assert not store.state(path)["groups"]
    await asyncio.to_thread(validate_binding, path, episode, project["episodes"][0]["note_source"])


async def test_only_selected_shots_enter_episode_and_outside_scope_is_rejected(tmp_path):
    pm, path, indexed = await asyncio.to_thread(setup, tmp_path)
    project = await asyncio.to_thread(pm.load_project, "demo")
    first = indexed["notes"][0]["id"]
    await asyncio.to_thread(scope.configure, path, project, [first], indexed["source_basis"])
    with pytest.raises(ValueError, match="依据失效"):
        await asyncio.to_thread(assemble, pm, "demo", ["SH-1"], "未来", indexed["source_basis"], "bad")
    episode = await asyncio.to_thread(assemble, pm, "demo", ["SH-0"], "一镜成集", indexed["source_basis"], "good")
    text = (path / f"source/episode_{episode}.txt").read_text()
    assert text == "甲取剑。"
    assert len((await asyncio.to_thread(pm.load_project, "demo"))["episodes"]) == 1


async def test_library_change_blocks_production_and_duplicate_shots_rejected(tmp_path):
    pm, path, indexed = await asyncio.to_thread(setup, tmp_path)
    with pytest.raises(ValueError, match="不重复"):
        await asyncio.to_thread(assemble, pm, "demo", ["SH-0", "SH-0"], "重复", indexed["source_basis"], "duplicate")
    episode = await asyncio.to_thread(assemble, pm, "demo", ["SH-0"], "选定", indexed["source_basis"], "selected")
    project = await asyncio.to_thread(pm.load_project, "demo")
    library = scene_library.catalog(path)
    library["batches"]["0"]["scenes"][0]["shots"][0]["segments"][0]["scene_description"] = "被改变的动作"
    store.write(store.root(path) / "scene_library.json", library)
    with pytest.raises(ValueError, match="镜头已变化"):
        await asyncio.to_thread(validate_binding, path, episode, project["episodes"][0]["note_source"])


async def test_native_review_receives_selected_content_and_failed_publication_resumes(tmp_path, monkeypatch):
    from lib.novel_workflow import director
    from server.services.project.script_review import ScriptReviewService

    pm, path, indexed = await asyncio.to_thread(setup, tmp_path)
    real_write = director.write_formal_script_plan_locked

    def fail(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(director, "write_formal_script_plan_locked", fail)
    args = (pm, "demo", ["SH-1"], "待完成", indexed["source_basis"], "recoverable")
    with pytest.raises(OSError, match="disk failure"):
        await asyncio.to_thread(assemble, *args)
    pending = await asyncio.to_thread(store.view, path, await asyncio.to_thread(pm.load_project, "demo"))
    assert len(pending["pending_assemblies"]) == 1
    monkeypatch.setattr(director, "write_formal_script_plan_locked", real_write)
    episode = await asyncio.to_thread(assemble, *args)
    assert len((await asyncio.to_thread(pm.load_project, "demo"))["episodes"]) == 1
    review = await ScriptReviewService(pm).get_state("demo", episode)
    assert review["status"] == "pending_review"
    assert len(review["content"]["scenes"]) == 2
    assert review["content"]["scenes"][0]["source_text"] == "乙开门。"
