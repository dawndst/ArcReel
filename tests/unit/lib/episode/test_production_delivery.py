"""Human production decisions are tied to executable content and the actual approved artwork."""

import base64
import io
import json
import zipfile
from copy import deepcopy

import pytest

from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, execution, scene_library, settings, store
from lib.novel_workflow import delivery_review as review
from lib.novel_workflow.delivery_review import DirectorDecision
from lib.novel_workflow.shot_production import context, planning_inputs
from tests.unit.lib.episode.test_note_assets import save_reading
from tests.unit.lib.episode.test_shot_production import design


@pytest.fixture
def prepared(tmp_path):
    from lib.project.project_manager import ProjectManager
    from lib.project.project_schema import CURRENT_PROJECT_SCHEMA_VERSION

    manager = ProjectManager(tmp_path)
    path = manager.create_project("demo", content_mode="drama")
    text = "# 第一章\n甲举起古剑，说：“出发。”乙在门外说：“等我。”\n"
    (path / "source/book.txt").write_text(text)
    project = manager.load_project("demo")
    project.update(
        schema_version=CURRENT_PROJECT_SCHEMA_VERSION,
        whole_source_files=[{"source_file": "source/book.txt"}],
        generation_mode="storyboard",
        episodes=[],
        characters={},
        scenes={},
        props={},
        aspect_ratio="16:9",
    )
    for bucket, name, code in [
        ("characters", "甲", "CHR-001"),
        ("characters", "乙", "CHR-002"),
        ("scenes", "房间", "LOC-001"),
        ("props", "古剑", "PRP-001"),
    ]:
        project[bucket][name] = {"asset_id": code, "asset_code": code, "description": name, "voice_style": "平静清晰"}
    store.write(path / "project.json", project)
    settings.update(path, {"understanding_enabled": False})
    book = store.initialize(path, project, chapters.index(path, project)["source_basis"])
    note = book["notes"][0]
    save_reading(path, note, [])
    reading = store.valid_readings(path, book)[note["id"]]
    quote = text.split("\n")[1]
    ev = {
        "note_id": note["id"],
        "source_file": "source/book.txt",
        "start": text.index(quote),
        "end": text.index(quote) + len(quote),
        "quote": quote,
    }
    shot = {
        "id": "SH-0001",
        "title": "取剑出发",
        "evidence": ev,
        "segments": [
            {
                "duration_seconds": 8,
                "scene_description": "甲举剑望向门外",
                "characters_in_scene": ["甲"],
                "scenes": ["房间"],
                "props": ["古剑"],
                "start_frame": "甲望着古剑",
                "end_frame": "甲握剑面向门口",
                "asset_states": [],
                "utterances": [
                    {
                        "kind": "dialogue",
                        "speaker": "甲",
                        "text": "出发。",
                        "delivery": "on_screen",
                        "origin": "source",
                        "basis_quote": "",
                    },
                    {
                        "kind": "dialogue",
                        "speaker": "乙",
                        "text": "等我。",
                        "delivery": "off_screen",
                        "origin": "source",
                        "basis_quote": "",
                    },
                ],
            }
        ],
        "production": {"shot_id": "SH-0001", "event_ids": [], "moment_ids": [], "design": design(), "assets": []},
    }
    ctx = context(path, {**reading, "events": []}, chapters.chunks(path, project, note)[0])
    batch = {
        "basis": "batch",
        "note_id": note["id"],
        "note_order": 1,
        "part": 0,
        "source_basis": book["source_basis"],
        "rule_basis": digest(store.effective_rule(path, "scenes")),
        "note_bases": {note["id"]: reading["basis"]},
        "understanding_basis": digest([]),
        "production_context": ctx,
        "production_basis": planning_inputs(
            ctx, store.effective_rule(path, "shot_production"), {shot["id"]: shot}, project, reading
        )[2],
        "scenes": [
            {"id": "SCN-0001", "title": "出发", "location": "房间", "time": "日", "purpose": "行动", "shots": [shot]}
        ],
    }
    store.write(store.root(path) / "scene_library.json", {"shot_counter": 1, "batches": {"n:0": batch}})
    return manager, path, project, book, shot


