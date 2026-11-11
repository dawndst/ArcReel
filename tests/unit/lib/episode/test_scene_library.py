import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import grouping, scene_library, store
from lib.novel_workflow.scene_models import SceneBatch
from lib.novel_workflow.service import generate_svts, read_notes
from tests.unit.lib.episode.test_novel_workflow import Reader, SVTReader, project


def scene_output(quote="甲拿起古剑。"):
    return {
        "scenes": [
            {
                "title": "取剑",
                "location": "未明",
                "time": "未明",
                "purpose": "行动",
                "shots": [
                    {
                        "title": "取剑镜头",
                        "quote": quote,
                        "segments": [
                            {
                                "duration_seconds": 8,
                                "scene_description": "甲拿起古剑",
                                "characters_in_scene": ["甲"],
                                "scenes": [],
                                "props": [],
                                "utterances": [],
                            }
                        ],
                    }
                ],
            }
        ],
        "skipped_reason": "",
    }


@pytest.mark.parametrize("truncate", [False, True])
async def test_generation_has_no_episode_side_effect_and_cache_preserves_selection_ids(tmp_path, truncate):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
    store.write(tmp_path / "project.json", data)
    note_id = notebook["notes"][0]["id"]
    await read_notes(tmp_path, Reader(), [note_id], notebook["source_basis"])

    await generate_svts(tmp_path, SVTReader(), [note_id], notebook["source_basis"])

    class Generator:
        calls = 0
        max_output_tokens = 48000

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
                return SimpleNamespace(text=json.dumps({"revisions": [], "unresolved": []}))
            self.calls += 1
            assert "乙推开城门" not in request.prompt
            if truncate and self.calls == 1:
                from lib.backends.text_backends.base import TextOutputTruncatedError

                raise TextOutputTruncatedError(provider="test", model="test", output_tokens=request.max_output_tokens)
            return SimpleNamespace(text=json.dumps(scene_output(), ensure_ascii=False))

    generator = Generator()
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    original = scene_library.catalog(tmp_path)
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    assert generator.calls == 1 + int(truncate)
    assert scene_library.catalog(tmp_path) == original
    assert json.loads((tmp_path / "project.json").read_text())["episodes"] == []
    shot = next(iter(original["batches"].values()))["scenes"][0]["shots"][0]
    assert shot["evidence"]["note_id"] == note_id
    from lib.novel_understanding.store import digest
    from lib.novel_workflow.shot_production import ShotDecisions, update

    decisions = ShotDecisions.model_validate(
        {key: shot["production"][key] for key in ("shot_id", "event_ids", "moment_ids", "design")}
    )
    decisions.design.purpose = "核对后保留主角行动"
    project_data = json.loads((tmp_path / "project.json").read_text())
    await asyncio.to_thread(
        update, tmp_path, project_data, shot["id"], notebook["source_basis"], digest(shot), decisions
    )
    with pytest.raises(ValueError, match="已变化"):
        await asyncio.to_thread(
            update, tmp_path, project_data, shot["id"], notebook["source_basis"], digest(shot), decisions
        )
    assert (tmp_path / shot["evidence"]["source_file"]).read_text()[
        shot["evidence"]["start"] : shot["evidence"]["end"]
    ] == shot["quote"]


def test_scene_validation_rejects_invented_citation_and_unsupported_duration():
    value = SceneBatch.model_validate(scene_output())
    assets = {"character": {"甲"}, "scene": set(), "prop": set()}
    with pytest.raises(ValueError, match="逐字摘录"):
        scene_library.ground(value, {"text": "不存在的原文"}, assets, [8])
    with pytest.raises(ValueError, match="时长"):
        scene_library.ground(value, {"text": "甲拿起古剑。"}, assets, [12])


async def test_group_synopsis_does_not_make_episode_or_delete_notes(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in notebook["notes"]]
    await read_notes(tmp_path, Reader(), ids, notebook["source_basis"])
    group = store.group_notes(tmp_path, data, ids, "仅留档资料", notebook["source_basis"])
    grouping.set_usage(tmp_path, data, group["id"], "reference", notebook["source_basis"])
    await grouping.summarize(tmp_path, Reader(), ids, notebook["source_basis"], group["id"])
    saved = store.state(tmp_path)
    assert saved["groups"][0]["synopsis"]["summary"]
    assert saved["groups"][0]["usage"] == "reference"
    assert len(saved["notes"]) == 2
    assert not json.loads((tmp_path / "project.json").read_text()).get("episodes")
    with pytest.raises(ValueError, match="仅留档"):
        await scene_library.generate(tmp_path, Reader(), ids, notebook["source_basis"], durations=[8])


