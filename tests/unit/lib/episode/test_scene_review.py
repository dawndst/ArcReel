import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import scene_review


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

    from tests.unit.lib.episode.test_scene_pipeline import model_output

    class Generator:
        async def generate(self, request, **kwargs):
            value = model_output(request)
            if request.response_schema["title"] == "Inspection":
                material = json.loads(request.prompt.split("阶段材料：", 1)[1])
                value["corrections"] = [
                    {
                        "shot_id": material["shots"][0]["id"],
                        "segment_index": None,
                        "field": "title",
                        "after": "拿起古剑",
                        "source_ids": list(material["evidence"]),
                        "reason": "明确动作",
                    }
                ]
            return SimpleNamespace(text=json.dumps(value))

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
    library = await asyncio.to_thread(scene_library.catalog, tmp_path)
    batch = next(iter(library["batches"].values()))
    segment = batch["scenes"][0]["shots"][0]["segments"][0]
    suggestion = {
        "scene_index": 0,
        "shot_index": 0,
        "segment_index": 0,
        "field": "utterances",
        "before": segment["utterances"],
        "after": [{"kind": "voiceover", "text": "伪造的原文台词"}],
        "source_quote": "甲拿起古剑。",
        "reason": "补足声音",
        "id": "dialogue-revision",
        "applied": False,
    }
    batch["review"]["revisions"].append(suggestion)
    await asyncio.to_thread(store.write, store.root(tmp_path) / "scene_library.json", library)
    with pytest.raises(ValueError, match="连续摘录"):
        await asyncio.to_thread(
            scene_review.adopt, tmp_path, data, batch["basis"], suggestion["id"], notebook["source_basis"]
        )
    suggestion["after"] = [{"kind": "dialogue", "speaker": "未登记角色", "text": "甲拿起古剑。"}]
    await asyncio.to_thread(store.write, store.root(tmp_path) / "scene_library.json", library)
    with pytest.raises(ValueError, match="已登记角色"):
        await asyncio.to_thread(
            scene_review.adopt, tmp_path, data, batch["basis"], suggestion["id"], notebook["source_basis"]
        )
    suggestion["after"] = [{"kind": "voiceover", "text": "甲拿起古剑。"}]
    await asyncio.to_thread(store.write, store.root(tmp_path) / "scene_library.json", library)
    await asyncio.to_thread(
        scene_review.adopt, tmp_path, data, batch["basis"], suggestion["id"], notebook["source_basis"]
    )
    saved = next(iter((await asyncio.to_thread(scene_library.catalog, tmp_path))["batches"].values()))
    revised_shot = saved["scenes"][0]["shots"][0]
    assert revised_shot["segments"][0]["utterances"][0]["text"] == "甲拿起古剑。"
    assert revised_shot["production"]["dialogue_sources"] == [{"segment": 0, "utterance": 0, "dialogue_id": None}]


def test_confirm_question_is_individual_versioned_and_preserves_other_production_issues(tmp_path, monkeypatch):
    from lib.novel_workflow import scene_library, store
    from lib.novel_workflow.common import digest

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
    scene_review.confirm_questions(
        tmp_path, {}, "batch", "source", initial, "动作已按原文修复，其他台词仍待核对", 1, "repaired"
    )
    assert batch["review"]["unresolved"] == ["台词缺少说话人"]
    assert batch["review"]["resolved_questions"][0]["questions"] == ["需核对动作"]
    assert batch["scenes"][0]["shots"][0]["segments"][0]["utterances"][0]["speaker"] is None
    with pytest.raises(ValueError, match="仍有待核实问题"):
        scene_review.require_reviewed(batch, batch["scenes"][0]["shots"][0])
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
