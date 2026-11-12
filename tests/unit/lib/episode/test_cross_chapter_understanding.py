import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, retrieval, settings, store, understanding
from lib.novel_workflow.understanding_models import Findings

FIRST = "门边站着紫衣陌生人。他手持白玉。"
SECOND = "那名紫衣陌生人正是景麒。白玉来自王宫。"
THIRD = "景麒转身离开。"


def setup(path):
    (path / "source").mkdir()
    (path / "source/book.txt").write_text(f"# 第一章\n{FIRST}\n# 第二章\n{SECOND}\n# 第三章\n{THIRD}\n")
    project = {"whole_source_files": [{"source_file": "source/book.txt"}]}
    (path / "project.json").write_text(json.dumps(project))
    preview = chapters.index(path, project)
    notebook = store.initialize(path, project, preview["source_basis"])
    # The middle chapter is intentionally unread; retrieval must still find its original text.
    for note, quote, name in [(notebook["notes"][0], FIRST, "紫衣陌生人"), (notebook["notes"][2], THIRD, "景麒")]:
        part = chapters.chunks(path, project, note)[0]
        start = part["start"] + part["text"].index(quote)
        evidence = {
            "note_id": note["id"],
            "source_file": part["source_file"],
            "start": start,
            "end": start + len(quote),
            "quote": quote,
        }
        record = {
            "id": digest(evidence)[:24],
            "kind": "character",
            "name": name,
            "identity_scope": "",
            "description": "原文出现",
            "evidence": evidence,
        }
        result = {
            "basis": digest([note["basis"], quote]),
            "assets": [record],
            "changes": [],
            "events": [],
            "questions": ["陌生人是谁"],
            "summaries": [quote],
            "overview": {"summary": quote},
        }
        key = store.reading_key(path, note)
        store.write(store.root(path) / "notes" / note["id"] / f"{key}.json", result)
    return project, notebook


class CrossReader:
    def __init__(self):
        self.calls = []

    async def generate(self, request, **kwargs):
        if "# 章节精编与原文回读" in request.prompt:
            from tests.unit.lib.episode.test_novel_workflow import Reader

            return await Reader().generate(request, **kwargs)
        self.calls.append(request.prompt)
        if "查询规划材料：" in request.prompt:
            return SimpleNamespace(text=json.dumps({"queries": ["紫衣陌生人 景麒 白玉"], "questions": ["陌生人是谁"]}))
        fragments = json.loads(request.prompt.split("\n原文片段：", 1)[1].split("\n只输出 JSON", 1)[0])
        first = next(f for f in fragments if FIRST in f["text"])
        second = next(f for f in fragments if SECOND in f["text"])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "links": [
                        {
                            "kind": "identity",
                            "subject": "紫衣陌生人 / 景麒",
                            "description": "第二章揭晓第一章陌生人为景麒",
                            "status": "supported",
                            "story_time": "第一章出现时即为同一人物",
                            "story_start_note_id": first["note_id"],
                            "citations": [
                                {"fragment_id": first["id"], "quote": FIRST},
                                {"fragment_id": second["id"], "quote": SECOND},
                            ],
                        }
                    ],
                    "unresolved": [],
                    "next_queries": [],
                }
            )
        )


