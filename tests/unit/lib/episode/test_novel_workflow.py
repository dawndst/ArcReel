import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import chapters, store
from lib.novel_workflow.models import SVTBatch
from lib.novel_workflow.service import generate_svts, read_notes, validate_svt


def project(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source/book.txt").write_text("# 第一章\n甲拿起古剑。\n# 第二章\n乙推开城门。\n")
    data = {"whole_source_files": [{"source_file": "source/book.txt"}]}
    (tmp_path / "project.json").write_text(json.dumps(data))
    preview = chapters.index(tmp_path, data)
    return data, store.initialize(tmp_path, data, preview["source_basis"])


class Reader:
    def __init__(self):
        self.calls = 0

    async def generate(self, request, **kwargs):
        self.calls += 1
        text = request.prompt.split("当前原文：\n", 1)[1].split("\n只输出 JSON", 1)[0]
        quote = "甲拿起古剑。" if "甲拿起古剑。" in text else "乙推开城门。"
        return SimpleNamespace(
            text=json.dumps(
                {
                    "complete": True,
                    "summary": quote,
                    "assets": [{"kind": "character", "name": quote[0], "description": "原文明示行为", "quote": quote}],
                    "changes": [],
                    "events": [
                        {
                            "title": quote,
                            "cause": "未明",
                            "conflict": "未明",
                            "action": quote,
                            "outcome": "动作完成",
                            "quote": quote,
                        }
                    ],
                    "questions": [],
                },
                ensure_ascii=False,
            )
        )


class SVTReader:
    async def generate(self, request, **kwargs):
        events = json.loads(request.prompt.split("本批事件：", 1)[1].split("\n可续接SVT：", 1)[0])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "svts": [
                        {
                            "title": events[0]["title"],
                            "summary": events[0]["action"],
                            "event_ids": [e["id"] for e in events],
                            "mainline_reason": "本集行动",
                            "status": "open",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )


async def test_reading_is_cached_and_partial_reread_preserves_other_notes(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    reader = Reader()
    await read_notes(tmp_path, reader, ids, index["source_basis"])
    assert reader.calls == 2
    await read_notes(tmp_path, reader, [ids[0]], index["source_basis"])
    assert reader.calls == 2
    view = await asyncio.to_thread(store.view, tmp_path, data)
    assert [n["status"] for n in view["notes"]] == ["read", "read"]
    assert view["notes"][0]["reading"]["events"][0]["evidence"]["quote"] == "甲拿起古剑。"


async def test_svt_generation_for_second_scope_preserves_first_scope(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), ids, index["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[0]], index["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[1]], index["source_basis"])
    view = await asyncio.to_thread(store.view, tmp_path, data)
    assert len(view["svts"]) == 2
    assert {svt["title"] for svt in view["svts"]} == {"甲拿起古剑。", "乙推开城门。"}
    assert not view["groups"]


def test_manual_group_preserves_notes_and_can_be_dissolved(tmp_path):
    data, index = project(tmp_path)
    notes = index["notes"]
    group = store.group_notes(tmp_path, data, [n["id"] for n in notes], "改编组合", index["source_basis"])
    assert store.state(tmp_path)["notes"] == notes
    assert group["created_by"] == "human"
    store.dissolve_group(tmp_path, group["id"])
    assert store.state(tmp_path)["groups"] == []
    assert store.state(tmp_path)["notes"] == notes


def test_svt_cannot_invent_events_or_silently_omit_current_events():
    batch = SVTBatch(svts=[], supporting_event_ids=["not-provided"])
    with pytest.raises(ValueError, match="Unknown"):
        validate_svt(batch, {"current"}, {"current"}, set(), set())
    with pytest.raises(ValueError, match="not classified"):
        validate_svt(SVTBatch(), {"current"}, {"current"}, set(), set())
