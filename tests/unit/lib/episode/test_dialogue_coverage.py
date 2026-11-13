from copy import deepcopy

from lib.novel_workflow.dialogue_coverage import report


def material():
    evidence = {"source_file": "novel.txt", "start": 10, "end": 30, "note_id": "note"}
    dialogue = {
        "id": "D1",
        "quote": "『为什么？因为要回家。』",
        "speaker": "甲",
        "value": "决定的理由",
        "evidence": evidence,
    }
    reading = {"basis": "reading", "dialogues": [dialogue], "events": []}
    chunk = {"source_file": "novel.txt", "start": 0, "end": 100}
    batch = {
        "basis": "batch",
        "scenes": [
            {
                "shots": [
                    {
                        "id": "SH-0001",
                        "evidence": evidence,
                        "segments": [{"utterances": [{"text": "为什么？", "speaker": "甲", "origin": "source"}]}],
                    }
                ]
            }
        ],
    }
    return batch, reading, chunk


def test_partial_dialogue_is_not_complete_and_contiguous_segments_cover_whole_quote():
    batch, reading, chunk = material()
    first = report(batch, reading, chunk)
    assert first["counts"] == {"retained": 0, "partial": 1, "unassigned": 0, "omitted": 0}
    batch["scenes"][0]["shots"][0]["segments"].append({"utterances": [{"text": "因为要回家。", "speaker": "甲"}]})
    second = report(batch, reading, chunk)
    assert second["entries"][0]["status"] == "retained"
    assert [p["segment_index"] for p in second["entries"][0]["locations"]] == [0, 1]
    assert first["revision"] != second["revision"]


def test_repeated_words_wrong_source_and_adaptation_do_not_claim_original_retention():
    batch, reading, chunk = material()
    shot = batch["scenes"][0]["shots"][0]
    shot["evidence"] = {"start": 40, "end": 60}
    assert report(batch, reading, chunk)["entries"][0]["status"] == "unassigned"
    shot["evidence"] = reading["dialogues"][0]["evidence"]
    shot["segments"][0]["utterances"][0].update(text=reading["dialogues"][0]["quote"], origin="adaptation")
    assert report(batch, reading, chunk)["entries"][0]["status"] == "unassigned"


def test_duplicate_extraction_merged_but_separate_occurrences_not_counted_twice():
    batch, reading, chunk = material()
    duplicate = deepcopy(reading["dialogues"][0])
    duplicate["id"] = "D2"
    reading["events"] = [{"dialogues": [duplicate]}]
    result = report(batch, reading, chunk)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["source_ids"] == ["D1", "D2"]
    duplicate["evidence"] = {**duplicate["evidence"], "start": 60, "end": 80}
    result = report(batch, reading, chunk)
    assert [e["status"] for e in result["entries"]] == ["partial", "unassigned"]


def test_human_omission_keeps_original_and_reason_and_restore_returns_actual_coverage():
    batch, reading, chunk = material()
    original = deepcopy(reading)
    batch["dialogue_decisions"] = {"D1": {"decision": "omit", "reason": "导演选择用动作交代这一动机"}}
    omitted = report(batch, reading, chunk)
    assert omitted["entries"][0]["status"] == "omitted"
    assert omitted["entries"][0]["quote"] == reading["dialogues"][0]["quote"]
    assert omitted["entries"][0]["reason"] == batch["dialogue_decisions"]["D1"]["reason"]
    batch["dialogue_decisions"]["D1"]["decision"] = "restore"
    restored = report(batch, reading, chunk)
    assert restored["entries"][0]["status"] == "partial"
    assert restored["revision"] != omitted["revision"]
    assert reading == original


async def test_decisions_are_version_checked_and_do_not_delete_note_or_shots(tmp_path):
    import asyncio
    import json
    from types import SimpleNamespace

    import pytest

    from lib.novel_understanding.store import digest
    from lib.novel_workflow import chapters, store, understanding
    from lib.novel_workflow.dialogue_coverage import decide
    from lib.novel_workflow.service import read_notes
    from tests.unit.lib.episode.test_novel_workflow import Reader, project

    def prepare():
        data, _ = project(tmp_path)
        source = tmp_path / "source/book.txt"
        source.write_text(source.read_text().replace("甲拿起古剑。", "甲拿起古剑。甲说：“回家吧。”"))
        return data, store.initialize(tmp_path, data, chapters.index(tmp_path, data)["source_basis"])

    class DialogueReader(Reader):
        async def generate(self, request, **kwargs):
            response = await super().generate(request, **kwargs)
            value = json.loads(response.text)
            if value.get("complete") and not value["events"][0].get("dialogues"):
                value["events"][0]["dialogues"] = [
                    {
                        "speaker": "甲",
                        "quote": "回家吧。",
                        "value": "行动决定",
                        "claim_type": "fact",
                        "source_kind": "narrative",
                        "perspective": "",
                    }
                ]
                return SimpleNamespace(text=json.dumps(value))
            return response

    data, notebook = await asyncio.to_thread(prepare)
    note = notebook["notes"][0]
    await read_notes(tmp_path, DialogueReader(), [note["id"]], notebook["source_basis"])

    def check():
        reading = store.note_result(tmp_path, note)
        chunk = chapters.chunks(tmp_path, data, note)[0]
        batch = {
            "basis": "batch",
            "note_id": note["id"],
            "part": 0,
            "note_order": note["order"],
            "source_start": chunk["start"],
            "source_basis": notebook["source_basis"],
            "note_bases": {note["id"]: reading["basis"]},
            "rule_basis": digest(store.effective_rule(tmp_path, "scenes")),
            "understanding_basis": understanding.production_context(
                tmp_path, [note["id"]], source_offset=chunk["start"]
            )["basis"],
            "scenes": [],
        }
        library = store.root(tmp_path) / "scene_library.json"
        store.write(library, {"batches": {"b": batch}})
        before = deepcopy(reading)
        coverage = report(batch, reading, chunk)
        entry = coverage["entries"][0]
        args = (tmp_path, data, "batch", notebook["source_basis"], coverage["revision"], entry["dialogue_id"])
        decide(*args, "omit", "导演选择将该信息留到后续镜头表现")
        with pytest.raises(ValueError, match="去向已变化"):
            decide(*args, "restore", "决定重新安排到当前镜头之中")
        from lib.novel_workflow.scene_library import catalog

        saved = catalog(tmp_path)["batches"]["b"]
        assert saved["scenes"] == []
        assert report(saved, reading, chunk)["entries"][0]["status"] == "omitted"
        assert store.note_result(tmp_path, note) == before
        assert list((store.root(tmp_path) / "history").glob("dialogue-decision-*.json"))

    await asyncio.to_thread(check)


def test_unique_original_line_matches_even_when_shot_anchor_is_an_adjacent_action():
    batch, reading, chunk = material()
    chunk["text"] = "他转身。『为什么？因为要回家。』她关上门。"
    shot = batch["scenes"][0]["shots"][0]
    shot["evidence"] = {"start": 40, "end": 60}
    shot["segments"][0]["utterances"][0]["text"] = reading["dialogues"][0]["quote"]
    assert report(batch, reading, chunk)["entries"][0]["status"] == "retained"
    chunk["text"] += "后来他又问。『为什么？因为要回家。』"
    assert report(batch, reading, chunk)["entries"][0]["status"] == "unassigned"