async def test_rereads_unread_source_without_rewriting_notes_and_filters_future_revelation(tmp_path):
    project, notebook = await asyncio.to_thread(setup, tmp_path)
    first, second, third = notebook["notes"]
    before = await asyncio.to_thread(store.note_result, tmp_path, first)
    reader = CrossReader()
    await understanding.understand_notes(tmp_path, reader, [first["id"]], notebook["source_basis"])
    result = await asyncio.to_thread(store.view, tmp_path, project)
    link = result["understanding"]["links"][0]
    assert link["revealed_at"]["note_id"] == second["id"]
    assert link["revealed_at"]["order"] == 2
    assert link["story_start_note_id"] == first["id"]
    assert second["id"] in result["understanding"]["reports"][0]["unread_inspected_note_ids"]
    assert result["notes"][1]["status"] == "unread"
    assert await asyncio.to_thread(store.note_result, tmp_path, first) == before
    assert result["notes"][0]["reading"]["assets"][0]["name"] == before["assets"][0]["name"]
    early = await asyncio.to_thread(understanding.production_context, tmp_path, [first["id"]])
    later = await asyncio.to_thread(understanding.production_context, tmp_path, [third["id"]])
    assert early["links"] == []
    assert later["links"][0]["id"] == link["id"]
    await understanding.understand_notes(tmp_path, reader, [first["id"]], notebook["source_basis"])
    assert len(reader.calls) == 2
    await asyncio.to_thread(understanding.require_understood, tmp_path, [first["id"]])
    with pytest.raises(ValueError, match="尚未完成"):
        await asyncio.to_thread(understanding.require_understood, tmp_path, [third["id"]])
    await asyncio.to_thread(settings.update, tmp_path, {"understanding_enabled": False})
    assert (await asyncio.to_thread(understanding.production_context, tmp_path, [third["id"]]))["links"] == []


def test_retrieval_searches_raw_chapters_and_citations_cannot_fabricate_or_backdate(tmp_path):
    project, notebook = setup(tmp_path)
    corpus = retrieval.index(tmp_path, project, notebook)
    hits = retrieval.search(corpus, ["景麒 白玉 王宫"])
    second = notebook["notes"][1]
    assert any(f["note_id"] == second["id"] and SECOND in f["text"] for f in hits)
    first_fragment, second_fragment = corpus["fragments"][:2]
    payload = {
        "links": [
            {
                "kind": "identity",
                "subject": "景麒",
                "description": "同一人",
                "status": "supported",
                "citations": [
                    {"fragment_id": first_fragment["id"], "quote": FIRST},
                    {"fragment_id": second_fragment["id"], "quote": "原文不存在的真相"},
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="唯一出现"):
        understanding.ground(Findings.model_validate(payload), hits, {notebook["notes"][0]["id"]}, notebook)
    payload["links"][0]["citations"][1]["quote"] = SECOND
    result = understanding.ground(Findings.model_validate(payload), hits, {notebook["notes"][0]["id"]}, notebook)
    assert result["links"][0]["revealed_at"]["order"] == 2


def test_summary_limit_is_project_scoped_and_changes_summary_cache_identity(tmp_path):
    _project, notebook = setup(tmp_path)
    note = notebook["notes"][0]
    previous = store.reading_key(tmp_path, note)
    assert settings.get(tmp_path)["summary_max_chars"] == 1200
    settings.update(tmp_path, {"summary_max_chars": 2400})
    assert "2400" in settings.chapter_rule(tmp_path)
    assert store.reading_key(tmp_path, note) != previous
    with pytest.raises(ValueError, match="400 and 3000"):
        settings.update(tmp_path, {"summary_max_chars": 6000})


async def test_read_action_automatically_finishes_understanding_for_cached_notes(tmp_path):
    from lib.novel_workflow.service import read_notes

    _project, notebook = await asyncio.to_thread(setup, tmp_path)
    from lib.novel_workflow import scope

    await asyncio.to_thread(
        scope.configure, tmp_path, _project, [n["id"] for n in notebook["notes"]], notebook["source_basis"]
    )
    first = notebook["notes"][0]
    reader = CrossReader()
    await read_notes(tmp_path, reader, [first["id"]], notebook["source_basis"])
    state = await asyncio.to_thread(understanding.view, tmp_path)
    assert len(state["links"]) == 1
    assert state["reports"][0]["selected_note_ids"] == [first["id"]]
    assert len(reader.calls) == 2


async def test_configured_summary_limit_is_validated_and_repair_is_requested(tmp_path):
    from lib.novel_workflow.synthesis import chapter

    _project, notebook = await asyncio.to_thread(setup, tmp_path)
    settings_value = await asyncio.to_thread(settings.update, tmp_path, {"summary_max_chars": 400})
    assert settings_value["summary_max_chars"] == 400
    first = notebook["notes"][0]
    reading = await asyncio.to_thread(store.note_result, tmp_path, first)
    # The old summary key is deliberately invalid now; use independently validated extraction as input.
    assert reading is None

    class Summarizer:
        def __init__(self):
            self.calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "summary": "字" * (401 if self.calls == 1 else 380),
                        "cause": "未明",
                        "conflict": "未明",
                        "action": "出现",
                        "outcome": "站在门边",
                        "hook": "身份未知",
                        "evidence_ids": ["fact"],
                    }
                )
            )

    generator = Summarizer()
    result = await chapter(
        tmp_path,
        generator,
        [{"summary": "人物出现", "assets": [{"id": "fact", "evidence": {"quote": FIRST}}]}],
        await asyncio.to_thread(settings.chapter_rule, tmp_path),
    )
    assert len(result["summary"]) == 380
    assert generator.calls == 2


