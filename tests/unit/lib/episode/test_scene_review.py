import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import scene_review
from tests.unit.lib.episode.test_scene_library import scene_output


async def test_semantic_review_proposes_local_changes_without_editing_or_accepting_fabricated_evidence(tmp_path):
    rule = tmp_path / "novel_workflow/rules/scene_review.md"
    await asyncio.to_thread(rule.parent.mkdir, parents=True)
    await asyncio.to_thread(rule.write_text, "本项目自定义场镜审核规则", encoding="utf-8")
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
            assert "本项目自定义场镜审核规则" in request.prompt
            return SimpleNamespace(text=json.dumps({"revisions": [suggestion], "unresolved": []}))

    review = await scene_review.review(tmp_path, Generator(), scenes, "甲拿起古剑。")
    assert review["revisions"][0]["applied"] is False
    assert json.dumps(scenes) == before
    suggestion["source_quote"] = "甲挥剑杀人。"
    rejected = await scene_review.review(tmp_path, Generator(), scenes, "甲拿起古剑。")
    assert not rejected["revisions"]
    assert "连续逐字摘录" in rejected["unresolved"][0]


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


async def test_review_isolates_invalid_suggestions_without_retrying_and_blocks_assembly(tmp_path):
    scenes = scene_output()["scenes"]
    valid = {
        "scene_index": 0,
        "shot_index": 0,
        "segment_index": None,
        "field": "title",
        "before": "取剑镜头",
        "after": "拿起古剑",
        "source_quote": "甲拿起古剑。",
        "reason": "贴合原文",
    }
    suggestions = [
        valid,
        dict(valid),
        dict(valid, after=valid["before"]),
        dict(valid, shot_index=99),
        dict(valid, before="错误标题"),
        dict(valid, source_quote="甲拿起。后来古剑。"),
    ]
    calls = 0

    class Generator:
        async def generate(self, request, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(text=json.dumps({"revisions": suggestions, "unresolved": ["原有疑点"]}))

    result = await scene_review.review(tmp_path, Generator(), scenes, "甲拿起古剑。后来离开。")
    assert calls == 1
    assert len(result["revisions"]) == 1
    assert result["revisions"][0]["after"] == "拿起古剑"
    assert len(result["unresolved"]) == 4
    assert any("第1场、第100镜的标题" in question and "位置索引" in question for question in result["unresolved"])
    assert any("修订前文字" in question for question in result["unresolved"])
    assert any("连续逐字摘录" in question for question in result["unresolved"])
    with pytest.raises(ValueError, match="仍有待核实问题"):
        scene_review.require_reviewed({"review": result, "scenes": scenes}, scenes[0]["shots"][0])


def test_conflicting_suggestions_cannot_be_adopted_but_other_fields_survive():
    scenes = scene_output()["scenes"]
    valid = {
        "scene_index": 0,
        "shot_index": 0,
        "segment_index": None,
        "field": "title",
        "before": "取剑镜头",
        "after": "拿起古剑",
        "source_quote": "甲拿起古剑。",
        "reason": "贴合原文",
    }
    segment = scenes[0]["shots"][0]["segments"][0]
    other = dict(
        valid, segment_index=0, field="scene_description", before=segment["scene_description"], after="甲拿起古剑。"
    )
    value = scene_review.SceneReview.model_validate({"revisions": [valid, dict(valid, after="拿剑"), other]})
    result = scene_review.validate_review(value, scenes, "甲拿起古剑。")
    assert len(result["revisions"]) == 1
    assert result["revisions"][0]["field"] == "scene_description"
    assert "同一字段" in result["unresolved"][0]


@pytest.mark.parametrize("field", ["start_frame", "end_frame", "utterances"])
def test_review_supports_local_frame_and_whole_utterance_list_revisions(field):
    scenes = scene_output()["scenes"]
    revision = {
        "scene_index": 0,
        "shot_index": 0,
        "segment_index": 0,
        "field": field,
        "before": [] if field == "utterances" else "",
        "after": [{"kind": "voiceover", "text": "甲拿起古剑。"}] if field == "utterances" else "甲手持古剑。",
        "source_quote": "甲拿起古剑。",
        "reason": "按原文补充当前片段",
    }
    review = scene_review.validate_review(
        scene_review.SceneReview.model_validate({"revisions": [revision]}), scenes, "甲拿起古剑。"
    )
    assert review["revisions"][0]["field"] == field
    assert not review["unresolved"]
    revision["segment_index"] = None
    rejected = scene_review.validate_review(
        scene_review.SceneReview.model_validate({"revisions": [revision]}), scenes, "甲拿起古剑。"
    )
    assert not rejected["revisions"]
