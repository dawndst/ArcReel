import json

import pytest

from lib.novel_workflow import shot_production as p
from lib.novel_workflow import store


def design():
    return dict.fromkeys(
        ["purpose", "shot_size", "camera_angle", "camera_movement", "framing", "continuity", "sound"], "明确的镜头设计"
    )


def test_decisions_require_exact_shot_set_and_local_event_and_moment_membership():
    ctx = {"events": [{"id": "e"}], "moments": [{"id": "m", "event_ids": ["e"]}]}
    data = {"shots": [{"shot_id": "SH-9", "event_ids": ["e"], "moment_ids": ["m"], "design": design()}]}
    assert p.validate_decisions(p.Decisions.model_validate(data), {"SH-9": {}}, ctx)["shots"][0]["moment_ids"] == ["m"]
    data["shots"][0]["event_ids"] = ["future"]
    with pytest.raises(ValueError, match="当前可见"):
        p.validate_decisions(p.Decisions.model_validate(data), {"SH-9": {}}, ctx)
    with pytest.raises(ValueError, match="每个输入镜头"):
        p.validate_decisions(p.Decisions(shots=[]), {"SH-9": {}}, ctx)


def test_cross_chapter_moment_only_exposes_local_evidence(tmp_path, monkeypatch):
    from lib.novel_workflow import svt_contract

    chunk = {"note_id": "n1", "source_file": "book", "start": 0, "end": 100}
    ev = {"note_id": "n1", "source_file": "book", "start": 1, "end": 20}
    d = {"id": "d1", "quote": "现在出发", "evidence": ev}
    event = {"id": "e1", "title": "出发", "action": "拿起剑", "evidence": ev, "dialogues": [d]}
    m = {
        "event_ids": ["e1", "e2"],
        "dialogue_ids": ["d1", "d2"],
        "note_ids": ["n1", "n2"],
        "scene": "未来主角死亡",
        "reason": "后文结局",
    }
    svt = {"id": "svt", "note_ids": ["n1", "n2"], "climaxes": [m], "payoffs": []}
    monkeypatch.setattr(store, "state", lambda path: {})
    monkeypatch.setattr(store, "valid_readings", lambda path, notebook: {})
    monkeypatch.setattr(svt_contract, "valid_svts", lambda *args: [svt])
    result = p.context(tmp_path, {"events": [event]}, chunk)
    assert "未来主角死亡" not in json.dumps(result, ensure_ascii=False)
    moment = result["moments"][0]
    assert moment["partial"]
    assert moment["dialogues"] == [d]
    assert moment["event_ids"] == ["e1"]
    assert moment["id"] == p.context(tmp_path, {"events": [event]}, chunk)["moments"][0]["id"]


def test_assembly_inherits_design_and_variant_without_rewriting_dialogue():
    from lib.novel_workflow.director import content_from_selection

    segment = {
        "duration_seconds": 8,
        "scene_description": "景麒站立",
        "characters_in_scene": ["景麒"],
        "scenes": [],
        "props": [],
        "utterances": [{"kind": "dialogue", "speaker": "景麒", "text": "走吧"}],
    }
    shot = {
        "id": "sh",
        "evidence": {"quote": "景麒说走吧"},
        "segments": [segment],
        "production": {
            "design": design(),
            "assets": [{"kind": "character", "name": "景麒", "variant": "人形", "segments": [0]}],
        },
    }
    content, mapping = content_from_selection([({}, {"id": "sc"}, shot)], 1, "测试")
    row = content["scenes"][0]
    assert row["characters_in_scene"] == ["景麒/人形"]
    assert row["utterances"][0]["speaker"] == "景麒/人形"
    assert row["utterances"][0]["text"] == "走吧"
    assert "景别：明确的镜头设计" in row["scene_description"]
    assert mapping[0]["production"] == shot["production"]
    assert segment["characters_in_scene"] == ["景麒"]