def test_single_note_claim_is_unresolved_not_confirmed_cross_chapter_fact(tmp_path):
    project, notebook = setup(tmp_path)
    corpus = retrieval.index(tmp_path, project, notebook)
    first = notebook["notes"][0]
    fragment = next(f for f in corpus["fragments"] if f["note_id"] == first["id"])
    findings = Findings.model_validate(
        {
            "links": [
                {
                    "kind": "identity",
                    "subject": "陌生人",
                    "description": "身份同指待核对",
                    "status": "supported",
                    "story_time": "未明确",
                    "citations": [
                        {"fragment_id": fragment["id"], "quote": "门边站着紫衣陌生人。"},
                        {"fragment_id": fragment["id"], "quote": "他手持白玉。"},
                    ],
                }
            ],
            "unresolved": [],
            "next_queries": [],
        }
    )
    result = understanding.ground(findings, [fragment], {first["id"]}, notebook)
    assert result["links"] == []
    assert len(result["unresolved"]) == 1
    assert "仅有本章依据" in result["unresolved"][0]
    unrelated = understanding.ground(findings, [fragment], {notebook["notes"][1]["id"]}, notebook)
    assert unrelated["links"] == []
    assert "未覆盖本次锚点" in unrelated["unresolved"][0]


def test_citation_relocates_only_to_unique_supplied_source_span(tmp_path):
    project, notebook = setup(tmp_path)
    fragments = retrieval.index(tmp_path, project, notebook)["fragments"]
    first, second = fragments[:2]
    value = Findings.model_validate(
        {
            "links": [
                {
                    "kind": "identity",
                    "subject": "景麒",
                    "description": "后章揭晓身份",
                    "status": "supported",
                    "citations": [
                        {"fragment_id": first["id"], "quote": FIRST},
                        {"fragment_id": first["id"], "quote": SECOND},
                    ],
                }
            ]
        }
    )
    result = understanding.ground(value, [first, second], {first["note_id"]}, notebook)
    evidence = result["links"][0]["evidence"][1]
    assert evidence["note_id"] == second["note_id"]
    assert evidence["start"] == second["start"] + second["text"].index(SECOND)
    assert evidence["quote"] == SECOND
    duplicate = {**second, "id": "another-position", "start": second["start"] + 10000}
    with pytest.raises(ValueError, match="唯一出现"):
        understanding.ground(value, [first, second, duplicate], {first["note_id"]}, notebook)
    with pytest.raises(ValueError, match="唯一出现"):
        understanding.ground(value, [first], {first["note_id"]}, notebook)


