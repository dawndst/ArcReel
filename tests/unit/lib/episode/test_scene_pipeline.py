import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.novel_workflow import scene_library, scene_pipeline, store
from lib.novel_workflow.common import digest
from lib.novel_workflow.scene_contracts import ScenePlan
from lib.novel_workflow.service import generate_svts, read_notes
from lib.novel_workflow.stage_runner import ContractError, FieldPatch, StageRepairRequired, apply_patch, run
from tests.unit.lib.episode.test_novel_workflow import Reader, SVTReader, project


def model_output(request):
    material = json.loads(request.prompt.split("阶段材料：", 1)[1])
    kind = request.response_schema["title"]
    if kind == "ScenePlan":
        return {
            "scenes": [
                {
                    "key": "s",
                    "title": "取剑",
                    "location": "未明",
                    "time": "未明",
                    "purpose": "行动",
                    "event_ids": [e["id"] for e in material["events"]],
                    "primary_event_ids": [e["id"] for e in material["events"]],
                }
            ]
        }
    if kind == "Inspection":
        return {"findings": [], "corrections": []}
    return {
        "shots": [
            {
                "key": "sh",
                "title": "取剑镜头",
                "event_ids": [e["id"] for e in material["events"]],
                "purpose": "行动",
                **dict.fromkeys(
                    ["shot_size", "camera_angle", "camera_movement", "framing", "continuity", "sound"], "固定观察动作"
                ),
                "segments": [
                    {
                        "duration_seconds": 7,
                        "start_frame": "甲站立",
                        "action": "甲拿起古剑",
                        "end_frame": "甲持剑",
                        "visible_asset_ids": [],
                    }
                ],
            }
        ]
    }


class Generator:
    calls = 0
    max_output_tokens = 48000

    async def generate(self, request, **kwargs):
        self.calls += 1
        assert request.response_schema
        return SimpleNamespace(text=json.dumps(model_output(request), ensure_ascii=False))


async def prepared(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
    await asyncio.to_thread(store.write, tmp_path / "project.json", data)
    ids = [notebook["notes"][0]["id"]]
    await read_notes(tmp_path, Reader(), ids, notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), ids, notebook["source_basis"])
    return data, notebook, ids


async def test_pipeline_reuses_ids_preserves_upstream_and_marks_actual_completion(tmp_path):
    _data, notebook, ids = await prepared(tmp_path)
    before = await asyncio.to_thread(
        lambda: digest([store.valid_readings(tmp_path, notebook), (store.root(tmp_path) / "svts.json").read_text()])
    )
    generator = Generator()
    await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    first = await asyncio.to_thread(scene_library.catalog, tmp_path)
    assert generator.calls == 3
    shot = next(iter(first["batches"].values()))["scenes"][0]["shots"][0]
    assert shot["segments"][0]["duration_seconds"] == 7
    assert shot["evidence"]["quote"] == "甲拿起古剑。"
    await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    second = await asyncio.to_thread(scene_library.catalog, tmp_path)
    assert generator.calls == 3
    assert first == second
    status = await asyncio.to_thread(
        scene_pipeline.status, tmp_path, notebook, store.valid_readings(tmp_path, notebook)
    )
    assert status[ids[0]]["status"] == "complete"
    assert status[ids[0]]["completed"] == status[ids[0]]["total"] == 1
    assert json.loads((tmp_path / "project.json").read_text())["episodes"] == []
    assert before == await asyncio.to_thread(
        lambda: digest([store.valid_readings(tmp_path, notebook), (store.root(tmp_path) / "svts.json").read_text()])
    )


def test_patch_cannot_rewrite_other_shots_and_checks_base_revision():
    candidate = {"shots": [{"title": "good"}, {"title": "bad"}]}
    issues = [{"path": ["shots", 1, "title"], "message": "bad"}]
    patch = FieldPatch(
        base_revision=digest(candidate),
        edits=[{"path": ["shots", 1, "title"], "operation": "replace", "value_json": '"fixed"'}],
    )
    assert apply_patch(candidate, patch, issues) == {"shots": [{"title": "good"}, {"title": "fixed"}]}
    assert candidate["shots"][1]["title"] == "bad"
    patch.edits[0].path = ["shots", 0, "title"]
    with pytest.raises(ValueError, match="错误字段"):
        apply_patch(candidate, patch, issues)
    patch.base_revision = "old"
    with pytest.raises(ValueError, match="版本"):
        apply_patch(candidate, patch, issues)


