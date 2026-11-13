import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow.service import read_notes
from lib.novel_workflow.svt_summary import finalize
from tests.unit.lib.episode.test_novel_workflow import Reader, project


async def test_cumulative_svt_summary_covers_early_and_late_notes_without_changing_ownership(tmp_path):
    _, book = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in book["notes"]]
    await read_notes(tmp_path, Reader(), ids, book["source_basis"])
    original = {
        "id": "s1",
        "title": "乙开门",
        "summary": "仅末批",
        "mainline_reason": "寻找出路",
        "note_ids": ids,
        "event_ids": ["e1", "e2"],
        "climaxes": [{"scene": "取剑"}],
    }
    saved = copy.deepcopy(original)

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            material = json.loads(request.prompt.split("SVT累计概况材料：", 1)[1].split("\n只输出 JSON", 1)[0])
            assert len(material["sources"]) == 2
            assert material["sources"][0]["note_ids"] == [ids[0]]
            assert material["sources"][1]["note_ids"] == [ids[1]]
            assert material["opening_context"] == material["sources"][0]["summary"].split("。", 1)[0] + "。"
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "title": "取剑与开门寻找出路",
                        "summary": "甲先拿起古剑，乙再推开城门，出路尚未确认。",
                        "mainline_reason": "同一行动的起因和后续",
                        "note_ids": ids,
                    }
                )
            )

    generator = Generator()
    result = (await finalize(tmp_path, generator, [original], book))[0]
    again = (await finalize(tmp_path, generator, [original], book))[0]
    assert generator.calls == 1
    assert result == again
    assert result["summary_mode"] == "cumulative"
    assert result["summary"].startswith("甲先拿起古剑")
    assert result["note_ids"] == ids
    assert result["event_ids"] == saved["event_ids"]
    assert result["climaxes"] == saved["climaxes"]
    assert original == saved
    assert set(result["summary_note_bases"]) == set(ids)


async def test_cumulative_summary_rejects_last_note_only_result(tmp_path):
    _, book = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in book["notes"]]
    await read_notes(tmp_path, Reader(), ids, book["source_basis"])

    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "title": "只保留末章",
                        "summary": "乙推开城门。",
                        "mainline_reason": "局部进展",
                        "note_ids": ids[-1:],
                    }
                )
            )

    with pytest.raises(ValueError, match="不能只保留末章"):
        await finalize(
            tmp_path,
            Generator(),
            [
                {
                    "id": "s1",
                    "title": "出路",
                    "summary": "末章",
                    "mainline_reason": "寻找出路",
                    "note_ids": ids,
                }
            ],
            book,
        )


async def test_single_note_svt_reuses_complete_validated_overview_without_model_call(tmp_path):
    from lib.novel_workflow import store

    _, book = await asyncio.to_thread(project, tmp_path)
    note = book["notes"][0]
    await read_notes(tmp_path, Reader(), [note["id"]], book["source_basis"])
    reading = await asyncio.to_thread(store.note_result, tmp_path, note)
    original = {"id": "s1", "title": "取剑", "summary": "遗漏开头", "mainline_reason": "行动", "note_ids": [note["id"]]}

    class NoCalls:
        async def generate(self, *args, **kwargs):
            raise AssertionError("single-Note overview must not be generated again")

    result = (await finalize(tmp_path, NoCalls(), [original], book))[0]
    assert result["summary"] == reading["overview"]["summary"]
    assert result["summary_mode"] == "chapter_overview"
    assert result["title"] == original["title"]
