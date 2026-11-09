import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lib.novel_workflow import store
from lib.novel_workflow.models import Moment, SVTBatch
from lib.novel_workflow.service import generate_svts, read_notes, validate_svt
from lib.novel_workflow.svt_contract import adopt, assignments
from tests.unit.lib.episode.test_novel_workflow import Reader, project


def draft(events, existing=None):
    return {
        "existing_id": existing,
        "title": "主线",
        "summary": "因果",
        "event_ids": events,
        "mainline_reason": "当前目标",
        "status": "open",
    }


def test_one_note_cannot_have_multiple_primary_svts_even_with_disjoint_events():
    batch = SVTBatch(svts=[draft(["a"]), draft(["b"])])
    with pytest.raises(ValueError, match="一个主归属"):
        validate_svt(batch, {"a", "b"}, {"a", "b"}, set(), set(), event_notes={"a": "n", "b": "n"})
    with pytest.raises(ValueError, match="not classified"):
        validate_svt(SVTBatch(supporting_event_ids=["a"]), {"a"}, {"a"}, set(), set(), event_notes={"a": "n"})


def test_explosion_requires_paired_scene_dialogue_and_exact_note():
    with pytest.raises(ValidationError):
        Moment(event_ids=["a"], scene="场面", reason="高潮", note_ids=["n"], dialogue_ids=[])
    value = draft(["a"])
    value["climaxes"] = [
        {"event_ids": ["a"], "scene": "反转场面", "reason": "高潮", "note_ids": ["other"], "dialogue_ids": ["d"]}
    ]
    with pytest.raises(ValueError, match="来源 Note"):
        validate_svt(
            SVTBatch(svts=[value]), {"a"}, {"a"}, {"d"}, set(), dialogue_events={"d": "a"}, event_notes={"a": "n"}
        )
    value["climaxes"][0]["note_ids"] = ["n"]
    with pytest.raises(ValueError, match="来源事件"):
        validate_svt(
            SVTBatch(svts=[value]), {"a"}, {"a"}, {"d"}, set(), dialogue_events={"d": "outside"}, event_notes={"a": "n"}
        )
    assert validate_svt(
        SVTBatch(svts=[value]), {"a"}, {"a"}, {"d"}, set(), dialogue_events={"d": "a"}, event_notes={"a": "n"}
    )


async def test_note_batches_keep_single_primary_and_alternatives_can_replace_it(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    note_id = notebook["notes"][0]["id"]
    await read_notes(tmp_path, Reader(), [note_id], notebook["source_basis"])
    note = notebook["notes"][0]
    result = store.note_result(tmp_path, note)
    event = result["events"][0]
    result["events"] = [{**copy.deepcopy(event), "id": f"event-{i}"} for i in range(11)]
    store.write(store.root(tmp_path) / "notes" / note_id / f"{store.reading_key(tmp_path, note)}.json", result)

    class Generator:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            events = json.loads(request.prompt.split("本批事件：", 1)[1].split("\n可续接SVT：", 1)[0])
            old = json.loads(request.prompt.split("\n可续接SVT：", 1)[1].split("\n只输出 JSON", 1)[0])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "svts": [draft([e["id"] for e in events], old[0]["id"] if old else None)],
                        "alternatives": [
                            {
                                "note_id": note_id,
                                "candidates": [
                                    {"title": "备选主线一", "summary": "另一视角", "reason": "侧重人物选择"},
                                    {"title": "备选主线二", "summary": "另一目标", "reason": "侧重线索"},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    generator = Generator()
    await generate_svts(tmp_path, generator, [note_id], notebook["source_basis"])
    assert generator.calls == 2
    view = store.view(tmp_path, data)
    assert len(view["svts"]) == 1
    assert len(view["notes"][0]["svt_candidates"]) == 2
    original = view["notes"][0]["svt_id"]
    candidate = view["notes"][0]["svt_candidates"][0]["candidate_id"]
    adopted = adopt(tmp_path, data, note_id, candidate, notebook["source_basis"])
    fresh = store.view(tmp_path, data)
    assert fresh["notes"][0]["svt_id"] == adopted["svt_id"] != original
    assert assignments(fresh["svts"]) == {note_id: adopted["svt_id"]}
    assert len(fresh["svts"][0]["event_ids"]) == 11
    assert fresh["notes"][0]["svt_status"] == "needs_review"