async def test_failed_local_repairs_keep_candidate_and_resume_without_recreating_draft(tmp_path):
    class Patcher:
        calls = 0
        fix = False

        async def generate(self, request, **kwargs):
            self.calls += 1
            if request.response_schema["title"] == "ScenePlan":
                return SimpleNamespace(text='{"scenes": []}')
            payload = json.loads(request.prompt.split("局部修订材料：", 1)[1])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "base_revision": payload["base_revision"],
                        "edits": [{"path": ["scenes"], "operation": "replace", "value_json": "[]"}],
                    }
                )
            )

    generator = Patcher()

    def validate(value):
        if not generator.fix:
            raise ContractError([{"path": ["scenes"], "message": "缺场"}])
        return value.model_dump()

    with pytest.raises(StageRepairRequired):
        await run(tmp_path, generator, ScenePlan, "rule", {}, "test-key", validate)
    assert generator.calls == 4
    generator.fix = True
    await run(tmp_path, generator, ScenePlan, "rule", {}, "test-key", validate)
    assert generator.calls == 4


async def test_review_rule_update_reuses_scene_and_shots(tmp_path):
    _, notebook, ids = await prepared(tmp_path)
    generator = Generator()
    await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    first = await asyncio.to_thread(scene_library.catalog, tmp_path)

    def change():
        file = store.root(tmp_path) / "rules/scene_inspection.md"
        file.parent.mkdir(exist_ok=True)
        file.write_text("新审核规则")

    await asyncio.to_thread(change)
    await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    second = await asyncio.to_thread(scene_library.catalog, tmp_path)
    assert generator.calls == 4
    assert [u["id"] for u in first["plans"][ids[0]]["units"]] == [u["id"] for u in second["plans"][ids[0]]["units"]]
    assert [b["scenes"] for b in first["batches"].values()] == [b["scenes"] for b in second["batches"].values()]


def test_source_compilation_retains_repeated_dialogue_by_id_and_rejects_future_asset():
    from lib.novel_workflow.scene_contracts import SceneShots, compile_shots

    class Catalogue:
        def __init__(self):
            self.note = {"id": "note"}
            self.svt = {"id": "svt"}
            self.texts = {"book": "甲说走。乙说走。后段兽形。"}
            self.events = {"e1": {"source_id": "s1"}, "e2": {"source_id": "s2"}}
            self.dialogues = {
                "d1": {"id": "d1", "event_id": "e1", "source_id": "d1s", "text": "走", "speaker": "甲"},
                "d2": {"id": "d2", "event_id": "e2", "source_id": "d2s", "text": "走", "speaker": "乙"},
            }
            self.sources = {
                "s1": {"start": 0, "end": 2, "source_file": "book"},
                "d1s": {"start": 2, "end": 4, "source_file": "book"},
                "s2": {"start": 4, "end": 6, "source_file": "book"},
                "d2s": {"start": 6, "end": 8, "source_file": "book"},
                "future": {"start": 8, "end": 12, "source_file": "book"},
            }
            self.moments = []
            self.assets = {
                "beast": {
                    "name": "兽形",
                    "kind": "character",
                    "source_id": "future",
                    "pending": False,
                    "asset_name": "乙",
                    "variant": "兽形",
                }
            }

        def chunk(self, ids):
            refs = [self.sources[d["source_id"]] for d in self.dialogues.values() if d["event_id"] in ids]
            return {"source_file": "book", "end": max(r["end"] for r in refs)}

    def shot(event, line):
        return {
            "key": event,
            "title": "动作",
            "event_ids": [event],
            "purpose": "决定",
            **dict.fromkeys(["shot_size", "camera_angle", "camera_movement", "framing", "continuity", "sound"], "明确"),
            "segments": [
                {
                    "duration_seconds": 5,
                    "start_frame": "站立",
                    "action": "说话",
                    "end_frame": "离开",
                    "dialogue": [{"dialogue_id": line, "delivery": "off_screen"}],
                }
            ],
        }

    catalogue = Catalogue()
    draft = SceneShots.model_validate({"shots": [shot("e1", "d1"), shot("e2", "d2")]})
    unit = {"event_ids": ["e1", "e2"], "primary_event_ids": ["e1", "e2"]}
    result = compile_shots(draft, catalogue, unit)
    assert [s["source_dialogue_uses"][0]["dialogue_id"] for s in result["shots"]] == ["d1", "d2"]
    assert [s["evidence"]["end"] for s in result["shots"]] == [4, 8]
    assert all(s["segments"][0]["utterances"][0]["speaker"] is None for s in result["shots"])
    draft.shots[0].segments[0].visible_asset_ids = ["beast"]
    with pytest.raises(ContractError, match="未来形态"):
        compile_shots(draft, catalogue, unit)


