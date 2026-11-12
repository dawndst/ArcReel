import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import chapters, store
from lib.novel_workflow.models import SVTBatch
from lib.novel_workflow.service import generate_svts, read_notes, validate_svt


def project(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source/book.txt").write_text("# 第一章\n甲拿起古剑。\n# 第二章\n乙推开城门。\n")
    data = {"whole_source_files": [{"source_file": "source/book.txt"}]}
    (tmp_path / "project.json").write_text(json.dumps(data))
    preview = chapters.index(tmp_path, data)
    from lib.novel_workflow.settings import update

    update(tmp_path, {"understanding_enabled": False})
    return data, store.initialize(tmp_path, data, preview["source_basis"])


class Reader:
    def __init__(self):
        self.calls = 0

    async def generate(self, request, **kwargs):
        if "# 章节精编与原文回读" in request.prompt:
            payload = json.JSONDecoder().raw_decode(request.prompt[request.prompt.index('{"source_units":') :])[0]
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "passages": [
                            {"unit": u["unit"], "treatment": "retain", "text": u["text"], "reason": "测试保留原文"}
                            for u in payload["source_units"]
                        ]
                    }
                )
            )
        if "抽取审核材料：" in request.prompt:
            payload = json.JSONDecoder().raw_decode(request.prompt.split("抽取审核材料：", 1)[1])[0]
            return SimpleNamespace(text=json.dumps(payload["draft"]))
        self.calls += 1
        if "章节材料：" in request.prompt:
            nodes = json.loads(request.prompt.split("章节材料：", 1)[1].split("\n只输出 JSON", 1)[0])
            ids = [r["id"] for n in nodes for r in n["records"]]
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "summary": "人物完成行动，结果明确。",
                        "cause": "未明",
                        "conflict": "未明",
                        "action": "完成行动",
                        "outcome": "动作完成",
                        "hook": "未明",
                        "evidence_ids": ids,
                    },
                    ensure_ascii=False,
                )
            )
        text = json.loads(request.prompt.split("\n", 1)[1])["source"]
        quote = "甲拿起古剑。" if "甲拿起古剑。" in text else "乙推开城门。"
        return SimpleNamespace(
            text=json.dumps(
                {
                    "complete": True,
                    "summary": quote,
                    "assets": [
                        {
                            "claim_type": "fact",
                            "source_kind": "narrative",
                            "perspective": "",
                            "kind": "character",
                            "name": quote[0],
                            "description": "原文明示行为",
                            "quote": quote,
                        }
                    ],
                    "changes": [],
                    "events": [
                        {
                            "title": quote,
                            "claim_type": "fact",
                            "source_kind": "narrative",
                            "perspective": "",
                            "cause": "未明",
                            "conflict": "未明",
                            "action": quote,
                            "outcome": "动作完成",
                            "quote": quote,
                        }
                    ],
                    "questions": [],
                },
                ensure_ascii=False,
            )
        )


