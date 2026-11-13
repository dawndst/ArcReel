import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import condensation as c


def test_complete_unit_coverage_protects_evidence_and_keeps_uncertain_verbatim():
    chunk = {"text": "甲开门。", "start": 10, "end": 14, "source_file": "book"}
    source = c.units(chunk)
    anchor = [{"start": 10, "end": 14}]
    omitted = c.Edition(passages=[c.Passage(unit=0, treatment="omit", text="", reason="重复")])
    with pytest.raises(ValueError, match="不能省略"):
        c.validate(omitted, source, anchor)
    uncertain = c.Edition(
        passages=[c.Passage(unit=0, treatment="uncertain", text="模型错误改写", reason="伏笔价值未明")]
    )
    assert c.validate(uncertain, source, anchor)[0]["text"] == chunk["text"]
    with pytest.raises(ValueError, match="漏段"):
        c.validate(c.Edition(passages=[uncertain.passages[0], uncertain.passages[0]]), source, [])


def test_chunk_projection_cannot_reveal_later_material():
    chunk = {"text": "甲开门。", "start": 0, "end": 4, "source_file": "book"}
    edition = {
        "parts": [
            {**chunk, "passages": [{"text": "甲开门"}]},
            {"source_file": "book", "start": 4, "end": 9, "passages": [{"text": "未来结局"}]},
        ]
    }
    reading = {"events": [{"evidence": {"source_file": "book", "start": 0, "end": 9}}]}
    material = c.material(edition, reading, chunk)
    assert material["edition"] == "甲开门"
    assert material["source_excerpts"] == ["甲开门。"]
    assert "未来结局" not in json.dumps(material, ensure_ascii=False)
    assert c.edition_key({"basis": "a"}, "rule") != c.edition_key({"basis": "a"}, "changed")


async def test_cached_edition_resumes_without_rewriting_note(tmp_path, monkeypatch):
    from lib.novel_workflow import service, store

    reading = {"basis": "reading", "events": []}
    note = {"id": "note"}
    chunk = {"text": "甲开门。", "start": 0, "end": 4, "source_file": "book"}
    monkeypatch.setattr(service, "current", lambda *args: {})
    monkeypatch.setattr(store, "note_result", lambda *args: reading)
    monkeypatch.setattr(c.chapters, "chunks", lambda *args: [chunk])

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                text=json.dumps(
                    {"passages": [{"unit": 0, "treatment": "retain", "text": "甲开门。", "reason": "保留动作"}]}
                )
            )

    gen = Generator()
    first = await c.ensure(tmp_path, gen, note, reading, {}, "source")
    second = await c.ensure(tmp_path, gen, note, reading, {}, "source")
    assert first == second
    assert gen.calls == 1
    assert reading == {"basis": "reading", "events": []}
    assert first["parts"][0]["passages"][0]["evidence"]["start"] == 0


def test_subrequest_accepts_only_its_actual_unit_ids():
    source = [{"unit": 4, "text": "原文", "start": 100, "end": 102, "source_file": "book"}]
    value = c.Edition(passages=[c.Passage(unit=4, treatment="retain", text="原文", reason="保留")])
    assert c.validate(value, source, [])[0]["unit"] == 4
    value.passages[0].unit = 0
    with pytest.raises(ValueError, match="漏段"):
        c.validate(value, source, [])


async def test_new_material_batches_eight_units_and_resumes_cached_pairs(tmp_path, monkeypatch):
    import asyncio

    from lib.novel_understanding.store import digest
    from lib.novel_workflow import service, store

    reading = {"basis": "reading", "events": []}
    note = {"id": "note"}
    chunk = {"text": "甲" * 20, "start": 0, "end": 20, "source_file": "book"}
    source = [{"unit": i, "text": "甲", "start": i, "end": i + 1, "source_file": "book"} for i in range(20)]
    monkeypatch.setattr(service, "current", lambda *args: {})
    monkeypatch.setattr(store, "note_result", lambda *args: reading)
    monkeypatch.setattr(c.chapters, "chunks", lambda *args: [chunk])
    monkeypatch.setattr(c, "units", lambda *args: source)
    rule = await asyncio.to_thread(store.effective_rule, tmp_path, "condense")
    group = source[4:6]
    pair = c.Edition(
        passages=[c.Passage(unit=u["unit"], treatment="retain", text="保留原文", reason="保留") for u in group]
    )
    await asyncio.to_thread(
        store.write,
        store.root(tmp_path) / "edition_parts" / f"{digest([rule, group, []])}.json",
        c.validate(pair, group, []),
    )

    class Generator:
        def __init__(self):
            self.batches = []

        async def generate(self, request, **kwargs):
            payload = json.JSONDecoder().raw_decode(request.prompt[request.prompt.index('{"source_units"') :])[0]
            units = payload["source_units"]
            self.batches.append([u["unit"] for u in units])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "passages": [
                            {"unit": u["unit"], "treatment": "retain", "text": "保留原文", "reason": "保留"}
                            for u in units
                        ]
                    }
                )
            )

    gen = Generator()
    result = await c.ensure(tmp_path, gen, note, reading, {}, "source")
    assert gen.batches == [list(range(4)), list(range(6, 14)), list(range(14, 20))]
    assert [p["unit"] for p in result["parts"][0]["passages"]] == list(range(20))
    assert all(p["text"] == "甲" for p in result["parts"][0]["passages"])