def test_scoped_semantic_question_does_not_block_unrelated_shot():
    from lib.novel_workflow.scene_review import require_reviewed

    batch = {
        "review": {
            "version": 2,
            "issues": [{"status": "open", "blocking": True, "shot_ids": ["SH-2"]}],
            "unresolved": ["问题"],
            "revisions": [],
        }
    }
    require_reviewed(batch, {"id": "SH-1"})
    with pytest.raises(ValueError, match="待核实"):
        require_reviewed(batch, {"id": "SH-2"})


def test_coverage_repair_cannot_silently_rewrite_already_valid_shots():
    candidate = {"shots": [{"key": "good", "title": "保留"}]}
    patch = FieldPatch(
        base_revision=digest(candidate),
        edits=[
            {
                "path": ["shots"],
                "operation": "replace",
                "value_json": '[{"key":"good","title":"偷偷改写"},{"key":"new","title":"新增"}]',
            }
        ],
    )
    with pytest.raises(ValueError, match="原样保留"):
        apply_patch(candidate, patch, [{"path": ["shots"], "message": "遗漏事件"}])


def test_reviewer_can_withdraw_an_unsafe_proposal_without_fabricating_a_plot_question():
    candidate = {"corrections": [{"field": "title", "after": "不安全"}, {"field": "title", "after": "可用"}]}
    patch = FieldPatch(
        base_revision=digest(candidate),
        edits=[{"path": ["corrections", 0], "operation": "remove", "value_json": "null"}],
    )
    result = apply_patch(candidate, patch, [{"path": ["corrections", 0], "type": "unsafe_proposal", "message": "撤回"}])
    assert result == {"corrections": [{"field": "title", "after": "可用"}]}
    assert len(candidate["corrections"]) == 2


def test_later_description_of_an_existing_scene_asset_is_not_a_future_transformation():
    from lib.novel_workflow.scene_material import asset_available

    catalogue = SimpleNamespace(
        sources={"later": {"source_file": "book", "start": 6, "end": 8}},
        chunk=lambda ids: {"source_file": "book", "end": 10 if "e2" in ids else 5},
    )
    base = {"source_id": "later", "kind": "scene", "variant": "", "state": ""}
    assert asset_available(catalogue, base, ["e1"], ["e1", "e2"])
    assert not asset_available(catalogue, {**base, "kind": "character", "variant": "受伤形态"}, ["e1"], ["e1", "e2"])


async def test_ai_omission_is_a_suggestion_and_does_not_remove_director_options(tmp_path):
    _, notebook, ids = await prepared(tmp_path)

    class SuggestionGenerator(Generator):
        async def generate(self, request, **kwargs):
            value = model_output(request)
            if request.response_schema["title"] == "ScenePlan":
                value["scenes"][0]["skipped_reason"] = "可压缩为过渡，由导演决定"
            return SimpleNamespace(text=json.dumps(value))

    await scene_library.generate(tmp_path, SuggestionGenerator(), ids, notebook["source_basis"])
    library = await asyncio.to_thread(scene_library.catalog, tmp_path)
    unit = library["plans"][ids[0]]["units"][0]
    scene = next(iter(library["batches"].values()))["scenes"][0]
    assert unit["status"] == "ready"
    assert scene["suggested_omission"] == "可压缩为过渡，由导演决定"
    assert scene["shots"]


def test_review_freshness_tracks_only_the_edited_shot_and_rule():
    from copy import deepcopy

    from lib.novel_workflow.scene_inspection import pending_shots, shot_inputs

    shot = {"id": "SH-1", "title": "原稿", "segments": [], "production": {"event_ids": ["e"]}}
    other = {**deepcopy(shot), "id": "SH-2"}
    batch = {"basis": "batch", "scenes": [{"shots": [shot, other]}], "inspection_rule_basis": "rule"}
    batch["inspection_shots"] = {s["id"]: digest(s) for s in shot_inputs(batch)}
    assert pending_shots(batch, "rule") == []
    shot["title"] = "人工编辑"
    assert pending_shots(batch, "rule") == ["SH-1"]
    assert pending_shots(batch, "new-rule") == ["SH-1", "SH-2"]


