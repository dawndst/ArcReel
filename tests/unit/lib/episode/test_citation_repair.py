import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow.citation_repair import candidates, repair
from lib.novel_workflow.understanding import ground
from lib.novel_workflow.understanding_models import Findings


def test_candidates_preserve_reader_annotation_and_literal_source():
    text = "树林里有人。（读者插话：猜猜是谁）\n\n──景麒。\n\n她仍未看清。"
    options = candidates(text)
    assert options["0"] == "树林里有人。（读者插话：猜猜是谁）"
    assert options["1"] == "──景麒。"
    assert all(quote in text for quote in options.values())


async def test_repair_selects_source_paragraph_without_changing_claim_or_certainty(tmp_path):
    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(text=json.dumps({"candidate_ids": ["0", "1"], "reason": "保留插话并分开引用"}))

    source = "树林里有人。（读者插话：猜猜是谁）\n\n──景麒。"
    fragments = [
        {"id": "a", "note_id": "n1", "source_file": "book", "start": 20, "text": source},
        {"id": "b", "note_id": "n2", "source_file": "book", "start": 100, "text": "未看清人影。"},
    ]
    value = Findings(
        links=[
            {
                "kind": "identity",
                "subject": "人影",
                "description": "疑似景麒，尚未确认",
                "status": "uncertain",
                "claim_type": "statement",
                "perspective": "阳子",
                "source_kind": "narrative",
                "citations": [
                    {"fragment_id": "a", "quote": "树林里有人。──景麒。"},
                    {"fragment_id": "b", "quote": "未看清人影。"},
                ],
            }
        ]
    )
    result = await repair(tmp_path, Generator(), value, fragments)
    assert len(result.links[0].citations) == 3
    notebook = {"notes": [{"id": "n1", "order": 1}, {"id": "n2", "order": 2}]}
    grounded = ground(result, fragments, {"n1"}, notebook)["links"][0]
    assert grounded["description"] == "疑似景麒，尚未确认"
    assert grounded["status"] == "uncertain"
    assert grounded["claim_type"] == "statement"
    assert grounded["evidence"][0]["quote"] == "树林里有人。（读者插话：猜猜是谁）"
    assert grounded["evidence"][0]["start"] == 20


async def test_repair_refuses_unsupported_or_invented_candidates(tmp_path):
    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(text=json.dumps({"candidate_ids": ["invented"], "reason": "没有依据"}))

    value = Findings(
        links=[
            {
                "kind": "identity",
                "subject": "人影",
                "description": "待查",
                "status": "uncertain",
                "citations": [
                    {"fragment_id": "a", "quote": "不存在的句子"},
                    {"fragment_id": "b", "quote": "未看清人影。"},
                ],
            }
        ]
    )
    with pytest.raises(ValueError, match="原文不足以支持"):
        await repair(
            tmp_path,
            Generator(),
            value,
            [
                {"id": "a", "text": "树林里有人。"},
                {"id": "b", "text": "未看清人影。"},
            ],
        )


async def test_unverifiable_link_becomes_pending_without_losing_verified_sibling(tmp_path):
    import asyncio

    from lib.novel_workflow import store
    from lib.novel_workflow.citation_repair import verify

    class NoModel:
        async def generate(self, request, **kwargs):
            raise AssertionError("Literal grounding and unavailable source IDs do not need model calls")

    fragments = [
        {"id": "a", "note_id": "n1", "source_file": "book", "start": 20, "text": "紫衣人站在门边。"},
        {"id": "b", "note_id": "n2", "source_file": "book", "start": 100, "text": "紫衣人就是景麒。"},
    ]
    valid = {
        "kind": "identity",
        "subject": "紫衣人",
        "description": "身份已揭示",
        "status": "supported",
        "claim_type": "fact",
        "perspective": "",
        "source_kind": "narrative",
        "citations": [
            {"fragment_id": "typo", "quote": "紫衣人站在门边。"},
            {"fragment_id": "b", "quote": "紫衣人就是景麒。"},
        ],
    }
    invalid = {
        **valid,
        "description": "原文未提供的身份说法",
        "citations": [
            {"fragment_id": "unavailable", "quote": "虚构的身份依据。"},
            {"fragment_id": "b", "quote": "紫衣人就是景麒。"},
        ],
    }
    result = await verify(
        tmp_path,
        NoModel(),
        Findings(links=[valid, invalid]),
        fragments,
        {"n1"},
        {
            "notes": [{"id": "n1", "order": 1}, {"id": "n2", "order": 2}],
        },
    )
    assert len(result["links"]) == 1
    assert result["links"][0]["status"] == "supported"
    assert result["links"][0]["evidence"][0]["start"] == 20
    assert any("原文未提供的身份说法" in q for q in result["unresolved"])
    files = await asyncio.to_thread(
        lambda: list((store.root(tmp_path) / "understanding/citation_reviews").glob("*.json"))
    )
    assert len(files) == 1
    pending = json.loads(await asyncio.to_thread(files[0].read_text))
    assert pending["claim"]["description"] == "原文未提供的身份说法"
    assert pending["source_fragments"] == fragments
    assert pending["status"] == "unresolved"
