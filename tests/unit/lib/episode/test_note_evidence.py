import pytest

from lib.novel_workflow.evidence import locate
from lib.novel_workflow.models import Reading
from lib.novel_workflow.service import ground


def test_epub_whitespace_restores_exact_source_span_and_fact_quote():
    text = "开头。导师倒地。\n\n\u00a0\u00a0阳子回头。结尾。"
    quote = "导师倒地。阳子回头。"
    start, end = locate(text, quote)
    assert text[start:end] == "导师倒地。\n\n\u00a0\u00a0阳子回头。"
    value = Reading(
        summary="阳子回头",
        complete=True,
        assets=[{"kind": "character", "name": "阳子", "description": "回头", "quote": quote}],
    )
    result = ground(value, {"text": text, "start": 100, "note_id": "n1", "source_file": "book.txt"})
    asset = result["assets"][0]
    assert asset["quote"] == asset["evidence"]["quote"] == text[start:end]
    assert (asset["evidence"]["start"], asset["evidence"]["end"]) == (100 + start, 100 + end)


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("她拾起剑。", "她拔出剑。"),
        ("甲说话。乙离开。丙回头。", "甲说话。丙回头。"),
        ("甲说话。乙离开。丙回头。", "甲说话。……丙回头。"),
        ("甲\n乙。甲\n乙。", "甲乙"),
        ("甲乙。", " \n "),
    ],
)
def test_normalization_rejects_paraphrase_splicing_ambiguity_and_empty_quotes(text, quote):
    with pytest.raises(ValueError, match="唯一出现"):
        locate(text, quote)


def test_partial_dialogue_wrapper_does_not_extend_or_rewrite_original():
    text = "『我不能抛弃主人。现在走。』"
    start, end = locate(text, "『我不能抛弃主人。』")
    assert text[start:end] == "我不能抛弃主人。"
    with pytest.raises(ValueError, match="唯一出现"):
        locate(text, "『我不会抛弃主人。』")


async def test_chapter_summary_accepts_supplied_dialogue_as_parent_event_evidence(tmp_path):
    import json
    from types import SimpleNamespace

    from lib.novel_workflow.synthesis import chapter

    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "summary": "人物求救",
                        "cause": "遇险",
                        "conflict": "受困",
                        "action": "求救",
                        "outcome": "待救",
                        "hook": "能否脱险",
                        "questions": [],
                        "evidence_ids": ["dialogue-1"],
                    }
                )
            )

    extracted = [
        {"summary": "求救", "events": [{"id": "event-1", "dialogues": [{"id": "dialogue-1", "quote": "救我"}]}]}
    ]
    result = await chapter(tmp_path, Generator(), extracted, "按原文归纳")
    assert result["evidence_ids"] == ["event-1"]
