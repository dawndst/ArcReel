import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import scene_review
from tests.unit.lib.episode.test_scene_library import scene_output


async def test_semantic_review_proposes_local_changes_without_editing_or_accepting_fabricated_evidence(tmp_path):
    scenes = scene_output()["scenes"]
    before = json.dumps(scenes)
    suggestion = {
        "scene_index": 0,
        "shot_index": 0,
        "segment_index": None,
        "field": "title",
        "before": "取剑镜头",
        "after": "拿起古剑",
        "source_quote": "甲拿起古剑。",
        "reason": "贴合原文",
    }

    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(text=json.dumps({"revisions": [suggestion], "unresolved": []}))

    review = await scene_review.review(tmp_path, Generator(), scenes, "甲拿起古剑。")
    assert review["revisions"][0]["applied"] is False
    assert json.dumps(scenes) == before
    suggestion["source_quote"] = "甲挥剑杀人。"
    with pytest.raises(ValueError, match="校验"):
        await scene_review.review(tmp_path, Generator(), scenes, "甲拿起古剑。")


async def test_adoption_versions_only_selected_field_and_guards_assembly(tmp_path):
    from lib.novel_workflow import scene_library, store
    from lib.novel_workflow.service import generate_svts, read_notes
    from tests.unit.lib.episode.test_novel_workflow import Reader, SVTReader, project

    data, notebook = await asyncio.to_thread(project, tmp_path)
    data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
    await asyncio.to_thread(store.write, tmp_path / "project.json", data)
    note_id = notebook["notes"][0]["id"]
    await read_notes(tmp_path, Reader(), [note_id], notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [note_id], notebook["source_basis"])

    class Generator:
        async def generate(self, request, **kwargs):
            if "逐项审核场镜" in request.prompt:
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "revisions": [
                                {
                                    "scene_index": 0,
                                    "shot_index": 0,
                                    "segment_index": None,
                                    "field": "title",
                                    "before": "取剑镜头",
                                    "after": "拿起古剑",
                                    "source_quote": "甲拿起古剑。",
                                    "reason": "明确动作",
                                }
                            ]
                        }
                    )
                )
            return SimpleNamespace(text=json.dumps(scene_output()))

    await scene_library.generate(tmp_path, Generator(), [note_id], notebook["source_basis"], durations=[8])
    batch = next(iter((await asyncio.to_thread(scene_library.catalog, tmp_path))["batches"].values()))
    shot = batch["scenes"][0]["shots"][0]
    with pytest.raises(ValueError, match="一致性修订"):
        scene_review.require_reviewed(batch, shot)
    result = await asyncio.to_thread(
        scene_review.adopt,
        tmp_path,
        data,
        batch["basis"],
        batch["review"]["revisions"][0]["id"],
        notebook["source_basis"],
    )
    assert result["applied"]
    saved = next(iter((await asyncio.to_thread(scene_library.catalog, tmp_path))["batches"].values()))
    assert saved["scenes"][0]["shots"][0]["title"] == "拿起古剑"
    assert saved["scenes"][0]["shots"][0]["evidence"] == shot["evidence"]
    scene_review.require_reviewed(saved, saved["scenes"][0]["shots"][0])
    histories = await asyncio.to_thread(lambda: list((store.root(tmp_path) / "history").glob("scene-revision-*.json")))
    old = await asyncio.to_thread(lambda: json.loads(histories[0].read_text()))
    assert old["scenes"][0]["shots"][0]["title"] == "取剑镜头"
