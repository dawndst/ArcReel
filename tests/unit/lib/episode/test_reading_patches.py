import json
from copy import deepcopy

import pytest

from lib.novel_workflow.models import Reading
from lib.novel_workflow.reading_patches import BUCKETS, ReviewEdits, apply, material


def draft():
    return Reading(complete=True, summary="原摘要", questions=["甲", "乙", "丙"]).model_dump()


def review(value, edits=()):
    return ReviewEdits(
        snapshot=material(value)["snapshot"], complete=True, reviewed_sections=["summary", *BUCKETS], edits=list(edits)
    )


def test_no_changes_preserves_all_data_and_input():
    value = draft()
    before = deepcopy(value)
    assert apply(value, review(value)).model_dump() == value == before


def test_edits_use_original_indices_and_do_not_mutate_source():
    value = draft()
    result = apply(
        value,
        review(
            value,
            [
                {"operation": "remove", "target": "questions.0", "reason": "没有依据"},
                {"operation": "replace", "target": "questions.2", "reason": "澄清疑问", "value_json": json.dumps("丁")},
                {"operation": "append", "target": "questions", "reason": "原文遗漏", "value_json": json.dumps("戊")},
            ],
        ),
    )
    assert result.questions == ["乙", "丁", "戊"]
    assert value["questions"] == ["甲", "乙", "丙"]


@pytest.mark.parametrize(
    "edit",
    [
        {"operation": "replace", "target": "questions.9", "value_json": '"甲"'},
        {"operation": "append", "target": "arbitrary", "value_json": '"甲"'},
        {"operation": "replace", "target": "complete", "value_json": "false"},
        {"operation": "replace", "target": "summary", "value_json": '{"evidence": {}}'},
        {"operation": "append", "target": "assets", "value_json": "{}"},
    ],
)
def test_invalid_patch_never_returns_partial_result(edit):
    value = draft()
    with pytest.raises(ValueError, match=r".+"):
        apply(value, review(value, [{**edit, "reason": "测试拒绝非法修改"}]))
    assert value == draft()


def test_snapshot_completeness_and_duplicate_targets_are_checked():
    value = draft()
    r = review(value)
    r.snapshot = "outdated"
    with pytest.raises(ValueError, match="版本"):
        apply(value, r)
    r = review(value)
    r.reviewed_sections.pop()
    with pytest.raises(ValueError, match="全部栏目"):
        apply(value, r)
    edit = {"operation": "remove", "target": "questions.0", "reason": "无依据"}
    with pytest.raises(ValueError, match="只能修改一次"):
        apply(value, review(value, [edit, edit]))


@pytest.mark.asyncio
async def test_patch_review_still_grounds_against_original_source(tmp_path, monkeypatch):
    from lib.novel_workflow import reading_audit, service

    source = "甲拿起剑。"
    part = {"note_id": "n", "source_file": "source/book.txt", "start": 10, "text": source}
    raw = Reading(
        complete=True,
        summary="取剑",
        assets=[
            {
                "kind": "prop",
                "claim_type": "fact",
                "source_kind": "narrative",
                "name": "剑",
                "description": "被拿起",
                "quote": source,
            }
        ],
    )
    extracted = service.ground(raw, part)
    original = deepcopy(extracted)

    async def fake_ask(path, generator, schema, prompt, validate, **kwargs):
        assert schema is ReviewEdits
        assert "局部修订" in prompt
        return await validate(review(reading_audit.draft_claims(extracted)))

    monkeypatch.setattr(service, "ask", fake_ask)
    result = await reading_audit.audit(tmp_path, object(), extracted, part, set(), set())
    assert result == original == extracted


@pytest.mark.asyncio
async def test_patched_quote_cannot_bypass_grounding(tmp_path, monkeypatch):
    from lib.novel_workflow import reading_audit, service

    part = {"note_id": "n", "source_file": "source/book.txt", "start": 0, "text": "甲拿起剑。"}
    extracted = service.ground(
        Reading(
            complete=True,
            summary="取剑",
            assets=[
                {
                    "kind": "prop",
                    "claim_type": "fact",
                    "source_kind": "narrative",
                    "name": "剑",
                    "description": "被拿起",
                    "quote": part["text"],
                }
            ],
        ),
        part,
    )

    async def fake_ask(path, generator, schema, prompt, validate, **kwargs):
        raw = reading_audit.draft_claims(extracted)
        replacement = {**raw["assets"][0], "quote": "甲把剑送给乙。"}
        return await validate(
            review(
                raw,
                [
                    {
                        "operation": "replace",
                        "target": "assets.0",
                        "value_json": json.dumps(replacement),
                        "reason": "测试伪造引文必须被拒绝",
                    }
                ],
            )
        )

    monkeypatch.setattr(service, "ask", fake_ask)
    with pytest.raises(ValueError, match="不是逐字原文"):
        await reading_audit.audit(tmp_path, object(), extracted, part, set(), set())
