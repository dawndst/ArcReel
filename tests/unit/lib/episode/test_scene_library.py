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


async def test_generation_has_no_episode_side_effect_and_cache_preserves_selection_ids(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
    store.write(tmp_path / "project.json", data)
    note_id = notebook["notes"][0]["id"]
    await read_notes(tmp_path, Reader(), [note_id], notebook["source_basis"])

    await generate_svts(tmp_path, SVTReader(), [note_id], notebook["source_basis"])

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            assert "乙推开城门" not in request.prompt
            return SimpleNamespace(text=json.dumps(scene_output(), ensure_ascii=False))

    generator = Generator()
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    original = scene_library.catalog(tmp_path)
    await scene_library.generate(tmp_path, generator, [note_id], notebook["source_basis"], durations=[8])
    assert generator.calls == 1
    assert scene_library.catalog(tmp_path) == original
    assert json.loads((tmp_path / "project.json").read_text())["episodes"] == []
    shot = next(iter(original["batches"].values()))["scenes"][0]["shots"][0]
    assert shot["evidence"]["note_id"] == note_id
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
