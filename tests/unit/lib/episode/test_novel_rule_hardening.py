import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lib.novel_workflow import condensation, memory, scene_library, store
from lib.novel_workflow.models import Reading
from lib.novel_workflow.scene_models import SceneBatch
from lib.novel_workflow.service import ask, output_schema
from tests.unit.lib.episode.test_novel_workflow import Reader, project
from tests.unit.lib.episode.test_scene_library import scene_output


def test_model_output_requires_explicit_information_class_and_uncertainty_reason():
    raw = {
        "complete": True,
        "summary": "甲取剑",
        "events": [
            {
                "title": "取剑",
                "cause": "未知",
                "conflict": "未知",
                "action": "甲取剑",
                "outcome": "持剑",
                "quote": "甲取剑",
            }
        ],
    }
    # Historical documents remain parseable; newly generated output must not inherit classification defaults.
    assert Reading.model_validate(raw).events[0].claim_type == "unverified"
    with pytest.raises(ValidationError, match="显式填写"):
        Reading.model_validate(raw, context={"model_output": True})
    raw["events"][0].update(claim_type="unverified", source_kind="unknown", perspective="")
    with pytest.raises(ValidationError, match="uncertainty_reason"):
        Reading.model_validate(raw, context={"model_output": True})
    raw["events"][0]["uncertainty_reason"] = "只有人物转述，尚缺原文中的现场行动依据"
    assert Reading.model_validate(raw, context={"model_output": True}).events[0].uncertainty_reason
    required = output_schema(Reading)["$defs"]["Event"]["required"]
    assert {"claim_type", "source_kind", "perspective"} <= set(required)


async def test_omitted_classification_is_repaired_before_generation_can_succeed(tmp_path):
    class Generator:
        attempts = 0

        async def generate(self, request, **_kwargs):
            self.attempts += 1
            claim = {"kind": "character", "name": "甲", "description": "取剑者", "quote": "甲取剑"}
            if self.attempts > 1:
                claim.update(claim_type="fact", source_kind="narrative", perspective="")
            return SimpleNamespace(text=json.dumps({"complete": True, "summary": "取剑", "assets": [claim]}))

    result = await ask(tmp_path, Generator(), Reading, "只读甲取剑")
    assert result.assets[0].claim_type == "fact"
    responses = await asyncio.to_thread(lambda: list((store.root(tmp_path) / "responses").glob("*.json")))
    assert len(responses) == 2


def test_fidelity_change_invalidates_cached_reading_without_hiding_saved_material(tmp_path):
    data, book = project(tmp_path)
    note = book["notes"][0]
    key = store.reading_key(tmp_path, note)
    old = {"basis": "old", "assets": [], "changes": [], "events": [], "questions": [], "summaries": ["旧版已保存"]}
    store.write(store.root(tmp_path) / "notes" / note["id"] / f"{key}.json", old)
    (store.root(tmp_path) / "rules/fidelity.md").write_text("新事实规则，不把梦境当现实")
    assert key != store.reading_key(tmp_path, note)
    assert store.note_result(tmp_path, note) is None
    view = store.view(tmp_path, data)
    assert view["notes"][0]["reading"]["summaries"] == ["旧版已保存"]
    assert view["notes"][0]["status"] == "outdated"


def test_protected_quote_cannot_be_paraphrased_away_by_condensation():
    text = "甲说：我怀疑是他。重复描写。"
    units = condensation.units({"text": text, "start": 0, "end": len(text), "source_file": "book"})
    value = condensation.Edition(
        passages=[condensation.Passage(unit=0, treatment="condense", text="就是他。", reason="压缩")]
    )
    result = condensation.validate(value, units, [{"start": 0, "end": 10}])
    assert result[0]["text"] == text
    assert result[0]["treatment"] == "retain"


def test_off_screen_speaker_is_valid_without_forcing_character_into_frame():
    raw = scene_output("“别动。”")
    segment = raw["scenes"][0]["shots"][0]["segments"][0]
    segment["utterances"] = [{"kind": "dialogue", "delivery": "off_screen", "speaker": "乙", "text": "别动。"}]
    assets = {"character": {"甲", "乙"}, "scene": set(), "prop": set()}
    result = scene_library.ground(SceneBatch.model_validate(raw), {"text": "“别动。”"}, assets, [8])
    assert result["scenes"][0]["shots"][0]["segments"][0]["characters_in_scene"] == ["甲"]
    segment["utterances"][0]["delivery"] = "on_screen"
    with pytest.raises(ValueError, match="画内对白"):
        scene_library.ground(SceneBatch.model_validate(raw), {"text": "“别动。”"}, assets, [8])


