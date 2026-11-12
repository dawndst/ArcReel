import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lib.novel_workflow import review, store
from lib.novel_workflow.models import ScopeReview


def advice(ids, action="keep"):
    return {
        "action": action,
        "note_ids": ids,
        "evidence_ids": [f"e-{i}" for i in set(ids)],
        "reason": "原因",
        "character_impact": "人物",
        "thread_impact": "线索",
        "dialogue_impact": "对白",
        "preserve": "行动",
    }


def test_single_note_schema_disallows_combine_and_validation_rejects_duplicate_ids():
    value = {"theme": "主题", "mainline": "主线", "advice": [advice(["a"], "combine")]}
    with pytest.raises(ValidationError):
        review.SingleNoteReview.model_validate(value)
    value["advice"] = [advice(["a", "a"], "combine")]
    with pytest.raises(ValueError, match="must not repeat"):
        review.validate(ScopeReview.model_validate(value), {"e-a": {"evidence": {"note_id": "a"}}}, {"a"})


@pytest.mark.parametrize("reject", [False, True])
async def test_cross_note_advice_keeps_all_owners_and_progress_records_every_stage(tmp_path, monkeypatch, reject):
    from lib.novel_workflow import service, understanding

    notes = [{"id": i, "title": i} for i in ["a", "b"]]
    notebook = {"notes": notes, "source_basis": "source"}
    readings = {
        i: {"basis": i, "overview": {"summary": i}, "events": [{"id": f"e-{i}", "evidence": {"note_id": i}}]}
        for i in ["a", "b"]
    }
    monkeypatch.setattr(understanding, "require_understood", lambda *args: None)
    monkeypatch.setattr(service, "current", lambda *args: notebook)
    monkeypatch.setattr(store, "note_result", lambda path, note: readings[note["id"]])
    stages = []

    class Generator:
        async def generate(self, request, **kwargs):
            progress = json.loads(await asyncio.to_thread((store.root(tmp_path) / "progress.json").read_text))
            assert progress["phase"] == "review"
            stages.append(progress["step"])
            if reject:
                return SimpleNamespace(
                    text=json.dumps({"theme": "主题", "mainline": "主线", "advice": [advice(["outside"])]})
                )
            if "范围总览材料：" in request.prompt:
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "theme": "主题",
                            "mainline": "主线",
                            "must_preserve": "行动",
                            "adaptation_risks": "风险",
                            "evidence_ids": ["e-a", "e-b"],
                        }
                    )
                )
            if "汇总已完成的取舍分析" in request.prompt:
                nodes = json.JSONDecoder().raw_decode(
                    request.prompt.split("汇总已完成的取舍分析，检查跨章因果与组合建议：", 1)[1]
                )[0]
                assert set(nodes[0]["note_ids"]) == {"a", "b"}
                assert set(nodes[0]["evidence_ids"]) == {"e-a", "e-b"}
            return SimpleNamespace(
                text=json.dumps({"theme": "主题", "mainline": "主线", "advice": [advice(["a", "b"], "combine")]})
            )

    if reject:
        with pytest.raises(ValueError, match="outside this range"):
            await review.review_scope(tmp_path, Generator(), ["a", "b"], "source")
        progress = json.loads(await asyncio.to_thread((store.root(tmp_path) / "progress.json").read_text))
        assert progress["phase"] == "failed"
        assert "outside this range" in progress["error"]
        assert stages == ["analysis"] * 3
        return
    await review.review_scope(tmp_path, Generator(), ["a", "b"], "source")
    assert stages == ["analysis", "overview", "conclusion"]
    progress = json.loads(await asyncio.to_thread((store.root(tmp_path) / "progress.json").read_text))
    assert progress["phase"] == "complete"
    assert progress["done"] == progress["total"]