async def test_unreviewed_draft_can_be_assembled_but_cannot_pass_formal_delivery(tmp_path):
    from lib.novel_workflow.delivery_review import preview
    from lib.novel_workflow.director import content_from_selection

    data, notebook, ids = await prepared(tmp_path)
    await scene_library.generate(tmp_path, Generator(), ids, notebook["source_basis"])

    def inspect():
        library = scene_library.catalog(tmp_path)
        batch = next(iter(library["batches"].values()))
        shot = batch["scenes"][0]["shots"][0]
        for key in ["inspection_basis", "inspection_shots", "inspection_rule_basis", "review"]:
            batch.pop(key, None)
        store.write(store.root(tmp_path) / "scene_library.json", library)
        result = preview(tmp_path, data, [shot["id"]], "编导参考", notebook["source_basis"])
        assert any(i["code"] == "source_review_pending" and i["hard"] for i in result["issues"])
        selected = scene_library.selected_shots(
            tmp_path, notebook, store.valid_readings(tmp_path, notebook), [shot["id"]]
        )
        script, mapping = content_from_selection(selected, 1, "编导参考")
        assert script["scenes"][0]["duration_seconds"] == 7
        assert mapping[0]["library_shot_id"] == shot["id"]

    await asyncio.to_thread(inspect)


async def test_complete_cache_enters_local_repair_when_validation_changes(tmp_path):
    from lib.novel_workflow.models import StrictModel

    class Value(StrictModel):
        value: int
        preserved: str

    class Model:
        calls = 0

        async def generate(self, request, **kwargs):
            self.calls += 1
            if request.response_schema["title"] == "Value":
                return SimpleNamespace(text='{"value":1,"preserved":"保留"}')
            payload = json.loads(request.prompt.split("局部修订材料：", 1)[1])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "base_revision": payload["base_revision"],
                        "edits": [{"path": ["value"], "operation": "replace", "value_json": "2"}],
                    }
                )
            )

    model = Model()
    await run(tmp_path, model, Value, "rule", {}, "revision", lambda v: v.model_dump())

    def tightened(value):
        if value.value != 2:
            raise ContractError([{"path": ["value"], "message": "改为2"}])
        return value.model_dump()

    result = await run(tmp_path, model, Value, "rule", {}, "revision", tightened)
    assert result == {"value": 2, "preserved": "保留"}
    assert model.calls == 2