async def test_svt_first_batch_receives_whole_chapter_context(tmp_path):
    from lib.novel_workflow.service import generate_svts, read_notes
    from tests.unit.lib.episode.test_novel_workflow import SVTReader

    _, book = await asyncio.to_thread(project, tmp_path)
    note = book["notes"][0]
    await read_notes(tmp_path, Reader(), [note["id"]], book["source_basis"])

    class DirectionReader(SVTReader):
        async def generate(self, request, **kwargs):
            direction = json.loads(request.prompt.split("整章方向材料：", 1)[1].split("\n必须覆盖的本批事件ID", 1)[0])
            assert direction["overview"]["summary"]
            assert direction["index"]["events"][0]["title"] == "甲拿起古剑。"
            return await super().generate(request, **kwargs)

    await generate_svts(tmp_path, DirectionReader(), [note["id"]], book["source_basis"])
    svts = await asyncio.to_thread(lambda: json.loads((store.root(tmp_path) / "svts.json").read_text()))
    assert note["id"] in svts["note_assignments"]


def test_memory_retains_stable_old_state_and_does_not_apply_unverified_alias(tmp_path):
    _, book = project(tmp_path)
    from lib.novel_workflow.models import Reading
    from lib.novel_workflow.service import ground

    note = book["notes"][0]
    quote = "甲拿起古剑。"
    result = ground(
        Reading(
            complete=True,
            summary=quote,
            assets=[{"kind": "character", "name": "甲", "description": "取剑者", "quote": quote}],
            aliases=[{"name": "乙", "alias": "甲", "quote": quote}],
        ),
        {"note_id": note["id"], "source_file": "source/book.txt", "start": 0, "text": quote},
    )
    key = store.reading_key(tmp_path, note)
    store.write(store.root(tmp_path) / "notes" / note["id"] / f"{key}.json", {**result, "basis": key})
    ledger = memory.ledger(tmp_path, book)
    assert ledger["characters"][0]["name"] == "甲"
    assert ledger["aliases"] == []


async def test_current_chapter_revelation_is_usable_only_after_its_source_position(tmp_path):
    from lib.novel_workflow import understanding
    from tests.unit.lib.episode.test_cross_chapter_understanding import CrossReader, setup

    _, book = await asyncio.to_thread(setup, tmp_path)
    first, second, _ = book["notes"]
    await understanding.understand_notes(tmp_path, CrossReader(), [first["id"]], book["source_basis"])
    value = await asyncio.to_thread(understanding.view, tmp_path)
    offset = value["links"][0]["revealed_at"]["offset"]
    early = await asyncio.to_thread(
        understanding.production_context, tmp_path, [second["id"]], source_offset=offset - 1
    )
    later = await asyncio.to_thread(
        understanding.production_context, tmp_path, [second["id"]], source_offset=offset + 1
    )
    assert early["links"] == []
    assert later["links"][0]["id"] == value["links"][0]["id"]


async def test_conflicting_cross_chapter_drafts_are_reconciled_and_cached(tmp_path):
    from copy import deepcopy

    from lib.novel_workflow import retrieval, understanding
    from lib.novel_workflow.understanding_models import Findings
    from lib.novel_workflow.understanding_reconcile import reconcile
    from tests.unit.lib.episode.test_cross_chapter_understanding import FIRST, SECOND, setup

    project_data, book = await asyncio.to_thread(setup, tmp_path)
    fragments = await asyncio.to_thread(retrieval.index, tmp_path, project_data, book)
    left, right = fragments["fragments"][:2]
    draft = {
        "kind": "identity",
        "subject": "陌生人",
        "description": "身份关联",
        "status": "supported",
        "claim_type": "fact",
        "source_kind": "narrative",
        "perspective": "",
        "citations": [{"fragment_id": left["id"], "quote": FIRST}, {"fragment_id": right["id"], "quote": SECOND}],
    }
    link = understanding.ground(Findings.model_validate({"links": [draft]}), [left, right], {left["note_id"]}, book)[
        "links"
    ][0]
    conflicting = {**deepcopy(link), "description": "另一批得出有冲突的身份结论"}

    class Generator:
        calls = 0

        async def generate(self, request, **_kwargs):
            self.calls += 1
            material = json.loads(request.prompt.split("关联汇总材料：", 1)[1].split("\n只输出 JSON", 1)[0])
            refs = material["fragments"]
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "links": [
                            {
                                **draft,
                                "kind": "contradiction",
                                "status": "uncertain",
                                "description": "两批身份结论冲突，应回查",
                                "citations": [{"fragment_id": f["id"], "quote": f["quote"]} for f in refs],
                            }
                        ]
                    }
                )
            )

    generator = Generator()
    original = [link, conflicting]
    result, _ = await reconcile(tmp_path, generator, original, book, {left["note_id"]})
    again, _ = await reconcile(tmp_path, generator, original, book, {left["note_id"]})
    assert len(result) == 1
    assert result[0]["status"] == "uncertain"
    assert result == again
    assert generator.calls == 1
    assert original[0]["status"] == "supported"
    assert len(original) == 2


