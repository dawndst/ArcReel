import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import svt_material as material
from lib.novel_workflow.models import SVTBatch


def inputs():
    span = {"source_file": "book", "start": 0, "end": 10, "quote": "原文十个字符完整证据"}
    events = [
        {
            "id": f"e{i}",
            "note_id": "n",
            "title": "事件",
            "action": "行动",
            "claim_type": "fact",
            "evidence": span,
            "dialogues": [{"id": f"d{i}", "speaker": "甲", "quote": "完整原句" * 400, "value": "决定"}],
        }
        for i in range(2)
    ]
    edition = {"parts": [{"passages": [{"text": "共享精简段落", "treatment": "condense", "evidence": span}]}]}
    return events, edition


def test_shared_prose_and_exact_dialogue_with_complete_event_index():
    events, edition = inputs()
    result = material.prepare(events, edition)
    assert len(result["edition_passages"]) == 1
    assert [e["id"] for e in result["events"]] == ["e0", "e1"]
    assert result["events"][0]["passage_ids"] == result["events"][1]["passage_ids"]
    assert result["original_dialogues"][0]["quote"] == events[0]["dialogues"][0]["quote"]
    assert result["source_excerpts"] == []
    assert "evidence" not in result["events"][0]


def test_omitted_gapped_and_uncertain_material_falls_back_without_losing_event():
    events, edition = inputs()
    passage = edition["parts"][0]["passages"][0]
    for change in [
        {"text": "", "treatment": "omit"},
        {"treatment": "uncertain"},
        {"evidence": {"source_file": "book", "start": 2, "end": 10}},
    ]:
        altered = {"parts": [{"passages": [{**passage, **change}]}]}
        result = material.prepare(events, altered)
        assert len(result["source_excerpts"]) == 2
        assert result["source_excerpts"][0]["evidence"] == events[0]["evidence"]
    events[0]["claim_type"] = "inference"
    assert len(material.prepare(events, edition)["source_excerpts"]) == 1


@pytest.mark.asyncio
async def test_source_request_is_local_and_only_final_validated_result_is_returned(tmp_path, monkeypatch):
    from lib.novel_workflow import service

    events, edition = inputs()
    prompts = []

    async def ask(path, generator, schema, prompt, validate):
        prompts.append(prompt)
        if len(prompts) == 1:
            with pytest.raises(ValueError, match="本批"):
                validate(material.Proposal(source_requests=["future-event"]))
            return validate(material.Proposal(source_requests=["e1"]))
        assert schema is SVTBatch
        narrative = json.loads(prompt.split("精简稿与原句：", 1)[1].split("\n必须覆盖", 1)[0])
        assert [s["event_id"] for s in narrative["source_excerpts"]] == ["e1"]
        return validate(SVTBatch())

    monkeypatch.setattr(service, "ask", ask)
    result, stats = await material.generate(
        tmp_path, SimpleNamespace(), "rule", {}, events, edition, [], lambda v: {"checked": True}
    )
    assert result == {"checked": True}
    assert stats["source_requests"] == ["e1"]
    assert len(prompts) == 2