class SVTReader:
    async def generate(self, request, **kwargs):
        events = json.loads(request.prompt.split("本批事件：", 1)[1].split("\n可续接SVT：", 1)[0])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "svts": [
                        {
                            "title": events[0]["title"],
                            "summary": events[0]["action"],
                            "event_ids": [e["id"] for e in events],
                            "mainline_reason": "本集行动",
                            "status": "open",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )


async def test_reading_is_cached_and_partial_reread_preserves_other_notes(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    reader = Reader()
    await read_notes(tmp_path, reader, ids, index["source_basis"])
    assert reader.calls == 4
    await read_notes(tmp_path, reader, [ids[0]], index["source_basis"])
    assert reader.calls == 4
    view = await asyncio.to_thread(store.view, tmp_path, data)
    assert [n["status"] for n in view["notes"]] == ["read", "read"]
    assert view["notes"][0]["reading"]["events"][0]["evidence"]["quote"] == "甲拿起古剑。"


async def test_svt_generation_for_second_scope_preserves_first_scope(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), ids, index["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[0]], index["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[1]], index["source_basis"])
    view = await asyncio.to_thread(store.view, tmp_path, data)
    assert len(view["svts"]) == 2
    assert {svt["title"] for svt in view["svts"]} == {"甲拿起古剑。", "乙推开城门。"}
    assert not view["groups"]


def test_manual_group_preserves_notes_and_can_be_dissolved(tmp_path):
    data, index = project(tmp_path)
    notes = index["notes"]
    group = store.group_notes(tmp_path, data, [n["id"] for n in notes], "改编组合", index["source_basis"])
    assert store.state(tmp_path)["notes"] == notes
    assert group["created_by"] == "human"
    store.dissolve_group(tmp_path, group["id"])
    assert store.state(tmp_path)["groups"] == []
    assert store.state(tmp_path)["notes"] == notes


def test_svt_cannot_invent_events_or_silently_omit_current_events():
    batch = SVTBatch(svts=[], supporting_event_ids=["not-provided"])
    with pytest.raises(ValueError, match="Unknown"):
        validate_svt(batch, {"current"}, {"current"}, set(), set())
    with pytest.raises(ValueError, match="not classified"):
        validate_svt(SVTBatch(), {"current"}, {"current"}, set(), set())


class ContinuingSVTReader:
    def __init__(self):
        self.supplied = []

    async def generate(self, request, **kwargs):
        events = json.loads(request.prompt.split("本批事件：", 1)[1].split("\n可续接SVT：", 1)[0])
        old = json.loads(request.prompt.split("\n可续接SVT：", 1)[1].split("\n只输出 JSON", 1)[0])
        self.supplied.append(old)
        return SimpleNamespace(
            text=json.dumps(
                {
                    "svts": [
                        {
                            "existing_id": old[0]["id"] if old else None,
                            "title": "寻找出路",
                            "summary": "甲取剑后乙开门，出路仍未确定",
                            "event_ids": [e["id"] for e in events],
                            "mainline_reason": "同一目标继续推进",
                            "status": "open",
                        }
                    ]
                }
            )
        )


async def test_svt_continues_across_jobs_with_stable_id_and_no_future_context(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), ids, index["source_basis"])
    reader = ContinuingSVTReader()
    await generate_svts(tmp_path, reader, [ids[0]], index["source_basis"])
    first = await asyncio.to_thread(store.view, tmp_path, data)
    stable_id = first["svts"][0]["id"]
    await generate_svts(tmp_path, reader, [ids[1]], index["source_basis"])
    result = await asyncio.to_thread(store.view, tmp_path, data)
    assert len(result["svts"]) == 1
    assert result["svts"][0]["id"] == stable_id
    assert result["svts"][0]["note_ids"] == ids
    assert reader.supplied[-1][0]["id"] == stable_id
    # Change the rule to invalidate cached jobs, then regenerate only the earlier scope.
    await asyncio.to_thread((store.root(tmp_path) / "rules/svt.md").write_text, "Only supplied facts")
    await generate_svts(tmp_path, reader, [ids[0]], index["source_basis"])
    assert reader.supplied[-1] == []


def test_ledger_preserves_reveal_order_alias_evidence_and_seed_resolution(tmp_path):
    from lib.novel_workflow import memory
    from lib.novel_workflow.models import Reading
    from lib.novel_workflow.service import ground

    _data, index = project(tmp_path)
    first, second = index["notes"]
    quote = "甲拿起古剑。"
    left = ground(
        Reading(
            complete=True,
            summary=quote,
            assets=[{"kind": "character", "name": "甲", "description": "取剑者", "quote": quote}],
            threads=[{"kind": "seed", "description": "古剑来历未明", "quote": quote}],
        ),
        {"text": quote, "start": 0, "source_file": "source/book.txt", "note_id": first["id"]},
    )
    seed_id = left["threads"][0]["id"]
    quote = "乙推开城门。"
    right = ground(
        Reading(
            complete=True,
            summary=quote,
            assets=[{"kind": "character", "name": "乙", "description": "开门者", "quote": quote}],
            aliases=[{"claim_type": "fact", "source_kind": "narrative", "name": "甲", "alias": "乙", "quote": quote}],
            changes=[
                {"character": "甲", "before": "未知", "after": "身份揭晓", "dimension": "knowledge", "quote": quote}
            ],
            threads=[{"kind": "resolution", "description": "剑来历揭晓", "seed_id": seed_id, "quote": quote}],
        ),
        {"text": quote, "start": 20, "source_file": "source/book.txt", "note_id": second["id"]},
        {seed_id},
    )
    for note, result in [(first, left), (second, right)]:
        basis = store.reading_key(tmp_path, note)
        store.write(store.root(tmp_path) / "notes" / note["id"] / f"{basis}.json", {**result, "basis": basis})
    early = memory.ledger(tmp_path, index, through=1)
    all_read = memory.ledger(tmp_path, index)
    assert early["characters"][0]["aliases"] == []
    assert early["threads"][0]["resolutions"] == []
    assert len(all_read["characters"]) == 1
    assert all_read["characters"][0]["appear"] == [first["id"], second["id"]]
    assert all_read["threads"][0]["resolutions"][0]["seed_id"] == seed_id
    assert memory.context(early, "未出现人名的文字")["records"][0]["id"] == seed_id
    with pytest.raises(ValueError, match="outside"):
        ground(
            Reading(
                complete=True,
                summary="揭示",
                threads=[{"kind": "resolution", "description": "揭示", "seed_id": "invented", "quote": quote}],
            ),
            {},
        )


