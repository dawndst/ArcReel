import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_understanding.store import digest
from lib.novel_workflow import conclusions, settings, store, understanding
from lib.novel_workflow.conclusions import Consolidation
from tests.unit.lib.episode.test_cross_chapter_understanding import FIRST, SECOND, setup


def fixture(path):
    _project, notebook = setup(path)
    settings.update(path, {"conclusions_enabled": True})
    note = notebook["notes"][0]
    reading = store.note_result(path, note)
    reading["reading_questions"] = [
        {"text": "陌生人是谁？", "kind": "plot_unrevealed"},
        {"text": "紫衣人的身份是否明确？", "kind": "plot_unrevealed"},
    ]
    store.write(store.root(path) / "notes" / note["id"] / f"{store.reading_key(path, note)}.json", reading)
    text = (path / "source/book.txt").read_text()
    ev = {
        "note_id": notebook["notes"][1]["id"],
        "source_file": "source/book.txt",
        "start": text.index(SECOND),
        "end": text.index(SECOND) + len(SECOND),
        "quote": SECOND,
    }
    report = {
        "id": "test-report",
        "source_basis": notebook["source_basis"],
        "rule_basis": digest(understanding.understanding_rules(path)),
        "note_bases": {note["id"]: reading["basis"]},
        "links": [
            {
                "id": "identity",
                "kind": "identity",
                "subject": "陌生人身份",
                "description": "第二章揭示身份",
                "status": "supported",
                "claim_type": "fact",
                "note_ids": [note["id"], ev["note_id"]],
                "evidence": [reading["assets"][0]["evidence"], ev],
            }
        ],
        "unresolved": [],
    }
    store.write(store.root(path) / "understanding/reports/test-report.json", report)
    return notebook, note, reading, report


def draft(material):
    first = next(e["id"] for e in material["evidence"] if e["note_id"] == material["note_id"])
    return {
        "overview": {
            "summary": FIRST,
            "cause": "遇到陌生人",
            "conflict": "身份未知",
            "action": "观察",
            "outcome": "身份尚未揭晓",
            "hook": "过期疑点必须被替换",
            "questions": ["过期疑点"],
            "evidence_ids": [first],
        },
        "conclusions": [
            {
                "question": "紫衣陌生人是谁？",
                "source_ids": [q["id"] for q in material["questions"]],
                "status": "resolved",
                "answer": "第二章明确揭示为景麒。",
                "evidence_ids": [e["id"] for e in material["evidence"]],
                "support": "explicit",
                "impact": "none",
                "production_constraint": "第二章揭示前保持陌生人身份。",
                "claim_type": "fact",
                "source_kind": "narrative",
                "perspective": "",
            }
        ],
    }


async def test_consolidation_preserves_raw_reading_and_reveal_boundary_and_reuses_cache(tmp_path):
    notebook, note, reading, report = await asyncio.to_thread(fixture, tmp_path)

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            material = json.JSONDecoder().raw_decode(request.prompt.split("结论整理材料：", 1)[1])[0]
            response = draft(material)
            if self.calls == 1:
                response["conclusions"][0]["source_ids"].pop()
            else:
                assert "精确校验错误" in request.prompt
                assert "缺少source_ids" in request.prompt
                assert '"draft"' in request.prompt
            return SimpleNamespace(text=json.dumps(response))

    generator = Generator()
    await conclusions.ensure(tmp_path, generator, [note["id"]], notebook["source_basis"], report)
    await conclusions.ensure(tmp_path, generator, [note["id"]], notebook["source_basis"], report)
    assert generator.calls == 2
    await asyncio.to_thread((store.root(tmp_path) / "conclusions" / f"{note['id']}.json").unlink)
    await conclusions.ensure(tmp_path, generator, [note["id"]], notebook["source_basis"], report)
    assert generator.calls == 2
    assert await asyncio.to_thread(store.note_result, tmp_path, note) == reading
    reviewed = await asyncio.to_thread(conclusions.effective_reading, tmp_path, note, reading)
    assert reviewed["questions"] == []
    assert "过期疑点" not in reviewed["overview"]["hook"]
    assert reviewed["conclusion_review"]["conclusions"][0]["revealed_at"]["order"] == 2
    assert (await asyncio.to_thread(understanding.production_context, tmp_path, [note["id"]]))["links"] == []
    assert (await asyncio.to_thread(understanding.production_context, tmp_path, [notebook["notes"][2]["id"]]))["links"]


