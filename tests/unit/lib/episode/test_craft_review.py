import asyncio
import json
from copy import deepcopy

import pytest

from lib.novel_workflow import craft_review as craft
from lib.novel_workflow import scene_source, store


def fixture(tmp_path, monkeypatch):
    text = "甲穿整洁长袍，拿起书。乙稍后走进来。"
    ev = {"note_id": "n", "source_file": "book.txt", "start": 0, "end": 11, "quote": text[:11]}
    chunk = {"note_id": "n", "source_file": "book.txt", "start": 0, "end": len(text), "text": text}
    shot = {
        "id": "SH-1",
        "title": "拿书",
        "evidence": ev,
        "segments": [
            {
                "duration_seconds": 5,
                "scene_description": "甲拿起书",
                "characters_in_scene": ["甲"],
                "scenes": [],
                "props": [],
                "utterances": [],
            }
        ],
    }
    batch = {
        "basis": "b",
        "source_basis": "src",
        "note_id": "n",
        "note_bases": {"n": "r"},
        "source_start": 0,
        "part": 0,
        "scenes": [{"id": "SCN-1", "title": "拿书", "location": "室内", "time": "日", "shots": [shot]}],
    }
    reading = {
        "basis": "r",
        "events": [
            {
                "id": "E1",
                "title": "拿书",
                "action": "甲拿起书",
                "cause": "",
                "outcome": "",
                "conflict": "",
                "evidence": ev,
                "claim_type": "fact",
                "source_kind": "narrative",
            }
        ],
    }
    project = {"characters": {"甲": {"asset_id": "C1", "description": "穿破旧衣服"}}}
    notebook = {"source_basis": "src", "notes": [{"id": "n", "title": "第一章"}], "groups": []}
    monkeypatch.setattr(scene_source.chapters, "index", lambda *a: {"source_basis": "src"})
    monkeypatch.setattr(scene_source.chapters, "chunks", lambda *a: [deepcopy(chunk)])
    monkeypatch.setattr(store, "require_current", lambda *a: notebook)
    store.write(tmp_path / "project.json", project)
    store.write(store.root(tmp_path) / "index.json", notebook)
    store.write(store.root(tmp_path) / "notes" / "n" / "r.json", reading)
    store.write(store.root(tmp_path) / "scene_library.json", {"batches": {"slot": batch}})
    return project, batch, reading, chunk


def model_result():
    return craft.CraftReview.model_validate(
        {
            "coverage": [{"item_id": "E1:action", "status": "covered", "shot_ids": ["SH-1"], "reason": "动作可见"}],
            "appearance": [
                {
                    "shot_id": "SH-1",
                    "reference": "甲",
                    "status": "conflict",
                    "source_quote": "甲穿整洁长袍",
                    "reason": "原文整洁，资产破旧",
                    "suggestion": "本镜保持整洁长袍，不增加破损",
                }
            ],
            "openings": [
                {
                    "scene_id": "SCN-1",
                    "state": {"present": "甲", "positions": "桌旁（设计建议）", "props": "书", "entering": "乙未入场"},
                    "source_quote": "甲穿整洁长袍",
                    "reason": "不把后来入场者放在开场",
                }
            ],
        }
    )


def test_stale_rules_do_not_block_source_but_changed_book_does(tmp_path, monkeypatch):
    project, batch, _, chunk = fixture(tmp_path, monkeypatch)
    # No valid generation hashes: browsing must still work.
    assert scene_source.batch_source(tmp_path, project, "b")["text"] == chunk["text"]
    monkeypatch.setattr(scene_source.chapters, "index", lambda *a: {"source_basis": "different"})
    with pytest.raises(ValueError, match="替换"):
        scene_source.batch_source(tmp_path, project, "b")
    batch["source_snapshot"] = scene_source.snapshot(chunk)
    assert scene_source.source_chunk(tmp_path, project, batch) == chunk
    batch["source_snapshot"]["chunk"]["text"] = "篡改"
    with pytest.raises(ValueError, match="快照校验"):
        scene_source.source_chunk(tmp_path, project, batch)


def test_wrong_offsets_do_not_silently_highlight_other_text(tmp_path, monkeypatch):
    project, batch, _, _ = fixture(tmp_path, monkeypatch)
    batch["scenes"][0]["shots"][0]["evidence"]["start"] = 2
    with pytest.raises(ValueError, match="位置"):
        scene_source.source_chunk(tmp_path, project, batch)