class Reviewer:
    async def generate(self, request, **kwargs):
        if "范围总览材料：" in request.prompt:
            nodes = json.loads(request.prompt.split("范围总览材料：", 1)[1].split("\n只输出 JSON", 1)[0])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "theme": "本范围的求生",
                        "mainline": "取剑寻路",
                        "must_preserve": "取剑的行动",
                        "adaptation_risks": "不能编造未知动机",
                        "evidence_ids": nodes[0]["evidence_ids"][:40],
                    }
                )
            )
        marker = (
            "本次已读范围材料："
            if "本次已读范围材料：" in request.prompt
            else "汇总已完成的取舍分析，检查跨章因果与组合建议："
        )
        nodes = json.loads(request.prompt.split(marker, 1)[1].split("\n只输出 JSON", 1)[0])
        advice = []
        for node in nodes:
            ids = [r["id"] for r in node["records"]] if "records" in node else node["evidence_ids"]
            advice.append(
                {
                    "action": "keep",
                    "note_ids": [node["note_id"]],
                    "evidence_ids": ids,
                    "reason": "必要行动",
                    "character_impact": "保持行动动机",
                    "thread_impact": "未明不删",
                    "dialogue_impact": "未提对白",
                    "preserve": "取剑或开门",
                }
            )
        return SimpleNamespace(text=json.dumps({"theme": "寻找出路", "mainline": "取剑后开门", "advice": advice}))


async def test_review_is_scoped_cited_and_does_not_modify_human_groups(tmp_path):
    from lib.novel_workflow.models import ScopeReview
    from lib.novel_workflow.review import review_scope, validate

    data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), ids, index["source_basis"])
    group = await asyncio.to_thread(store.group_notes, tmp_path, data, ids, "人工组合", index["source_basis"])
    await review_scope(tmp_path, Reviewer(), [ids[0]], index["source_basis"])
    result = await asyncio.to_thread(store.view, tmp_path, data)
    assert store.state(tmp_path)["groups"] == [group]
    assert result["groups"] == [{**group, "summary_stale": False}]
    review = result["reviews"][0]
    assert review["note_ids"] == [ids[0]]
    assert review["scope_kind"] == "selected"
    assert review["conclusion"]["must_preserve"] == "取剑的行动"
    assert review["applied"] is False
    assert review["stale"] is False
    assert all(e["evidence"]["note_id"] == ids[0] for e in review["evidence"].values())
    invalid = ScopeReview.model_validate(review["overview"][0])
    invalid.advice[0].note_ids = [ids[1]]
    with pytest.raises(ValueError, match="outside"):
        validate(invalid, review["evidence"], {ids[0]})
    await asyncio.to_thread((store.root(tmp_path) / "rules/review.md").write_text, "Changed rules")
    result = await asyncio.to_thread(store.view, tmp_path, data)
    assert result["reviews"][0]["stale"] is True


async def test_earlier_scope_never_receives_valid_future_svt(tmp_path):
    _data, index = await asyncio.to_thread(project, tmp_path)
    ids = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), ids, index["source_basis"])
    await generate_svts(tmp_path, ContinuingSVTReader(), ids, index["source_basis"])
    reader = ContinuingSVTReader()
    await generate_svts(tmp_path, reader, [ids[0]], index["source_basis"])
    assert reader.supplied == [[]]


async def test_new_earlier_memory_invalidates_later_reading_until_refreshed(tmp_path):
    data, index = await asyncio.to_thread(project, tmp_path)
    first, second = [n["id"] for n in index["notes"]]
    await read_notes(tmp_path, Reader(), [second], index["source_basis"])
    await read_notes(tmp_path, Reader(), [first], index["source_basis"])
    stale = await asyncio.to_thread(store.view, tmp_path, data)
    assert stale["notes"][1]["status"] == "outdated"
    await read_notes(tmp_path, Reader(), [second], index["source_basis"])
    fresh = await asyncio.to_thread(store.view, tmp_path, data)
    assert all(n["status"] == "read" for n in fresh["notes"])
