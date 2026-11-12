import pytest

from lib.infra.json_io import load_json
from lib.novel_workflow import assets, store
from lib.novel_workflow.source_roles import register
from tests.unit.lib.episode.test_note_assets import save_reading
from tests.unit.lib.episode.test_novel_workflow import project


def test_unnamed_role_reuses_code_and_keeps_note_evidence_after_synchronization(tmp_path):
    data, book = project(tmp_path)
    first, second = book["notes"]
    evidence = {
        "note_id": first["id"],
        "source_file": "source/book.txt",
        "start": 6,
        "end": 12,
        "quote": "甲拿起古剑。",
    }
    name = register(data, first, first["basis"], "持剑来客", evidence)
    original = data["characters"][name]["asset_code"]
    assert register(data, first, first["basis"], "持剑来客", evidence) == name
    assert len(data["characters"]) == 1
    assert data["characters"][name]["asset_code"] == original
    # Identical role labels in a different original chapter do not establish shared identity.
    other = register(data, second, second["basis"], "持剑来客", {**evidence, "note_id": second["id"]})
    assert other != name
    for note in book["notes"]:
        save_reading(tmp_path, note, [])
    store.write(tmp_path / "project.json", data)
    assets.synchronize(tmp_path)
    saved = load_json(tmp_path / "project.json")
    assert saved["characters"][name]["first_note"]["id"] == first["id"]
    annotated = assets.annotate(saved, {"basis": first["basis"], "assets": []})
    assert len(annotated["assets"]) == 1
    assert annotated["assets"][0]["asset_code"] == original
    assert annotated["assets"][0]["evidence"] == evidence
    from lib.novel_workflow.memory import ledger

    remembered = ledger(tmp_path, book, through=first["order"])
    assert len(remembered["characters"]) == 1
    assert remembered["characters"][0]["name"] == "持剑来客"
    # Manual rename keeps the identity and a later adoption reuses its current display name.
    saved["characters"]["人工新名"] = saved["characters"].pop(name)
    assert register(saved, first, first["basis"], "持剑来客", evidence) == "人工新名"
    del saved["characters"]["人工新名"]
    with pytest.raises(ValueError, match="已移除"):
        register(saved, first, first["basis"], "持剑来客", evidence)


def test_register_and_attribute_is_versioned_and_reuses_one_asset(tmp_path):
    from lib.novel_understanding.store import digest
    from lib.novel_workflow import chapters, scene_library, settings
    from lib.novel_workflow.shot_production import planning_inputs

    (tmp_path / "source").mkdir()
    text = "# 第一章\n一个女生跑来说：“借书。”又说：“谢谢。”\n"
    (tmp_path / "source/book.txt").write_text(text)
    data = {"whole_source_files": [{"source_file": "source/book.txt"}]}
    store.write(tmp_path / "project.json", data)
    settings.update(tmp_path, {"understanding_enabled": False})
    book = store.initialize(tmp_path, data, chapters.index(tmp_path, data)["source_basis"])
    note = book["notes"][0]
    save_reading(tmp_path, note, [])
    quote = "一个女生跑来说：“借书。”又说：“谢谢。”"
    start = text.index(quote)
    ev = {
        "note_id": note["id"],
        "source_file": "source/book.txt",
        "start": start,
        "end": start + len(quote),
        "quote": quote,
    }
    shot = {
        "id": "SH-1",
        "title": "借书",
        "evidence": ev,
        "segments": [
            {
                "duration_seconds": 8,
                "scene_description": "女生向同学借书",
                "characters_in_scene": [],
                "scenes": [],
                "props": [],
                "utterances": [
                    {"kind": "dialogue", "speaker": None, "text": "借书。"},
                    {"kind": "dialogue", "speaker": None, "text": "谢谢。"},
                ],
            }
        ],
        "production": {"assets": []},
        "speaker_suggestions": {
            "items": [
                {
                    "segment_index": 0,
                    "utterance_index": i,
                    "speaker": None,
                    "proposed_role": "借书的女生",
                    "source_quote": quote,
                    "reason": "两句均明确是该女生说的",
                }
                for i in (0, 1)
            ]
        },
    }
    reading = store.valid_readings(tmp_path, book)[note["id"]]
    ctx = {"svt_id": None, "events": [], "moments": []}
    rules = store.rule(tmp_path, "shot_production")
    batch = {
        "basis": "batch",
        "note_id": note["id"],
        "note_order": 1,
        "part": 0,
        "source_basis": book["source_basis"],
        "rule_basis": digest(store.rule(tmp_path, "scenes")),
        "note_bases": {note["id"]: reading["basis"]},
        "understanding_basis": digest([]),
        "scenes": [{"id": "SCN-1", "shots": [shot]}],
        "production_context": ctx,
        "production_basis": planning_inputs(ctx, rules, {"SH-1": shot}, data, reading)[2],
    }
    file = store.root(tmp_path) / "scene_library.json"
    store.write(file, {"batches": {"n:0": batch}})
    original_revision = digest(shot)
    result = scene_library.attribute_dialogue(
        tmp_path, data, "SH-1", 0, 0, "借书的女生", book["source_basis"], original_revision, True
    )
    name = result["speaker"]
    assert name == "借书的女生（未具名）"
    with pytest.raises(ValueError, match="已变化"):
        scene_library.attribute_dialogue(
            tmp_path, data, "SH-1", 0, 1, "借书的女生", book["source_basis"], original_revision, True
        )
    current = load_json(file)["batches"]["n:0"]["scenes"][0]["shots"][0]
    scene_library.attribute_dialogue(
        tmp_path, data, "SH-1", 0, 1, "借书的女生", book["source_basis"], digest(current), True
    )
    saved = load_json(tmp_path / "project.json")
    assert list(saved["characters"]) == [name]
    current = load_json(file)["batches"]["n:0"]["scenes"][0]["shots"][0]
    assert [u["speaker"] for u in current["segments"][0]["utterances"]] == [name, name]
    assert [u["text"] for u in current["segments"][0]["utterances"]] == ["借书。", "谢谢。"]
    assert current["attribution_history"][0]["ai_suggestion"]["proposed_role"] == "借书的女生"
    assert not scene_library.view(tmp_path, book, {note["id"]: reading})[0]["production_stale"]