def decision(plan):
    return DirectorDecision(
        basis=plan["basis"],
        reviewer="测试编导",
        story_intent="让观众看清人物携带古剑决定出发",
        withheld="保留门外人物此时还未入画的悬念",
        story_checked=True,
        timing_checked=True,
        continuity_checked=True,
        decisions={i["code"]: "经本集分镜核对，当前表达保留且不影响行动因果" for i in plan["issues"] if not i["hard"]},
    )


def preview(data):
    _, path, project, book, shot = data
    return review.preview(path, project, [shot["id"]], "出发", book["source_basis"])


def test_human_review_then_assembly_then_current_artwork_handoff(prepared):
    from lib.novel_workflow.director import assemble

    manager, path, _project, book, shot = prepared
    initial = preview(prepared)
    assert not initial["issues"]
    assert {a["name"] for a in initial["assets"] if a["visible"]} == {"甲", "房间", "古剑"}
    assert next(a for a in initial["assets"] if a["name"] == "乙")["voice"]
    # Assembly is a narrative reference; human review is recorded separately, not a timing gate.
    review.approve(path, [shot["id"]], "出发", book["source_basis"], decision(initial), actor_id="operator")
    episode = assemble(manager, "demo", [shot["id"]], "出发", book["source_basis"], "request")
    assert assemble(manager, "demo", [shot["id"]], "出发", book["source_basis"], "new-request") == episode
    current = manager.load_project("demo")
    before = review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])
    assert not before["ready"]
    assert len(before["missing_materials"]) == 3
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII="
    )
    for bucket, field in [("characters", "character_sheet"), ("scenes", "scene_image"), ("props", "prop_image")]:
        name = next(iter(current[bucket]))
        file = f"{current[bucket][name]['asset_code']}.png"
        (path / file).write_bytes(image)
        current[bucket][name][field] = file
    store.write(path / "project.json", current)
    with pytest.raises(ValueError, match="制作包尚未"):
        review.export(path, current, [shot["id"]], "出发", book["source_basis"], final=True)
    listed = review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])
    assert listed["approved"]
    for asset in listed["assets"]:
        if asset["visible"]:
            review.asset_approval(
                path,
                [shot["id"]],
                "出发",
                book["source_basis"],
                listed["basis"],
                asset["asset_id"],
                asset["image_hash"],
                "美术",
                actor_id="art",
            )
    final = review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])
    assert final["ready"]
    assert final["shots"][0]["display_id"] == "EP01-SC01-SH001"
    assert "角色画外发声" in final["shots"][0]["segments"][0]["canvas_prompt"]
    with zipfile.ZipFile(
        io.BytesIO(review.export(path, current, [shot["id"]], "出发", book["source_basis"], final=True))
    ) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["export_status"] == "approved"
        assert len([f for f in archive.namelist() if f.startswith("assets/")]) == 3
        assert not any("CHR-002" in f for f in archive.namelist())
    # Image-only changes retain story approval but invalidate the specific reference approval.
    (path / "CHR-001.png").write_bytes(image + b"changed")
    changed = review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])
    assert changed["approved"]
    assert not changed["ready"]
    # Native edits cannot be disguised as the previously accepted assembly.
    from lib.episode.episode_paths import SCRIPT_PLAN_FILENAMES, episode_drafts_dir

    plan_file = episode_drafts_dir(path, episode) / SCRIPT_PLAN_FILENAMES["drama"]
    formal = load_json(plan_file)
    formal["title"] = "编辑后的版本"
    store.write(plan_file, formal)
    assert "formal_plan_changed" in {
        m["code"]
        for m in review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])["missing_materials"]
    }