def test_review_rejects_missing_actions_unknown_shots_and_future_appearance(tmp_path, monkeypatch):
    project, batch, reading, chunk = fixture(tmp_path, monkeypatch)
    material = craft.inputs(tmp_path, project, batch, reading, chunk)
    value = model_result()
    assert craft.validate(value, material)["appearance"][0]["current_description"] == "穿破旧衣服"
    value.coverage = []
    with pytest.raises(ValueError, match="逐项"):
        craft.validate(value, material)
    value = model_result()
    value.coverage[0].shot_ids = ["SH-other"]
    with pytest.raises(ValueError, match="当前片段"):
        craft.validate(value, material)
    value = model_result()
    value.appearance[0].source_quote = "乙稍后走进来"
    with pytest.raises(ValueError, match="截至"):
        craft.validate(value, material)


def test_decisions_preserve_note_and_reject_races(tmp_path, monkeypatch):
    project, batch, reading, _ = fixture(tmp_path, monkeypatch)
    current = craft.view(tmp_path, project, batch)
    req = craft.CraftDecision(
        source_basis="src",
        revision=current["revision"],
        kind="coverage",
        item_id="E1:action",
        decision="omit",
        reason="编导决定此动作省略",
    )
    craft.decide(tmp_path, project, "b", req)
    _, saved = craft.find_batch(tmp_path, "b")
    assert craft.view(tmp_path, project, saved)["items"][0]["decision"]["decision"] == "omit"
    assert craft.saved_reading(tmp_path, saved) == reading
    with pytest.raises(ValueError, match="已变化"):
        craft.decide(tmp_path, project, "b", req)
    req.revision = craft.view(tmp_path, project, saved)["revision"]
    req.decision = "restore"
    craft.decide(tmp_path, project, "b", req)
    assert not craft.find_batch(tmp_path, "b")[1]["craft_decisions"]


def test_appearance_is_local_and_opening_survives_handoff(tmp_path, monkeypatch):
    project, batch, _, _ = fixture(tmp_path, monkeypatch)
    current = craft.view(tmp_path, project, batch)
    batch["craft_review"] = {
        **craft.validate(model_result(), craft.inputs(tmp_path, project, batch)),
        "basis": current["basis"],
        "created_at": "now",
    }
    store.write(store.root(tmp_path) / "scene_library.json", {"batches": {"slot": batch}})
    req = craft.CraftDecision(
        source_basis="src",
        revision=craft.view(tmp_path, project, batch)["revision"],
        kind="appearance",
        item_id="SH-1:甲",
        decision="accept",
        reason="对照本镜原文确认",
        text="长袍整洁，保持人形",
    )
    craft.decide(tmp_path, project, "b", req)
    _, saved = craft.find_batch(tmp_path, "b")
    assert "长袍整洁" in craft.appearance_text(saved["scenes"][0]["shots"][0])
    assert project == json.loads((tmp_path / "project.json").read_text())
    assert not craft.view(tmp_path, project, saved)["stale"]
    req = craft.CraftDecision(
        source_basis="src",
        revision=craft.view(tmp_path, project, saved)["revision"],
        kind="opening",
        item_id="SCN-1",
        decision="save",
        reason="编导确认开场仅有甲",
        opening=craft.OpeningState(present="甲", entering="乙稍后入场"),
    )
    craft.decide(tmp_path, project, "b", req)
    _, saved = craft.find_batch(tmp_path, "b")
    assert "乙稍后入场" in craft.opening_text(saved["scenes"][0])
    # Changing an actual asset invalidates an old review; declarations do not hide it.
    project["characters"]["甲"]["description"] = "新衣服"
    assert craft.view(tmp_path, project, saved)["stale"]


def test_input_filters_future_observations_and_retains_uncertainty(tmp_path, monkeypatch):
    project, batch, reading, chunk = fixture(tmp_path, monkeypatch)
    reading["assets"] = [{"description": "后文兽形", "evidence": {"source_file": "book.txt", "end": 100}}]
    reading["events"][0]["claim_type"] = "vision"
    material = craft.inputs(tmp_path, project, batch, reading, chunk)
    assert material["observations"]["SH-1"] == []
    assert material["items"][0]["claim_type"] == "vision"


@pytest.mark.asyncio
async def test_review_uses_one_fragment_then_cached_result(tmp_path, monkeypatch):
    from lib.novel_workflow import service

    project, _batch, _, chunk = await asyncio.to_thread(fixture, tmp_path, monkeypatch)
    prompts = []

    async def fake_ask(path, generator, schema, prompt, validator, **kwargs):
        prompts.append(prompt)
        return validator(model_result())

    monkeypatch.setattr(service, "ask", fake_ask)
    await craft.generate(tmp_path, object(), ["n"], "src", ["SH-1"])
    await craft.generate(tmp_path, object(), ["n"], "src", ["SH-1"])
    assert len(prompts) == 1
    assert chunk["text"] in prompts[0]
    _, saved = await asyncio.to_thread(craft.find_batch, tmp_path, "b")
    assert (await asyncio.to_thread(craft.view, tmp_path, project, saved))["review"]["appearance"][0][
        "status"
    ] == "conflict"