async def test_parallel_units_keep_successes_when_sibling_fails_and_resume(tmp_path, monkeypatch):
    _, notebook = await asyncio.to_thread(setup, tmp_path)
    first = notebook["notes"][0]
    original_records = understanding.memory.records
    original_packs = understanding.synthesis.packs
    monkeypatch.setattr(understanding.memory, "records", lambda reading: original_records(reading) * 4)

    def packs(values, budget=18000):
        if budget == 7000:
            yield from ([v] for v in values)
        else:
            yield from original_packs(values, budget)

    monkeypatch.setattr(understanding.synthesis, "packs", packs)

    class ConcurrentReader(CrossReader):
        def __init__(self):
            super().__init__()
            self.active = self.peak = self.inquiries = 0
            self.fail_once = True

        async def generate(self, request, **kwargs):
            if "查询规划材料：" not in request.prompt:
                return await super().generate(request, **kwargs)
            self.inquiries += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            fail = self.fail_once
            self.fail_once = False
            try:
                await asyncio.sleep(0.02)
                if fail:
                    raise RuntimeError("provider unavailable")
                return await super().generate(request, **kwargs)
            finally:
                self.active -= 1

    reader = ConcurrentReader()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await understanding.understand_notes(tmp_path, reader, [first["id"]], notebook["source_basis"])
    unit_dir = store.root(tmp_path) / "understanding" / "units"
    assert len(await asyncio.to_thread(lambda: list(unit_dir.glob("*.json")))) == 2
    assert reader.peak == 3
    await understanding.understand_notes(tmp_path, reader, [first["id"]], notebook["source_basis"])
    assert reader.inquiries == 5
    assert len(await asyncio.to_thread(lambda: list(unit_dir.glob("*.json")))) == 4
    reports = await asyncio.to_thread(understanding.view, tmp_path)
    assert len(reports["reports"]) == 1
    assert reports["reports"][0]["cursor"] == 4


async def test_read_failure_preserves_cross_chapter_progress(tmp_path, monkeypatch):
    from lib.infra.async_thread import run_noninterruptible_sync
    from lib.novel_workflow import scope
    from lib.novel_workflow.service import read_notes

    project, notebook = await asyncio.to_thread(setup, tmp_path)
    await asyncio.to_thread(
        scope.configure, tmp_path, project, [n["id"] for n in notebook["notes"]], notebook["source_basis"]
    )

    async def failed_understanding(path, *_args):
        await run_noninterruptible_sync(
            store.write, store.root(path) / "progress.json", {"phase": "failed", "done": 3, "total": 31}
        )
        raise ValueError("citation rejected")

    monkeypatch.setattr(understanding, "understand_notes", failed_understanding)
    with pytest.raises(ValueError, match="citation rejected"):
        await read_notes(tmp_path, CrossReader(), [notebook["notes"][0]["id"]], notebook["source_basis"])
    progress = await asyncio.to_thread(lambda: json.loads((store.root(tmp_path) / "progress.json").read_text()))
    assert (progress["phase"], progress["done"], progress["total"]) == ("failed", 3, 31)


def test_subjective_and_annotation_links_cannot_become_confirmed_facts(tmp_path):
    project, notebook = setup(tmp_path)
    fragments = retrieval.index(tmp_path, project, notebook)["fragments"][:2]
    for claim_type, source_kind in [
        ("inference", "narrative"),
        ("statement", "narrative"),
        ("vision", "narrative"),
        ("unverified", "annotation"),
    ]:
        value = Findings.model_validate(
            {
                "links": [
                    {
                        "kind": "identity",
                        "subject": "陌生人",
                        "description": "疑似景麒",
                        "status": "supported",
                        "claim_type": claim_type,
                        "perspective": "阳子",
                        "source_kind": source_kind,
                        "citations": [
                            {"fragment_id": fragments[0]["id"], "quote": FIRST},
                            {"fragment_id": fragments[1]["id"], "quote": SECOND},
                        ],
                    }
                ]
            }
        )
        result = understanding.ground(value, fragments, {notebook["notes"][0]["id"]}, notebook)
        assert result["links"][0]["status"] == "uncertain"
        assert result["links"][0]["revealed_at"]["order"] == 2