def test_hard_errors_cannot_be_signed_off_but_timing_is_a_human_decision(prepared):
    _, path, project, book, shot = prepared
    file = store.root(path) / "scene_library.json"
    library = load_json(file)
    raw = library["batches"]["n:0"]["scenes"][0]["shots"][0]
    raw["segments"][0]["utterances"][0]["speaker"] = None
    store.write(file, library)
    plan = preview(prepared)
    with pytest.raises(ValueError, match="人工确认不能"):
        review.approve(path, [shot["id"]], "出发", book["source_basis"], decision(plan))
    raw["segments"][0]["utterances"][0].update(speaker="甲", delivery="on_screen", text="很长的台词" * 50)
    batch = library["batches"]["n:0"]
    reading = store.valid_readings(path, book)[batch["note_id"]]
    batch["production_basis"] = planning_inputs(
        batch["production_context"], store.effective_rule(path, "shot_production"), {raw["id"]: raw}, project, reading
    )[2]
    store.write(file, library)
    plan = preview(prepared)
    d = decision(plan)
    assert not any(i["code"] == "timing" for i in plan["issues"])
    review.approve(path, [shot["id"]], "出发", book["source_basis"], d)
    # No arbitrary sign-off can bypass structural conflicts with hidden characters.
    raw["segments"][0]["asset_states"] = [
        {"kind": "character", "name": "甲", "visibility": "hidden", "start": "", "end": "", "attachment": ""}
    ]
    assert any(i["hard"] and i["code"] == "hidden_visible" for i in execution.inspect(raw, project))


def test_edit_grounding_cuts_ids_and_versions_invalidate_confirmation(prepared):
    _, path, project, book, shot = prepared
    plan = preview(prepared)
    review.approve(path, [shot["id"]], "出发", book["source_basis"], decision(plan))
    source = (path / "source/book.txt").read_text()
    draft = execution.ShotEdit.model_validate({"title": shot["title"], "segments": shot["segments"]})
    draft.segments[0].utterances[0].text = "凭空添加的原文"
    with pytest.raises(ValueError, match="连续摘录"):
        execution.validate_edit(draft, source, project)
    draft.segments[0].utterances[0].origin = "adaptation"
    with pytest.raises(ValueError, match="填写原文依据"):
        execution.validate_edit(draft, source, project)
    draft.segments[0].utterances[0].basis_quote = "甲举起古剑"
    assert execution.validate_edit(draft, source, project)
    draft.segments.append(deepcopy(draft.segments[0]))
    draft.cut_before = [1]
    result = execution.update(path, shot["id"], book["source_basis"], digest(shot), draft)
    assert result["shot_ids"] == ["SH-0001", "SH-0002"]
    assert list((store.root(path) / "history").glob("execution-edit-*.json"))
    updated = preview(prepared)
    assert not updated["approved"]
    assert updated["basis"] != plan["basis"]
    assert not scene_library.view(path, book, store.valid_readings(path, book))[0]["production_stale"]
    with pytest.raises(ValueError, match="已变化"):
        execution.update(path, shot["id"], book["source_basis"], digest(shot), draft)


def test_rule_change_and_asset_description_change_require_new_director_decision(prepared):
    _, path, project, book, shot = prepared
    plan = preview(prepared)
    review.approve(path, [shot["id"]], "出发", book["source_basis"], decision(plan))
    project["characters"]["甲"]["description"] = "改变外观"
    store.write(path / "project.json", project)
    assert not preview(prepared)["approved"]
    assert review._file(path, "../../outside.png") is None
    draft = review.export(path, project, [shot["id"]], "出发", book["source_basis"])
    with zipfile.ZipFile(io.BytesIO(draft)) as archive:
        assert json.loads(archive.read("manifest.json"))["export_status"] == "draft"


def test_native_speech_placement_survives_prompt_compilation():
    from lib.prompts.prompt_utils import build_drama_video_prompt, video_prompt_to_yaml
    from lib.script.script_models import Utterance

    lines = [
        Utterance(kind="dialogue", speaker="甲", text="原文", delivery="inner"),
        Utterance(kind="voiceover", text="叙述", delivery="narration"),
    ]
    rendered = video_prompt_to_yaml(
        build_drama_video_prompt(
            {"action": "甲静坐", "camera_motion": "static", "ambiance_audio": "静"},
            lines,
            characters={"甲": {"voice_style": "沉静"}},
        )
    )
    assert "内心独白" in rendered
    assert "不张口" in rendered
    assert "叙述" in rendered
    assert Utterance(kind="dialogue", speaker="甲", text="旧数据").model_dump() == {
        "kind": "dialogue",
        "speaker": "甲",
        "text": "旧数据",
    }


