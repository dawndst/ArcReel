import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import scene_review


async def test_review_finishes_text_corrections_without_manual_version_choice(tmp_path):
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
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
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

    generator = Generator()
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    batch = next(iter((await asyncio.to_thread(scene_library.catalog, tmp_path))["batches"].values()))
    shot = batch["scenes"][0]["shots"][0]
    assert shot["title"] == "拿起古剑"
    assert batch["review"]["revisions"][0]["applied_by"] == "automatic_review"
    scene_review.require_reviewed(batch, shot)
    assert scene_review.complete_corrections(batch) == 0
    calls = generator.calls
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    assert generator.calls == calls
    from copy import deepcopy

    original = deepcopy(shot)
    batch["review"]["revisions"].append(
        {
            "id": "unsafe-dialogue",
            "scene_index": 0,
            "shot_index": 0,
            "segment_index": 0,
            "field": "utterances",
            "before": [],
            "after": [{"kind": "voiceover", "text": "伪造台词"}],
            "applied": False,
        }
    )
    with pytest.raises(ValueError, match="仅允许"):
        scene_review.complete_corrections(batch)
    assert shot == original


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