def test_density_is_warning_and_missing_design_blocks_assembly():
    shot = {
        "segments": [{"duration_seconds": 5, "utterances": [{"kind": "dialogue", "speaker": None, "text": "字" * 50}]}]
    }
    assert {v["code"] for v in p.issues(shot)} == {"design", "speaker", "timing"}
    assert next(v for v in p.issues(shot) if v["code"] == "timing")["blocking"] is False
    with pytest.raises(ValueError, match="完善"):
        p.require_ready(shot, {})


def test_explicit_derivative_reference_survives_native_assembly():
    project = {
        "characters": {
            "景麒": {
                "asset_id": "root",
                "asset_code": "CHR-1",
                "derivatives": {"兽形": {"asset_id": "form", "asset_code": "CHR-2"}},
            }
        }
    }
    segment = {
        "characters_in_scene": ["景麒/兽形"],
        "utterances": [{"kind": "dialogue", "speaker": "景麒", "text": "走吧"}],
    }
    shot = {"evidence": {}, "segments": [segment]}
    bindings = p.asset_bindings(project, {"assets": []}, shot)
    assert bindings[0]["asset_id"] == "form"
    assert not bindings[0]["missing"]
    shot["production"] = {"assets": bindings}
    p.require_ready(shot, project)
    result = p.native_segment(segment, shot["production"], 0)
    assert result["characters_in_scene"] == ["景麒/兽形"]
    assert result["utterances"][0] == {"kind": "dialogue", "speaker": "景麒/兽形", "text": "走吧"}


def test_conclusion_constraints_are_bounded_by_chunk_end(tmp_path, monkeypatch):
    from lib.novel_workflow import conclusions, svt_contract

    note = {"id": "n1", "order": 1}
    monkeypatch.setattr(store, "state", lambda path: {"notes": [note]})
    monkeypatch.setattr(store, "valid_readings", lambda *args: {})
    monkeypatch.setattr(svt_contract, "valid_svts", lambda *args: [])
    monkeypatch.setattr(conclusions, "enabled", lambda path: True)
    items = [
        {
            "id": str(end),
            "status": "partial",
            "production_constraint": "不得表现为已确认身份",
            "answer": "后文秘密",
            "evidence": [{"note_id": "n1", "end": end}],
        }
        for end in (20, 100, 101)
    ]
    monkeypatch.setattr(conclusions, "load", lambda *args: {"conclusions": items})
    chunk = {"note_id": "n1", "source_file": "book", "start": 50, "end": 100}
    result = p.context(tmp_path, {}, chunk)
    assert [c["id"] for c in result["conclusion_constraints"]] == ["20", "100"]
    assert "后文秘密" not in json.dumps(result, ensure_ascii=False)
    monkeypatch.setattr(conclusions, "enabled", lambda path: False)
    assert p.context(tmp_path, {}, chunk)["conclusion_constraints"] == []


def test_conclusion_context_survives_disabled_understanding(tmp_path, monkeypatch):
    from lib.novel_workflow import conclusions, settings, understanding

    monkeypatch.setattr(settings, "get", lambda path: {"understanding_enabled": False})
    monkeypatch.setattr(store, "state", lambda path: {"notes": [{"id": "n", "order": 1}]})
    monkeypatch.setattr(store, "valid_readings", lambda *args: {"n": {"assets": []}})
    monkeypatch.setattr(conclusions, "enabled", lambda path: True)
    monkeypatch.setattr(conclusions, "production_links", lambda *args: [])
    basis = {"n": "v1"}
    monkeypatch.setattr(conclusions, "input_bases", lambda *args: dict(basis))
    first = understanding.production_context(tmp_path, ["n"])
    basis["n"] = "v2"
    assert understanding.production_context(tmp_path, ["n"])["basis"] != first["basis"]
    monkeypatch.setattr(conclusions, "enabled", lambda path: False)
    assert understanding.production_context(tmp_path, ["n"])["basis"] != first["basis"]