async def test_ai_story_review_sees_only_selected_audio_visual_material_and_requires_human_reconfirmation(prepared):
    import asyncio
    from types import SimpleNamespace

    from lib.novel_workflow import production_advice

    _, path, _project, book, shot = prepared
    plan = await asyncio.to_thread(preview, prepared)
    await asyncio.to_thread(review.approve, path, [shot["id"]], "出发", book["source_basis"], decision(plan))

    class Generator:
        async def generate(self, request, **kwargs):
            material = json.JSONDecoder().raw_decode(request.prompt[request.prompt.index('{"selected_in_order":') :])[0]
            body = json.dumps(material, ensure_ascii=False)
            assert "source_file" not in body
            assert "basis_quote" not in body
            assert "evidence" not in body
            assert [s["id"] for s in material["selected_in_order"]] == [shot["id"]]
            return SimpleNamespace(
                text=json.dumps(
                    {"summary": "当前行动可理解", "audience_understanding": "甲取剑出发，乙还在门外", "findings": []}
                )
            )

    await production_advice.selection_story(
        path, Generator(), plan["note_ids"], book["source_basis"], [shot["id"]], "出发"
    )
    after = await asyncio.to_thread(preview, prepared)
    assert after["basis"] == plan["basis"]
    assert not after["approved"]
    assert after["ai_review"]
    assert await asyncio.to_thread(load_json, store.root(path) / "scene_library.json")


async def test_ai_execution_is_a_candidate_not_an_automatic_rewrite(prepared):
    import asyncio
    from types import SimpleNamespace

    from lib.novel_workflow import production_advice

    _, path, _project, book, shot = prepared
    initial = deepcopy(shot)
    edit = execution.ShotEdit.model_validate({"title": "候选标题", "segments": shot["segments"]})

    class Generator:
        async def generate(self, request, **kwargs):
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "edit": edit.model_dump(),
                        "reason": "按原文完善当前镜头执行方案，交编导采用",
                        "source_quotes": ["甲举起古剑"],
                    },
                    ensure_ascii=False,
                )
            )

    await production_advice.shot_draft(path, Generator(), [book["notes"][0]["id"]], book["source_basis"], [shot["id"]])
    saved = await asyncio.to_thread(load_json, store.root(path) / "scene_library.json")
    actual = saved["batches"]["n:0"]["scenes"][0]["shots"][0]
    assert actual["title"] == initial["title"]
    assert actual["segments"] == initial["segments"]
    assert actual["execution_draft"]["edit"]["title"] == "候选标题"
    assert execution.content_basis(actual) == execution.content_basis(initial)


def test_registered_visual_variant_retains_voice_owner_in_final_video_prompt():
    from lib.prompts.prompt_utils import build_drama_video_prompt

    prompt = build_drama_video_prompt(
        {"action": "人物静坐"},
        [{"kind": "dialogue", "speaker": "甲/湿衣", "text": "内心声音", "delivery": "inner"}],
        characters={"甲": {"voice_style": "平静", "derivatives": {"湿衣": {"description": "湿衣外观"}}}},
    )
    assert prompt["voice_profiles"] == [{"Speaker": "甲/湿衣", "Voice_Style": "平静"}]


