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


async def test_bounded_output_growth_preserves_prompt_and_does_not_change_reading_split_policy(tmp_path):
    import json
    from types import SimpleNamespace

    from lib.backends.text_backends.base import TextOutputTruncatedError
    from lib.novel_workflow.service import ask
    from lib.novel_workflow.understanding_models import Findings

    class Generator:
        max_output_tokens = 24000

        def __init__(self):
            self.requests = []

        async def generate(self, request, **kwargs):
            self.requests.append(request)
            if request.max_output_tokens < self.max_output_tokens:
                raise TextOutputTruncatedError(provider="test", model="test", output_tokens=12000)
            return SimpleNamespace(text=json.dumps({"links": [], "unresolved": ["仍待回查"], "next_queries": []}))

    generator = Generator()
    result = await ask(tmp_path, generator, Findings, "完整材料", grow_output=True)
    assert result.unresolved == ["仍待回查"]
    assert [r.max_output_tokens for r in generator.requests] == [12000, 24000]
    assert generator.requests[0].prompt == generator.requests[1].prompt
    with pytest.raises(TextOutputTruncatedError):
        await ask(tmp_path, Generator(), Findings, "普通请求")
    capped = Generator()
    capped.max_output_tokens = 12000

    async def truncated(request, **kwargs):
        raise TextOutputTruncatedError(provider="test", model="test", output_tokens=12000)

    capped.generate = truncated
    with pytest.raises(TextOutputTruncatedError):
        await ask(tmp_path, capped, Findings, "注册上限", grow_output=True)


def test_reading_keeps_subjective_claims_and_does_not_default_to_facts():
    value = Reading(
        complete=True,
        summary="疑似故人",
        events=[
            {
                "title": "阳子疑似见到景麒",
                "cause": "",
                "conflict": "",
                "action": "看不清脸",
                "outcome": "身份未确认",
                "quote": "说不定是阳子自己看错人了。",
                "claim_type": "inference",
                "perspective": "阳子",
                "source_kind": "narrative",
            }
        ],
    )
    result = ground(value, {"text": "说不定是阳子自己看错人了。", "start": 0, "note_id": "n2", "source_file": "book"})
    assert result["events"][0]["claim_type"] == "inference"
    assert result["events"][0]["perspective"] == "阳子"
    from lib.novel_workflow.models import Event

    old = Event(title="旧资料", cause="", conflict="", action="", outcome="", quote="旧引文")
    assert old.claim_type == "unverified"


async def test_output_growth_is_available_after_two_validation_repairs(tmp_path):
    from types import SimpleNamespace

    from lib.backends.text_backends.base import TextOutputTruncatedError
    from lib.novel_workflow.service import ask
    from lib.novel_workflow.understanding_models import Findings

    class Generator:
        max_output_tokens = 48000

        def __init__(self):
            self.calls = []

        async def generate(self, request, **kwargs):
            self.calls.append(request.max_output_tokens)
            if len(self.calls) <= 2:
                return SimpleNamespace(text='{"unknown": true}')
            if request.max_output_tokens < 48000:
                raise TextOutputTruncatedError(provider="test", model="test", output_tokens=request.max_output_tokens)
            return SimpleNamespace(text='{"links": [], "unresolved": ["保留疑点"]}')

    generator = Generator()
    result = await ask(tmp_path, generator, Findings, "原文", max_output_tokens=24000, grow_output=True)
    assert result.unresolved == ["保留疑点"]
    assert generator.calls == [24000, 24000, 24000, 48000]


def test_scene_excerpt_expansion_restores_omitted_source_and_rejects_ambiguity():
    from lib.novel_workflow.evidence import expand_scene_excerpt

    source = "甲开门。中间有重要否定：并不是景麒。乙离开。"
    start, end = expand_scene_excerpt(source, "甲开门。……乙离开。")
    assert source[start:end] == source
    with pytest.raises(ValueError, match="唯一"):
        expand_scene_excerpt(source, "甲踢门。……乙离开。")
    with pytest.raises(ValueError, match="唯一"):
        expand_scene_excerpt(source + "乙离开。", "甲开门。……乙离开。")
    with pytest.raises(ValueError, match="唯一"):
        locate(source, "甲开门。……乙离开。")


def test_asset_identity_anchor_cannot_reference_unsupplied_or_future_records():
    value = Reading(
        summary="阳子回头",
        complete=True,
        assets=[
            {
                "kind": "character",
                "name": "阳子",
                "description": "回头",
                "quote": "阳子回头",
                "same_entity_as": "earlier-asset",
            }
        ],
    )
    part = {"text": "阳子回头", "start": 0, "note_id": "n", "source_file": "book"}
    with pytest.raises(ValueError, match="supplied earlier asset"):
        ground(value, part)
    assert ground(value, part, identity_ids={"earlier-asset"})["assets"][0]["same_entity_as"] == "earlier-asset"