def test_resolution_requires_explicit_evidence_and_covers_every_original_question(tmp_path):
    notebook, note, reading, report = fixture(tmp_path)
    material, evidence, questions = conclusions.inputs(tmp_path, note, reading, report)
    value = draft(material)
    value["conclusions"][0]["support"] = "inference"
    with pytest.raises(ValueError, match="直接正文依据"):
        conclusions.validate(Consolidation.model_validate(value), note, reading, evidence, questions, notebook, 1200)
    value = draft(material)
    value["conclusions"][0]["source_ids"].pop()
    with pytest.raises(ValueError, match="恰好归入"):
        conclusions.validate(Consolidation.model_validate(value), note, reading, evidence, questions, notebook, 1200)
    value = draft(material)
    value["conclusions"][0].update(status="unrevealed", support="none", evidence_ids=[], answer="范围内未揭晓")
    result = conclusions.validate(
        Consolidation.model_validate(value), note, reading, evidence, questions, notebook, 1200
    )
    assert not result["conclusions"][0]["blocking"]
    assert result["overview"]["questions"] == ["紫衣陌生人是谁？"]
    value["conclusions"][0].update(status="partial", impact="identity")
    result = conclusions.validate(
        Consolidation.model_validate(value), note, reading, evidence, questions, notebook, 1200
    )
    assert not result["conclusions"][0]["blocking"]
    assert result["conclusions"][0]["production_constraint"]


async def test_call_limit_stops_before_extra_generation_and_keeps_visible_counter(tmp_path):
    from lib.novel_understanding.service import NovelReadingInterrupted
    from lib.novel_workflow.call_budget import WorkflowGenerator

    await asyncio.to_thread(settings.update, tmp_path, {"max_model_calls": 1})

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            return SimpleNamespace(text="paid response")

    backend = Generator()
    generator = await WorkflowGenerator.create(backend, tmp_path, "task-1", "conclusions")
    assert (await generator.generate(None)).text == "paid response"
    with pytest.raises(NovelReadingInterrupted):
        await generator.generate(None)
    value = await asyncio.to_thread(lambda: json.loads((store.root(tmp_path) / "call_budget.json").read_text()))
    assert backend.calls == 1
    assert value["used"] == 1
    assert value["limit_reached"]


async def test_manual_decision_survives_new_report_and_invalidates_old_overlay(tmp_path):
    notebook, note, reading, report = await asyncio.to_thread(fixture, tmp_path)
    material, evidence, questions = await asyncio.to_thread(conclusions.inputs, tmp_path, note, reading, report)
    value = conclusions.validate(
        Consolidation.model_validate(draft(material)), note, reading, evidence, questions, notebook, 1200
    )
    value.update(
        basis=await asyncio.to_thread(conclusions.basis, tmp_path, reading, report),
        report_id=report["id"],
        source_questions=list(questions.values()),
    )
    await asyncio.to_thread(store.write, store.root(tmp_path) / "conclusions" / f"{note['id']}.json", value)
    item = value["conclusions"][0]
    value["available_evidence"] = [
        {"id": key, **ev} for key, ev in zip(item["evidence_ids"], item["evidence"], strict=True)
    ]
    selected_evidence = item["evidence_ids"][:]
    item["evidence_ids"] = item["evidence_ids"][:1]
    item["evidence"] = item["evidence"][:1]
    await asyncio.to_thread(store.write, store.root(tmp_path) / "conclusions" / f"{note['id']}.json", value)
    await asyncio.to_thread(
        conclusions.decide,
        tmp_path,
        note["id"],
        item["id"],
        "partial",
        "先保留人物当时的疑问",
        selected_evidence,
        "不提前揭晓身份",
        notebook["source_basis"],
    )
    assert await asyncio.to_thread(conclusions.load, tmp_path, note, reading, report) is None
    updated, refs, qs = await asyncio.to_thread(conclusions.inputs, tmp_path, note, reading, None)
    assert set(item["source_ids"]) <= set(qs)
    assert set(item["evidence_ids"]) <= set(refs)
    changed = draft(updated)
    changed["conclusions"][0].update(status="partial", answer="先保留人物当时的疑问")
    result = conclusions.validate(
        Consolidation.model_validate(changed),
        note,
        {**reading, "_manual_decisions": updated["manual_decisions"]},
        refs,
        qs,
        notebook,
        1200,
    )
    assert result["conclusions"][0]["answer"] == "先保留人物当时的疑问"
    changed["conclusions"][0]["answer"] = "模型反转决定"
    with pytest.raises(ValueError, match="保留人工处理"):
        conclusions.validate(
            Consolidation.model_validate(changed),
            note,
            {**reading, "_manual_decisions": updated["manual_decisions"]},
            refs,
            qs,
            notebook,
            1200,
        )
    changed["conclusions"][0].update(answer="先保留人物当时的疑问", evidence_ids=[])
    with pytest.raises(ValueError, match="保留人工处理"):
        conclusions.validate(
            Consolidation.model_validate(changed),
            note,
            {**reading, "_manual_decisions": updated["manual_decisions"]},
            refs,
            qs,
            notebook,
            1200,
        )


def test_conclusion_inputs_reject_report_evidence_outside_available_scope(tmp_path):
    _notebook, note, reading, report = fixture(tmp_path)
    store.write(store.root(tmp_path) / "scope.json", {"note_ids": [note["id"]]})
    with pytest.raises(ValueError, match="当前可用范围"):
        conclusions.inputs(tmp_path, note, reading, report)
    material, evidence, _questions = conclusions.inputs(tmp_path, note, reading, None)
    assert material["note_id"] == note["id"]
    assert {e["note_id"] for e in evidence.values()} == {note["id"]}