async def test_review_failure_resumes_saved_extraction_without_repeating_paid_extraction(tmp_path):
    from lib.novel_workflow.service import read_notes

    _, book = await asyncio.to_thread(project, tmp_path)
    note = book["notes"][0]

    class FailingReviewer(Reader):
        fail = True

        async def generate(self, request, **kwargs):
            if self.fail and "抽取审核材料：" in request.prompt:
                self.fail = False
                raise RuntimeError("temporary review provider failure")
            return await super().generate(request, **kwargs)

    generator = FailingReviewer()
    with pytest.raises(RuntimeError, match="temporary review"):
        await read_notes(tmp_path, generator, [note["id"]], book["source_basis"])
    assert generator.calls == 1
    await read_notes(tmp_path, generator, [note["id"]], book["source_basis"])
    result = await asyncio.to_thread(store.note_result, tmp_path, note)
    assert result["events"][0]["evidence"]["quote"] == "甲拿起古剑。"
    # One original extraction plus one synthesis; the failed audit did not repeat extraction.
    assert generator.calls == 2


def test_rule_change_keeps_historical_edition_browsable_without_reusing_it_for_production(tmp_path):
    from lib.novel_workflow import condensation

    reading = {"basis": "reading-v1"}
    note = {"id": "note-1"}
    key = condensation.edition_key(reading, store.effective_rule(tmp_path, "condense"))
    old = {
        "reading_basis": reading["basis"],
        "basis": key,
        "parts": [],
        "created_at": "2026-11-11",
        "original_chars": 100,
        "edited_chars": 80,
    }
    store.write(store.root(tmp_path) / "editions" / note["id"] / f"{key}.json", old)
    (store.root(tmp_path) / "rules").mkdir(exist_ok=True)
    (store.root(tmp_path) / "rules/condense.md").write_text("新的精简规则")
    assert condensation.load(tmp_path, note, reading) is None
    assert condensation.load(tmp_path, note, reading, history=True) == old
    assert condensation.metadata(tmp_path, note, reading)["edited_chars"] == 80


def test_repeated_short_dialogue_requires_unique_context_and_keeps_only_spoken_words():
    from lib.novel_workflow.service import claim_evidence

    text = "甲摇头说：『我不要。』乙随后喊：『我不要。』"
    part = {"text": text, "start": 100, "source_file": "book", "note_id": "n1"}
    with pytest.raises(ValueError, match="context_quote"):
        claim_evidence(part, {"quote": "『我不要。』"})
    resolved = claim_evidence(part, {"quote": "『我不要。』", "context_quote": "乙随后喊：『我不要。』"})
    assert resolved["start"] == 100 + text.rindex("『我不要。』")
    assert resolved["quote"] == "『我不要。』"
    with pytest.raises(ValueError, match="唯一"):
        claim_evidence(part, {"quote": "『我不要。』", "context_quote": text})


async def test_ambiguous_citation_uses_small_source_choice_and_keeps_extraction_text(tmp_path):
    from lib.novel_workflow.models import Reading
    from lib.novel_workflow.quote_locations import resolve
    from lib.novel_workflow.service import ground

    text = "甲回头说：『不要。』乙走远后喊：『不要。』"
    reading = Reading(
        complete=True,
        summary="甲乙说话",
        events=[
            {
                "title": "乙走远后拒绝",
                "cause": "未知",
                "conflict": "未知",
                "action": "乙拒绝",
                "outcome": "未知",
                "quote": "乙走远后喊：『不要。』",
                "dialogues": [{"speaker": "乙", "quote": "『不要。』", "value": "拒绝"}],
            }
        ],
    )
    part = {"text": text, "start": 0, "source_file": "book", "note_id": "n1"}

    class Locator:
        calls = 0

        async def generate(self, request, **_kwargs):
            self.calls += 1
            batch = json.loads(request.prompt.split("引用定位候选：", 1)[1].split("\n只输出 JSON", 1)[0])
            options = batch[0]["candidates"]
            chosen = next(v for v in options if "乙走远后喊：『不要。』" in v["context_quote"])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "locations": [
                            {
                                "record_id": batch[0]["record_id"],
                                "candidate_id": chosen["id"],
                                "reason": "乙走远后发言的上下文",
                            }
                        ]
                    }
                )
            )

    generator = Locator()
    await resolve(tmp_path, generator, reading, part)
    result = ground(reading, part)
    utterance = result["events"][0]["dialogues"][0]
    assert utterance["quote"] == "『不要。』"
    assert utterance["evidence"]["start"] == text.rindex("『不要。』")
    assert result["events"][0]["action"] == "乙拒绝"
    assert generator.calls == 1