async def test_filling_an_earlier_gap_does_not_regenerate_a_correct_later_scene(tmp_path):
    from collections import Counter
    from copy import deepcopy

    from lib.novel_workflow import chapters

    def setup():
        data, _ = project(tmp_path)
        source = tmp_path / "source/book.txt"
        source.write_text(source.read_text().replace("甲拿起古剑。", "甲拿起古剑。甲放下古剑。"))
        data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
        store.write(tmp_path / "project.json", data)
        return store.initialize(tmp_path, data, chapters.index(tmp_path, data)["source_basis"])

    class TwoEvents(Reader):
        async def generate(self, request, **kwargs):
            response = await super().generate(request, **kwargs)
            value = json.loads(response.text)
            if value.get("events") and value.get("complete"):
                event = deepcopy(value["events"][0])
                event.update(title="放下古剑", action="甲放下古剑。", quote="甲放下古剑。")
                value["events"].append(event)
                return SimpleNamespace(text=json.dumps(value))
            return response

    notebook = await asyncio.to_thread(setup)
    ids = [notebook["notes"][0]["id"]]
    await read_notes(tmp_path, TwoEvents(), ids, notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), ids, notebook["source_basis"])

    class GapGenerator(Generator):
        fix = False
        first_event = None

        def __init__(self):
            self.shot_calls = Counter()

        async def generate(self, request, **kwargs):
            kind = request.response_schema["title"]
            if kind == "FieldPatch":
                payload = json.loads(request.prompt.split("局部修订材料：", 1)[1])
                context = payload["context"]
                rows = (
                    model_output(
                        SimpleNamespace(
                            prompt="阶段材料：" + json.dumps(context), response_schema={"title": "SceneShots"}
                        )
                    )["shots"]
                    if self.fix
                    else []
                )
                return SimpleNamespace(
                    text=json.dumps(
                        {
                            "base_revision": payload["base_revision"],
                            "edits": [{"path": ["shots"], "operation": "replace", "value_json": json.dumps(rows)}],
                        }
                    )
                )
            context = json.loads(request.prompt.split("阶段材料：", 1)[1])
            output = model_output(request)
            if kind == "ScenePlan":
                self.first_event = context["events"][0]["id"]
                scene = output["scenes"][0]
                output["scenes"] = [
                    {
                        **scene,
                        "key": str(i),
                        "title": e["title"],
                        "event_ids": [e["id"]],
                        "primary_event_ids": [e["id"]],
                    }
                    for i, e in enumerate(context["events"])
                ]
            if kind == "SceneShots":
                event = context["events"][0]["id"]
                self.shot_calls[event] += 1
                if event == self.first_event and not self.fix:
                    output = {"shots": []}
            return SimpleNamespace(text=json.dumps(output))

    generator = GapGenerator()
    with pytest.raises(StageRepairRequired):
        await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    before = await asyncio.to_thread(scene_library.catalog, tmp_path)
    second = next(iter(before["batches"].values()))["scenes"][0]["shots"][0]

    def change_review_rule():
        file = store.root(tmp_path) / "rules/scene_inspection.md"
        file.parent.mkdir(exist_ok=True)
        file.write_text("独立复审规则更新")

    await asyncio.to_thread(change_review_rule)
    generator.fix = True
    await scene_library.generate(tmp_path, generator, ids, notebook["source_basis"])
    after = await asyncio.to_thread(scene_library.catalog, tmp_path)
    assert sum(generator.shot_calls.values()) == 2
    assert any(sh == second for b in after["batches"].values() for sc in b["scenes"] for sh in sc["shots"])
    assert all(u["status"] == "ready" for u in after["plans"][ids[0]]["units"])


def test_repeated_dialogue_source_navigation_uses_its_saved_occurrence():
    from lib.novel_workflow.scene_source import linked_dialogue_range

    chunk = {"source_file": "book", "start": 100, "end": 106, "text": "走。停。走。"}
    lines = {
        "second": {"quote": "走。", "evidence": {"source_file": "book", "start": 104, "end": 106, "quote": "走。"}}
    }
    shot = {"source_dialogue_uses": [{"segment": 0, "utterance": 0, "dialogue_id": "second"}]}
    assert linked_dialogue_range(shot, lines, 0, 0, {"text": "走。"}, chunk) == [{"start": 104, "end": 106}]
    assert linked_dialogue_range(shot, lines, 0, 0, {"text": "停。"}, chunk) is None
    lines["second"]["evidence"]["quote"] = "错误内容"
    assert linked_dialogue_range(shot, lines, 0, 0, {"text": "走。"}, chunk) is None


