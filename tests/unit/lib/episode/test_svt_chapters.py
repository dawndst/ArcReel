import asyncio
import json
from types import SimpleNamespace

from lib.novel_workflow import store
from lib.novel_workflow.service import read_notes
from lib.novel_workflow.svt_chapters import generate
from tests.unit.lib.episode.test_novel_workflow import Reader, project


async def test_chapter_story_uses_only_its_note_repairs_foreign_event_and_reuses_cache(tmp_path):
    _, book = await asyncio.to_thread(project, tmp_path)
    note = book["notes"][0]
    await read_notes(tmp_path, Reader(), [note["id"]], book["source_basis"])
    reading = await asyncio.to_thread(store.note_result, tmp_path, note)

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            material = json.loads(request.prompt.split("本章SVT材料：", 1)[1].split("\n只输出 JSON", 1)[0])
            assert material["note_id"] == note["id"]
            assert [e["title"] for e in material["events"]] == ["甲拿起古剑。"]
            assert "乙推开城门" not in request.prompt
            return SimpleNamespace(text=json.dumps({
                "note_id": note["id"], "title": "甲取剑准备行动", "summary": "甲拿起古剑，准备行动。",
                "advancement": "古剑由静置变为被甲拿起。",
                "event_ids": ["foreign-event"] if self.calls == 1 else [reading["events"][0]["id"]],
            }))

    generator = Generator()
    story = await generate(tmp_path, generator, note, reading)
    assert story["event_ids"] == [reading["events"][0]["id"]]
    assert story["title"] == "甲取剑准备行动"
    assert story["reading_basis"] == reading["basis"]
    assert await generate(tmp_path, generator, note, reading) == story
    assert generator.calls == 2