async def test_changed_svt_assignment_blocks_scenes_until_reextracted(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
    await asyncio.to_thread(store.write, tmp_path / "project.json", data)
    note_id = notebook["notes"][0]["id"]
    await read_notes(tmp_path, Reader(), [note_id], notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [note_id], notebook["source_basis"])
    file = store.root(tmp_path) / "svts.json"
    value = await asyncio.to_thread(lambda: json.loads(file.read_text()))
    value["svts"][0]["breakdown_status"] = "needs_review"
    await asyncio.to_thread(store.write, file, value)
    with pytest.raises(ValueError, match="主归属 SVT 已调整"):
        await scene_library.generate(tmp_path, Reader(), [note_id], notebook["source_basis"], durations=[8])
    reading = await asyncio.to_thread(store.note_result, tmp_path, notebook["notes"][0])
    assert await asyncio.to_thread(scene_library.svt_event_tags, tmp_path, note_id, reading) == []


def test_scene_assets_do_not_leak_later_state_from_same_note():
    chunk = {"source_file": "book.txt", "note_id": "n1", "start": 100, "end": 200, "text": "阳子走进学校。"}

    def asset(start, end):
        return {
            "raw_name": "阳子",
            "evidence": {"source_file": "book.txt", "note_id": "n1", "start": start, "end": end},
        }

    assert scene_library.asset_available(asset(10, 30), chunk)
    assert scene_library.asset_available(asset(110, 130), chunk)
    assert not scene_library.asset_available(asset(250, 270), chunk)


def test_missing_speaker_preserved_in_library_but_blocks_production_until_confirmed():
    from lib.novel_workflow.director import content_from_selection

    raw = scene_output("“不愧是班长。”")
    segment = raw["scenes"][0]["shots"][0]["segments"][0]
    segment["utterances"] = [{"kind": "dialogue", "speaker": " ", "text": "不愧是班长。"}]
    result = scene_library.ground(
        SceneBatch.model_validate(raw),
        {"text": "“不愧是班长。”"},
        {"character": {"甲"}, "scene": set(), "prop": set()},
        [8],
    )
    scene = {**result["scenes"][0], "id": "SCN-1"}
    shot = {**scene["shots"][0], "id": "SH-1", "evidence": {"quote": "“不愧是班长。”"}}
    assert shot["segments"][0]["utterances"][0]["speaker"] is None
    assert shot["segments"][0]["utterances"][0]["kind"] == "dialogue"
    with pytest.raises(ValueError, match="确认说话人"):
        content_from_selection([({}, scene, shot)], 1, "验收")
    shot["segments"][0]["utterances"][0]["speaker"] = "甲"
    script, mapping = content_from_selection([({}, scene, shot)], 1, "验收")
    assert script["scenes"][0]["utterances"][0]["text"] == "不愧是班长。"
    assert mapping[0]["library_shot_id"] == "SH-1"


def test_director_keeps_selected_order_scene_boundaries_and_segment_numbers():
    from copy import deepcopy

    from lib.novel_workflow.director import content_from_selection

    scene = {**scene_output()["scenes"][0], "id": "SCN-9"}
    shot = {**scene["shots"][0], "id": "SH-8", "evidence": {"quote": "甲拿起古剑。"}}
    shot["segments"].append(deepcopy(shot["segments"][0]))
    other = {**deepcopy(shot), "id": "SH-2", "segments": [deepcopy(shot["segments"][0])]}
    selected = [({}, scene, shot), ({}, {**scene, "id": "SCN-2"}, other)]
    content, mapping = content_from_selection(selected, 3, "导演选择")
    assert [(s["scene_number"], s["shot_number"], s["segment_number"]) for s in content["scenes"]] == [
        (1, 1, 1),
        (1, 1, 2),
        (2, 1, None),
    ]
    assert [m["library_shot_id"] for m in mapping] == ["SH-8", "SH-8", "SH-2"]
    assert [s["scene_id"] for s in content["scenes"]] == ["E3S001", "E3S002", "E3S003"]


def test_short_logical_shot_merges_segments_without_losing_actions_or_dialogue():
    from copy import deepcopy

    raw = scene_output()
    segments = raw["scenes"][0]["shots"][0]["segments"]
    segments[0].update(duration_seconds=4, utterances=[{"kind": "dialogue", "speaker": "甲", "text": "走吧。"}])
    segments.append(
        {
            **deepcopy(segments[0]),
            "scene_description": "甲转身",
            "utterances": [{"kind": "dialogue", "speaker": "甲", "text": "快点。"}],
        }
    )
    result = scene_library.ground(
        SceneBatch.model_validate(raw),
        {"text": "甲拿起古剑。走吧。快点。"},
        {"character": {"甲"}, "scene": set(), "prop": set()},
        [4, 8],
    )
    merged = result["scenes"][0]["shots"][0]["segments"]
    assert len(merged) == 1
    assert merged[0]["duration_seconds"] == 8
    assert merged[0]["scene_description"] == "甲拿起古剑\n甲转身"
    assert [u["text"] for u in merged[0]["utterances"]] == ["走吧。", "快点。"]
