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
            if "# 镜头制作设计与来源关联" in request.prompt:
                payload = json.JSONDecoder().raw_decode(request.prompt[request.prompt.index('{"original":') :])[0]
                design = dict.fromkeys(
                    ["purpose", "shot_size", "camera_angle", "camera_movement", "framing", "continuity", "sound"],
                    "固定机位，原文动作连续",
                )
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "shots": [
                                {
                                    "shot_id": key,
                                    "event_ids": [payload["context"]["events"][0]["id"]],
                                    "moment_ids": [],
                                    "design": design,
                                }
                                for key in payload["shots"]
                            ]
                        }
                    )
                )
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


def test_confirm_question_is_individual_versioned_and_cannot_fake_repair(tmp_path, monkeypatch):
    from lib.novel_understanding.store import digest
    from lib.novel_workflow import scene_library, store

    batch = {
        "basis": "batch",
        "scenes": [
            {"shots": [{"segments": [{"utterances": [{"kind": "dialogue", "speaker": None, "text": "谁？"}]}]}]}
        ],
        "review": {"unresolved": ["台词缺少说话人", "需核对动作"], "revisions": []},
    }
    library = {"batches": {"batch": batch}}
    monkeypatch.setattr(store, "require_current", lambda *args: {})
    monkeypatch.setattr(store, "valid_readings", lambda *args: {})
    monkeypatch.setattr(scene_library, "catalog", lambda *args: library)
    monkeypatch.setattr(scene_library, "valid_batch", lambda *args: True)
    initial = digest(batch["review"])
    with pytest.raises(ValueError, match="缺少说话人"):
        scene_review.confirm_questions(
            tmp_path, {}, "batch", "source", initial, "已经修复并核对原文对应人物", 0, "repaired"
        )
    assert len(batch["review"]["unresolved"]) == 2
    scene_review.confirm_questions(
        tmp_path, {}, "batch", "source", initial, "动作与原文一致，审核意见为误报", 1, "false_positive"
    )
    assert batch["review"]["unresolved"] == ["台词缺少说话人"]
    assert batch["review"]["resolved_questions"][0]["questions"] == ["需核对动作"]
    assert batch["scenes"][0]["shots"][0]["segments"][0]["utterances"][0]["speaker"] is None
    with pytest.raises(ValueError, match="审核结果已变化"):
        scene_review.confirm_questions(
            tmp_path, {}, "batch", "source", initial, "再次尝试使用旧版本确认结果", 0, "false_positive"
        )
    batch["scenes"][0]["shots"][0]["segments"][0]["utterances"][0]["speaker"] = "甲"
    scene_review.confirm_questions(
        tmp_path, {}, "batch", "source", digest(batch["review"]), "已在台词处指定甲，与原文一致", 0, "repaired"
    )
    assert not batch["review"]["unresolved"]
    assert len(batch["review"]["resolved_questions"]) == 2