async def test_explicit_asset_confirmation_rebinds_pending_shots_without_generation(tmp_path):
    from lib.novel_workflow import assets, chapters

    def setup():
        data, _ = project(tmp_path)
        file = tmp_path / "source/book.txt"
        file.write_text(file.read_text().replace("甲拿起古剑。", "甲拿起古剑。甲说：“走。”"))
        data.update(content_mode="drama", generation_mode="storyboard", episodes=[], characters={}, scenes={}, props={})
        store.write(tmp_path / "project.json", data)
        return data, store.initialize(tmp_path, data, chapters.index(tmp_path, data)["source_basis"])

    class DialogueReader(Reader):
        async def generate(self, request, **kwargs):
            response = await super().generate(request, **kwargs)
            value = json.loads(response.text)
            if value.get("events") and value.get("complete"):
                value["events"][0]["dialogues"] = [
                    {
                        "speaker": "甲",
                        "quote": "走。",
                        "value": "决定",
                        "claim_type": "fact",
                        "source_kind": "narrative",
                        "perspective": "",
                    }
                ]
                return SimpleNamespace(text=json.dumps(value))
            return response

    data, book = await asyncio.to_thread(setup)
    ids = [book["notes"][0]["id"]]
    await read_notes(tmp_path, DialogueReader(), ids, book["source_basis"])
    await generate_svts(tmp_path, SVTReader(), ids, book["source_basis"])

    def unlink():
        project_data = json.loads((tmp_path / "project.json").read_text())
        reading = store.valid_readings(tmp_path, book)[ids[0]]
        mention = reading["assets"][0]
        entity_id = project_data["characters"]["甲"]["asset_id"]
        project_data["note_asset_links"].pop(mention["id"])
        project_data["note_asset_entities"] = {}
        project_data.setdefault("note_asset_issues", {})[mention["id"]] = {
            "code": "identity_ambiguous",
            "candidates": [{"entity_id": entity_id, "name": "甲"}],
            "blocking": True,
        }
        store.write(tmp_path / "project.json", project_data)
        return mention, entity_id, reading["basis"]

    mention, entity_id, reading_basis = await asyncio.to_thread(unlink)

    class SpeakerGenerator(Generator):
        async def generate(self, request, **kwargs):
            self.calls += 1
            value = model_output(request)
            if request.response_schema["title"] == "SceneShots":
                context = json.loads(request.prompt.split("阶段材料：", 1)[1])
                seg = value["shots"][0]["segments"][0]
                seg["visible_asset_ids"] = [mention["id"]]
                seg["dialogue"] = [{"dialogue_id": context["dialogues"][0]["id"], "delivery": "on_screen"}]
            return SimpleNamespace(text=json.dumps(value))

    generator = SpeakerGenerator()
    await scene_library.generate(tmp_path, generator, ids, book["source_basis"])
    before = await asyncio.to_thread(scene_library.catalog, tmp_path)
    old = next(iter(before["batches"].values()))["scenes"][0]["shots"][0]
    assert old["segments"][0]["utterances"][0]["speaker"] is None
    result = await asyncio.to_thread(
        assets.resolve, tmp_path, data, mention["id"], book["source_basis"], reading_basis, entity_id, False, "none", ""
    )
    assert result["rebound_shots"] == 1
    after = await asyncio.to_thread(scene_library.catalog, tmp_path)
    new = next(iter(after["batches"].values()))["scenes"][0]["shots"][0]
    assert new["id"] == old["id"]
    assert new["segments"][0]["utterances"][0]["speaker"] == "甲"
    assert new["segments"][0]["utterances"][0]["text"] == "走。"
    assert new["segments"][0]["scene_description"] == old["segments"][0]["scene_description"]
    assert generator.calls == 3


def test_short_shot_phases_share_one_execution_segment_and_keep_dialogue_and_sources():
    from copy import deepcopy

    from lib.novel_workflow.director import content_from_selection
    from lib.novel_workflow.scene_projection import project as project_segments

    segments = [
        {
            "duration_seconds": 6,
            "scene_description": "甲入画",
            "start_frame": "门外",
            "end_frame": "门边",
            "characters_in_scene": ["甲"],
            "scenes": ["房间"],
            "props": [],
            "utterances": [{"kind": "dialogue", "speaker": "甲", "text": "走。", "delivery": "on_screen"}],
            "asset_states": [],
        },
        {
            "duration_seconds": 7,
            "scene_description": "乙跟上",
            "start_frame": "门边",
            "end_frame": "两人离开",
            "characters_in_scene": ["甲", "乙"],
            "scenes": ["房间"],
            "props": ["剑"],
            "utterances": [{"kind": "dialogue", "speaker": "乙", "text": "好。", "delivery": "on_screen"}],
            "asset_states": [],
        },
    ]
    before = deepcopy(segments)
    execution = project_segments(segments)
    assert len(execution) == 1
    assert execution[0]["duration_seconds"] == 13
    assert execution[0]["start_frame"] == "门外"
    assert execution[0]["end_frame"] == "两人离开"
    assert [u["text"] for u in execution[0]["utterances"]] == ["走。", "好。"]
    shot = {"id": "SH-1", "title": "离开", "evidence": {"quote": "原文"}, "segments": segments}
    content, mapping = content_from_selection([({}, {"id": "SCN-1"}, shot)], 1, "开篇")
    assert len(content["scenes"]) == 1
    assert content["scenes"][0]["segment_number"] is None
    assert mapping[0]["library_segment_indices"] == [0, 1]
    assert segments == before
    segments[1]["duration_seconds"] = 10
    assert len(project_segments(segments)) == 2