def test_reference_assembly_does_not_require_approval_or_a_speech_budget(prepared):
    from lib.novel_workflow.director import assemble

    manager, path, project, book, shot = prepared
    file = store.root(path) / "scene_library.json"
    library = load_json(file)
    batch = library["batches"]["n:0"]
    raw = batch["scenes"][0]["shots"][0]
    raw["segments"][0]["duration_seconds"] = 1
    reading = store.valid_readings(path, book)[batch["note_id"]]
    batch["production_basis"] = planning_inputs(
        batch["production_context"], store.effective_rule(path, "shot_production"), {raw["id"]: raw}, project, reading
    )[2]
    store.write(file, library)
    episode = assemble(manager, "demo", [shot["id"]], "出发", book["source_basis"], "reference")
    current = manager.load_project("demo")
    plan = review.handoff(path, current, [shot["id"]], "出发", book["source_basis"])
    assert plan["episode"] == episode
    assert not plan["approved"]
    assert plan["seconds"] == 1
    assert not any(i["code"] == "timing" for i in plan["issues"])
    with zipfile.ZipFile(
        io.BytesIO(review.export(path, current, [shot["id"]], "出发", book["source_basis"]))
    ) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["shots"][0]["scene"]["purpose"] == "行动"
        assert "story_links" in manifest["shots"][0]


def test_story_advice_accepts_cross_shot_explanation_and_attaches_real_material():
    from lib.novel_workflow.production_advice import StoryAdvice, ground_story_advice

    visible = [
        {"id": "SH-1", "segments": [{"scene_description": "怪物扑来", "utterances": []}]},
        {"id": "SH-2", "segments": [{"scene_description": "阳子走进教室", "utterances": []}]},
    ]
    value = StoryAdvice(
        summary="转场待编导判断",
        audience_understanding="两个场景之间没有可见过渡",
        findings=[
            {
                "kind": "transition",
                "shot_ids": ["SH-1", "SH-2"],
                "reason": "跨度较大",
                "visible_evidence": "前镜是“怪物扑来”；后镜是“阳子走进教室”，缺少过渡说明。",
                "suggestion": "由编导判断是否增加转场",
            }
        ],
    )
    result = ground_story_advice(value, visible, ["SH-1", "SH-2"])
    assert result["findings"][0]["evidence"] == visible
    value.findings[0].shot_ids = ["SH-other"]
    with pytest.raises(ValueError, match="实际选中镜头"):
        ground_story_advice(value, visible, ["SH-1", "SH-2"])


@pytest.mark.parametrize("unresolved", [None, "无名路人"])
def test_unresolved_speaker_uses_pending_asset_without_blocking_reference_episode(prepared, unresolved):
    from lib.novel_workflow.director import assemble

    manager, path, project, book, shot = prepared
    file = store.root(path) / "scene_library.json"
    library = load_json(file)
    batch = library["batches"]["n:0"]
    raw = batch["scenes"][0]["shots"][0]
    raw["segments"][0]["utterances"][0]["speaker"] = unresolved
    reading = store.valid_readings(path, book)[batch["note_id"]]
    batch["production_basis"] = planning_inputs(
        batch["production_context"], store.effective_rule(path, "shot_production"), {raw["id"]: raw}, project, reading
    )[2]
    store.write(file, library)
    episode = assemble(manager, "demo", [shot["id"]], "含待定路人", book["source_basis"], "pending")
    current = manager.load_project("demo")
    pending = [
        (name, asset) for name, asset in current["characters"].items() if asset.get("identity_status") == "pending"
    ]
    assert len(pending) == 1
    name, asset = pending[0]
    assert asset["asset_code"]
    assert asset["first_note"]["id"] == book["notes"][0]["id"]
    saved = load_json(file)["batches"]["n:0"]["scenes"][0]["shots"][0]
    assert saved["segments"][0]["utterances"][0]["speaker"] == name
    assert name not in saved["segments"][0]["characters_in_scene"]
    assert saved["attribution_history"][-1]["confirmed_by"] == "reference_placeholder"
    assert assemble(manager, "demo", [shot["id"]], "含待定路人", book["source_basis"], "retry") == episode
    assert (
        len([a for a in manager.load_project("demo")["characters"].values() if a.get("identity_status") == "pending"])
        == 1
    )
    assert (path / "source/book.txt").read_text().startswith("# 第一章")
