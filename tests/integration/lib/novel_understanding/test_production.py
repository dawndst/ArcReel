"""Novel memory: source-grounded isolation, resumable reading and native merge adoption."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from lib.backends.text_generator import TextGenerator
from lib.episode.episode_manual_split import ManualSplitConfirmationRequired, merge_with_next_episode
from lib.infra.json_io import load_json
from lib.novel_understanding import editorial, service, store
from lib.novel_understanding.models import BookSynthesis, EditorialDecision, FactDraft, ReadingDraft
from lib.project.project_manager import ProjectManager
from tests.fakes import FakeTextGenerator

EARLY = "少年阿青身穿完整的白衣走进院落，左臂尚未受伤。"
LATE = "多年后阿青才公开自己是白龙的秘密，并化为兽形。"


@pytest.fixture
def book(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    manager.create_project("novel", content_mode="drama")
    path = manager.get_project_path("novel")
    (path / "source" / "book.txt").write_text(EARLY + LATE, encoding="utf-8")

    def update(p):
        p["generation_mode"] = "storyboard"
        p["whole_source_files"] = [{"source_file": "source/book.txt", "source_kind": "novel"}]
        p["episodes"] = [
            {
                "episode": n,
                "title": "阿青",
                "hook": "等待",
                "source_origin": "whole_source",
                "script_file": f"scripts/episode_{n}.json",
                "ledger_status": "planned",
                "source_range": {"source_file": "source/book.txt", "start": start, "end": end},
                "outline": {"story_beats": [text], "next_episode_teaser": None},
            }
            for n, start, end, text in [(1, 0, len(EARLY), EARLY), (2, len(EARLY), len(EARLY + LATE), LATE)]
        ]

    manager.update_project("novel", update)
    return path, manager.load_project("novel"), manager


def reading() -> ReadingDraft:
    return ReadingDraft(
        summary="阿青后来揭示白龙身份。",
        facts=[
            FactDraft(subject="阿青", category="appearance", statement="完整白衣", evidence_quote=EARLY),
            FactDraft(subject="阿青", category="identity", statement="阿青是白龙", evidence_quote=LATE),
        ],
    )


def generator(*responses) -> tuple[TextGenerator, FakeTextGenerator]:
    fake = FakeTextGenerator(*responses)
    return cast(TextGenerator, fake), fake


def synthesis() -> str:
    return BookSynthesis(synopsis="白龙", genre="奇幻", theme="成长", world_setting="异界").model_dump_json()


@pytest.mark.asyncio
async def test_reading_cached_and_future_facts_never_enter_writer(book):
    path, project, _ = book
    gen, fake = generator(reading().model_dump_json(), synthesis())
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    context = memory.writer_context("source/book.txt", len(EARLY), EARLY)
    assert EARLY in context
    assert "白龙" not in context
    assert LATE not in context
    assert (await asyncio.to_thread(store.status, path, project))["coverage"] == 100
    again = await service.ensure(path, project, gen)
    assert again is not None
    assert len(fake.requests) == 2


@pytest.mark.asyncio
async def test_disabled_module_never_calls_generator_or_creates_cache(book):
    path, project, _ = book
    project[store.SETTING_KEY] = False
    gen, fake = generator()
    assert await service.ensure(path, project, gen) is None
    assert fake.requests == []
    assert not await asyncio.to_thread(store.root(path).exists)


@pytest.mark.asyncio
async def test_resume_after_synthesis_failure_reuses_reading(book):
    path, project, _ = book
    gen, fake = generator(reading().model_dump_json(), RuntimeError("provider unavailable"), synthesis())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await service.ensure(path, project, gen)
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    assert len(fake.requests) == 3
    assert "BookSynthesis" in fake.requests[2].prompt
    assert fake.requests[2].response_schema is None


def test_invalid_and_ambiguous_evidence_rejected(book):
    path, project, _ = book
    source = store.source_snapshot(path, project)
    invalid = reading()
    invalid.facts[0].evidence_quote = "不存在的原文证据必须拒绝"
    with pytest.raises(store.NovelUnderstandingError, match="unique verbatim"):
        store.ground_chunk(source.chunks[0], invalid)


def test_source_and_per_project_rules_invalidate_cache(book):
    path, project, _ = book
    source = store.source_snapshot(path, project)
    store.rules(path, install=True)
    (store.root(path) / "rules" / "reading.md").write_text("独立的阅读规则", encoding="utf-8")
    assert store.source_snapshot(path, project).run_id != source.run_id
    (path / "source" / "book.txt").write_text(EARLY, encoding="utf-8")
    assert store.source_snapshot(path, project).source_digest != source.source_digest


@pytest.mark.asyncio
async def test_review_checks_each_episode_cutoff_and_does_not_leak_feedback(book):
    path, project, _ = book
    gen, fake = generator(reading().model_dump_json(), synthesis())
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    future = next(f for f in memory.facts if f.category == "identity")
    review_gen, reviewer = generator(
        json.dumps(
            {
                "issues": [
                    {
                        "item_id": "1",
                        "kind": "premature_reveal",
                        "offending_text": "阿青展示身份",
                        "fact_ids": [future.id],
                        "explanation": "未来真相是白龙",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    feedback = await service.review(
        path,
        memory,
        review_gen,
        item_id="1",
        cutoff=("source/book.txt", len(EARLY)),
        content={"title": "阿青展示身份"},
        stage="script",
    )
    assert len(feedback) == 1
    assert "白龙" not in feedback[0]
    assert "reader_cutoff" in reviewer.requests[0].prompt
    assert len(fake.requests) == 2


def make_proposal(path, project):
    source = store.source_snapshot(path, project)
    decision = EditorialDecision(
        action="merge_next",
        reason="合并构成成长弧",
        must_film=["阿青入院"],
        compress=[],
        omit=[],
        preserve_setup=["白衣"],
        evidence_ids=["F-test"],
        title="阿青的成长",
        story_beats=["入院", "多年后揭示"],
        hook="新的旅程",
    )
    report_id = store.digest("proposal")
    report = {
        "id": report_id,
        "basis": editorial.basis(project, source, 1),
        "episode": 1,
        "next_episode": 2,
        "decision": decision.model_dump(),
        "evidence": [],
    }
    service.save_json(editorial.report_path(path, report_id), report)
    return report_id


def test_adopt_merge_updates_source_and_outline_in_same_native_transaction(book):
    path, project, manager = book
    report_id = make_proposal(path, project)
    _, validate, amend = editorial.adoption(path, report_id)
    preview = merge_with_next_episode(path, 1, dry_run=True, validate_project=validate, amend_project=amend)
    assert isinstance(preview, ManualSplitConfirmationRequired)
    assert len(manager.load_project("novel")["episodes"]) == 2
    merge_with_next_episode(path, 1, validate_project=validate, amend_project=amend)
    current = manager.load_project("novel")
    assert len(current["episodes"]) == 1
    assert current["episodes"][0]["title"] == "阿青的成长"
    assert current["episodes"][0]["source_range"]["end"] == len(EARLY + LATE)
    assert "阿青入院" in editorial.accepted_constraints(current, 1)
    assert (path / "source" / "episode_1.txt").read_text(encoding="utf-8") == EARLY + LATE


def test_stale_proposal_cannot_merge(book):
    path, project, manager = book
    report_id = make_proposal(path, project)
    _, validate, amend = editorial.adoption(path, report_id)
    manager.update_project("novel", lambda p: p["episodes"][0].update(title="已改名"))
    with pytest.raises(store.NovelUnderstandingError, match="out of date"):
        merge_with_next_episode(path, 1, validate_project=validate, amend_project=amend)
    assert len(load_json(path / "project.json")["episodes"]) == 2


@pytest.mark.asyncio
async def test_native_planner_default_on_checks_individual_cutoffs(book):
    from lib.episode.episode_planner import EpisodePlanner

    path, _, manager = book
    await asyncio.to_thread(manager.update_project, "novel", lambda p: p.update(episodes=[]))
    plan = {
        "episodes": [
            {
                "title": "阿青入院",
                "hook": "门后是谁",
                "end_anchor": EARLY,
                "story_beats": ["阿青入院"],
                "next_episode_teaser": None,
            },
            {
                "title": "阿青现身",
                "hook": "新的旅程",
                "end_anchor": LATE,
                "story_beats": ["阿青公开身份"],
                "next_episode_teaser": None,
            },
        ]
    }
    gen, fake = generator(
        reading().model_dump_json(),
        synthesis(),
        json.dumps(plan, ensure_ascii=False),
        '{"issues": []}',
        '{"issues": []}',
    )
    planner = await asyncio.to_thread(EpisodePlanner, path, gen)
    result = await planner.plan()
    assert len(result.episodes) == 2
    reviews = [r.prompt for r in fake.requests if '"reader_cutoff"' in r.prompt]
    assert len(reviews) == 2
    assert json.dumps(["source/book.txt", len(EARLY)]) in reviews[0]
    assert json.dumps(["source/book.txt", len(EARLY + LATE)]) in reviews[1]


def test_unrelated_appended_episode_does_not_invalidate_earlier_report(book):
    path, project, _ = book
    source = store.source_snapshot(path, project)
    before = editorial.basis(project, source, 1)
    project["episodes"].append({"episode": 3, "title": "独立番外", "source_origin": "own"})
    assert editorial.basis(project, source, 1) == before


def test_manual_outline_edits_invalidate_accepted_compression(book):
    path, project, _ = book
    report_id = make_proposal(path, project)
    _, _, amend = editorial.adoption(path, report_id)
    amend(project)
    assert editorial.accepted_constraints(project, 1)
    project["episodes"][0]["outline"]["story_beats"] = ["用户另写的节点"]
    assert editorial.accepted_constraints(project, 1) == ""


@pytest.mark.asyncio
async def test_script_guard_retries_with_safe_feedback_and_preserves_paid_response(book):
    from lib.backends.text_backends.base import TextGenerationRequest

    path, project, _ = book
    gen, _ = generator(reading().model_dump_json(), synthesis())
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    fact_id = next(f.id for f in memory.facts if f.category == "identity")
    issue = {
        "issues": [
            {
                "item_id": "1",
                "kind": "premature_reveal",
                "offending_text": "阿青展现真身",
                "fact_ids": [fact_id],
                "explanation": "白龙是未来秘密",
            }
        ]
    }
    production, fake = generator(
        '{"title":"阿青展现真身"}', json.dumps(issue, ensure_ascii=False), '{"title":"阿青走进院落"}', '{"issues":[]}'
    )
    guard = service.ProductionGuard(
        path,
        memory,
        production,
        1,
        ("source/book.txt", len(EARLY)),
        memory.writer_context("source/book.txt", len(EARLY), EARLY),
        service.episode_basis(project, 1),
    )
    result = await guard.generate(TextGenerationRequest(prompt="只写本集"))
    assert "走进院落" in result.text
    assert "白龙" not in fake.requests[2].prompt
    responses = await asyncio.to_thread(
        lambda: list((store.run_dir(path, memory.source) / "responses").glob("production-*.json"))
    )
    assert len(responses) == 2


@pytest.mark.asyncio
async def test_stop_finishes_paid_chunk_and_resume_uses_it(book):
    path, project, _ = book
    gen, fake = generator(reading().model_dump_json(), synthesis())
    token = service.stop_requested.set(lambda: len(fake.requests) >= 1)
    try:
        with pytest.raises(service.NovelReadingInterrupted):
            await service.ensure(path, project, gen)
    finally:
        service.stop_requested.reset(token)
    state = await asyncio.to_thread(store.status, path, project)
    assert state["phase"] == "interrupted"
    assert state["completed_chunks"] == 1
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    assert len(fake.requests) == 2


@pytest.mark.asyncio
async def test_invalid_json_response_is_preserved_then_retried(book):
    path, project, _ = book
    gen, fake = generator("not json", reading().model_dump_json(), synthesis())
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    assert len(fake.requests) == 3
    assert "上一轮 JSON 不符合结构要求" in fake.requests[1].prompt
    responses = await asyncio.to_thread(lambda: list((store.run_dir(path, memory.source) / "responses").glob("*.json")))
    assert len(responses) == 3


@pytest.mark.asyncio
async def test_truncated_reading_splits_and_resumes_without_repeating_paid_parts(book):
    from lib.backends.text_backends.base import TextOutputTruncatedError

    path, project, _ = book
    text = EARLY + "。" * 1200 + LATE + "！" * 1200
    await asyncio.to_thread((path / "source" / "book.txt").write_text, text, encoding="utf-8")
    left = ReadingDraft(summary="少年阶段", facts=[reading().facts[0]])
    right = ReadingDraft(summary="成年形态", facts=[reading().facts[1]])
    gen, fake = generator(
        TextOutputTruncatedError(provider="fake", model="test", output_tokens=24000),
        left.model_dump_json(),
        RuntimeError("temporary failure"),
        right.model_dump_json(),
        synthesis(),
    )
    with pytest.raises(RuntimeError, match="temporary failure"):
        await service.ensure(path, project, gen)
    state = await asyncio.to_thread(store.status, path, project)
    assert state["completed_chunks"] == 0
    assert state["read_chars"] == len(text) // 2
    memory = await service.ensure(path, project, gen)
    assert memory is not None
    assert len(fake.requests) == 5
    assert memory.chunks[0].reading_summaries == ["少年阶段", "成年形态"]
    assert {f.evidence.quote for f in memory.facts} == {EARLY, LATE}
    assert all(text[f.evidence.start : f.evidence.end] == f.evidence.quote for f in memory.facts)
    state = await asyncio.to_thread(store.status, path, project)
    assert state["coverage"] == 100
    assert state["read_chars"] == len(text)
    assert len(fake.requests[1].prompt) < len(fake.requests[0].prompt)


@pytest.mark.asyncio
async def test_truncated_minimum_reading_range_stops_without_infinite_retry(book):
    from lib.backends.text_backends.base import TextOutputTruncatedError

    path, project, _ = book
    gen, fake = generator(TextOutputTruncatedError(provider="fake", model="test"))
    with pytest.raises(store.NovelUnderstandingError, match="small source range"):
        await service.ensure(path, project, gen)
    assert len(fake.requests) == 1
    assert (await asyncio.to_thread(store.status, path, project))["read_chars"] == 0
