from lib.novel_workflow import conclusion_evidence as ce


def test_exact_question_quote_ranks_before_generic_character_mentions():
    rows = [
        {"id": "noise", "start": 0, "quote": "阳子闭上眼睛，听见了冗佑的名字。"},
        {"id": "line", "start": 30, "quote": "骠骑说：『不要闭眼睛！这样冗佑就没办法动了！』"},
    ]
    result = ce.related({"question": "‘不要闭眼睛！这样冗佑就没办法动了！’是否为世界规则？", "evidence_ids": []}, rows)
    assert result[0]["id"] == "line"
    assert "仍需区分" in result[0]["retrieval_reason"]
    assert not ce.related({"question": "王国继承方式为何？", "evidence_ids": []}, rows)


def test_catalog_excludes_future_outside_scope_and_false_source(tmp_path, monkeypatch):
    text = "第一章台词。第二章动作。第三章答案。"
    (tmp_path / "novel.txt").write_text(text)
    notes = [{"id": str(i), "order": i, "title": f"第{i}章"} for i in (1, 2, 3)]

    for n, quote in zip(notes, ("第一章台词。", "第二章动作。", "第三章答案。"), strict=True):
        start = text.index(quote)
        n["sections"] = [{"source_file": "novel.txt", "start": start, "end": start + len(quote)}]

    def row(identity, quote):
        start = text.index(quote)
        return {
            "id": identity,
            "kind": "character",
            "evidence": {
                "note_id": identity,
                "source_file": "novel.txt",
                "start": start,
                "end": start + len(quote),
                "quote": quote,
            },
        }

    readings = {
        str(i): {"assets": [row(str(i), quote)]}
        for i, quote in enumerate(("第一章台词。", "第二章动作。", "第三章答案。"), 1)
    }
    monkeypatch.setattr(ce.store, "state", lambda _p: {"notes": notes})
    monkeypatch.setattr(ce.store, "valid_readings", lambda *_a: readings)
    monkeypatch.setattr(ce.scope, "available_ids", lambda *_a: {"1", "2", "3"})
    rows = ce.catalog(tmp_path, notes[1], readings["2"], {})
    assert {r["note_id"] for r in rows} == {"1", "2"}
    monkeypatch.setattr(ce.scope, "available_ids", lambda *_a: {"2", "3"})
    assert [r["note_id"] for r in ce.catalog(tmp_path, notes[1], readings["2"], {})] == ["2"]
    readings["2"]["assets"][0]["evidence"]["quote"] = "编造原文"
    assert all(r["quote"] != "编造原文" for r in ce.catalog(tmp_path, notes[1], readings["2"], {}))


async def _saved_conclusion(path):
    import asyncio

    from lib.novel_workflow import conclusions
    from lib.novel_workflow.common import now
    from tests.unit.lib.episode.test_note_conclusions import draft, fixture

    def prepare():
        book, note, reading, report = fixture(path)
        material, ev, questions = conclusions.inputs(path, note, reading, report)
        data = conclusions.validate(
            conclusions.Consolidation.model_validate(draft(material)), note, reading, ev, questions, book, 1200
        )
        key = conclusions.basis(path, reading, report)
        value = {
            **data,
            "basis": key,
            "note_id": note["id"],
            "reading_basis": reading["basis"],
            "report_id": report["id"],
            "created_at": now(),
            "source_questions": list(questions.values()),
            "available_evidence": [{"id": i, **e} for i, e in ev.items()],
            "inspected_note_ids": [note["id"]],
        }
        conclusions.commit(path, note, book["source_basis"], report, key, value)
        return book, note, reading, value

    return await asyncio.to_thread(prepare)


import pytest


@pytest.mark.asyncio
async def test_targeted_review_is_cached_without_adopting_a_human_decision(tmp_path, monkeypatch):
    import asyncio

    from lib.novel_workflow import conclusions, service

    book, note, reading, value = await _saved_conclusion(tmp_path)
    item = value["conclusions"][0]
    calls = []

    async def fake_ask(path, generator, schema, prompt, validate, **kwargs):
        import json

        payload = json.JSONDecoder().raw_decode(prompt.split("本次疑点与候选原文：", 1)[1])[0]
        sources = payload["sources"]
        assert sources
        assert all(e["note_id"] == note["id"] for e in sources)
        calls.append(prompt)
        return validate(
            schema(
                status="partial",
                answer="当前原文只有陌生人的出场，不足以确认身份。",
                reason="不借用后章结局。",
                evidence_ids=[sources[0]["id"]],
                findings=[
                    {"evidence_id": e["id"], "relation": "insufficient", "explanation": "有出场描写，但没有具名。"}
                    for e in sources
                ],
            )
        )

    monkeypatch.setattr(service, "ask", fake_ask)
    await ce.generate(tmp_path, object(), [note["id"]], book["source_basis"], item["id"])
    result = await ce.generate(tmp_path, object(), [note["id"]], book["source_basis"], item["id"])
    assert result == {"cached": True}
    assert len(calls) == 1
    saved = await asyncio.to_thread(conclusions.load, tmp_path, note, reading)
    assert saved["conclusions"] == value["conclusions"]
