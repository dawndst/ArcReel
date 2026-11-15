"""Scene/shot model contracts select existing evidence; prose never rewrites dialogue."""

from typing import Literal

from pydantic import Field

from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_material import asset_available
from lib.novel_workflow.stage_runner import ContractError


class SourceAware(StrictModel):
    source_requests: list[str] = Field(default_factory=list)


class PlannedScene(StrictModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    location: str
    time: str
    purpose: str
    event_ids: list[str] = Field(min_length=1)
    primary_event_ids: list[str] = Field(min_length=1)
    skipped_reason: str = ""


class ScenePlan(SourceAware):
    scenes: list[PlannedScene] = Field(default_factory=list)


class DialogueUse(StrictModel):
    dialogue_id: str
    delivery: Literal["on_screen", "off_screen", "inner", "narration", "unclassified"]


class ShotSegment(StrictModel):
    duration_seconds: int = Field(ge=1, le=15, description="编导参考时长，不要求匹配供应商档位")
    start_frame: str = Field(min_length=1, max_length=2000)
    action: str = Field(min_length=1, max_length=4000)
    end_frame: str = Field(min_length=1, max_length=2000)
    visible_asset_ids: list[str] = Field(default_factory=list)
    dialogue: list[DialogueUse] = Field(default_factory=list)


class ShotDraft(StrictModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=1000)
    event_ids: list[str] = Field(min_length=1)
    moment_ids: list[str] = Field(default_factory=list)
    shot_size: str = Field(min_length=1, max_length=200)
    camera_angle: str = Field(min_length=1, max_length=200)
    camera_movement: str = Field(min_length=1, max_length=500)
    framing: str = Field(min_length=1, max_length=1000)
    continuity: str = Field(min_length=1, max_length=1500)
    sound: str = Field(min_length=1, max_length=1000)
    segments: list[ShotSegment] = Field(min_length=1, max_length=20)


class SceneShots(SourceAware):
    shots: list[ShotDraft] = Field(default_factory=list)
    omitted_dialogues: list[str] = Field(default_factory=list, description="未安排的源台词ID，保留供编导取舍")
    omission_reason: str = ""


def validate_plan(value, catalogue):
    issues, covered, keys = [], [], set()
    for i, scene in enumerate(value.scenes):
        base = ["scenes", i]
        for field in ("event_ids", "primary_event_ids"):
            ids = getattr(scene, field)
            if len(ids) != len(set(ids)) or not set(ids) <= set(catalogue.events):
                issues.append({"path": [*base, field], "message": "场面只能引用本章有效、不重复的事件ID"})
        if not set(scene.primary_event_ids) <= set(scene.event_ids):
            issues.append({"path": [*base, "primary_event_ids"], "message": "主承载事件必须属于本场引用事件"})
        if scene.key in keys:
            issues.append({"path": [*base, "key"], "message": "场面key不能重复"})
        keys.add(scene.key)
        valid_ids = [e for e in scene.event_ids if e in catalogue.events]
        if len({catalogue.sources[catalogue.events[e]["source_id"]]["source_file"] for e in valid_ids}) > 1:
            issues.append({"path": [*base, "event_ids"], "message": "一场不能跨原文文件，请分别规划"})
        covered.extend(scene.primary_event_ids)
    if set(covered) != set(catalogue.events) or len(covered) != len(set(covered)):
        issues.append(
            {
                "path": ["scenes"],
                "message": "本章每个事件必须有且仅有一场作为主承载；可另被其他场引用，省略也须列场说明",
            }
        )
    if issues:
        raise ContractError(issues)
    return value.model_dump()


def compile_shots(value, catalogue, unit):
    issues, keys, used_lines = [], set(), set()
    normalizations = []
    rows = []
    allowed_events = set(unit["event_ids"])
    allowed_lines = {d["id"] for d in catalogue.dialogues.values() if d["event_id"] in set(unit["primary_event_ids"])}
    allowed_moments = {m["id"]: m for m in catalogue.moments if set(m["event_ids"]) & allowed_events}
    covered = set()
    for i, shot in enumerate(value.shots):
        base = ["shots", i]
        if shot.key in keys:
            issues.append({"path": [*base, "key"], "message": "镜头key必须唯一"})
        keys.add(shot.key)
        if not set(shot.event_ids) <= allowed_events:
            issues.append({"path": [*base, "event_ids"], "message": "镜头只能认领本场事件"})
            continue
        if not set(shot.moment_ids) <= set(allowed_moments) or any(
            not set(allowed_moments[m]["event_ids"]) & set(shot.event_ids)
            for m in shot.moment_ids
            if m in allowed_moments
        ):
            issues.append({"path": [*base, "moment_ids"], "message": "爆点必须属于本场且与该镜承载的事件相符"})
        covered.update(shot.event_ids)
        source_ids = [catalogue.events[e]["source_id"] for e in shot.event_ids]
        segments, uses, pending = [], [], []
        cutoff = catalogue.chunk(shot.event_ids)["end"]
        for j, segment in enumerate(shot.segments):
            path = [*base, "segments", j]
            visible = {"character": [], "scene": [], "prop": []}
            for aid in segment.visible_asset_ids:
                a = catalogue.assets.get(aid)
                if not a or not asset_available(
                    catalogue, a, shot.event_ids, unit.get("scene_event_ids", unit["event_ids"])
                ):
                    issues.append(
                        {
                            "path": [*path, "visible_asset_ids"],
                            "message": "出镜资产尚未在该镜事件出现，不得引用未来形态；移除提前出镜的资产，或将镜头改为实际发生的后续事件。合法资产ID："
                            + ",".join(
                                k
                                for k, a in catalogue.assets.items()
                                if asset_available(
                                    catalogue, a, shot.event_ids, unit.get("scene_event_ids", unit["event_ids"])
                                )
                            ),
                        }
                    )
                    continue
                if a["pending"]:
                    pending.append({"source_asset_id": aid, "name": a["name"], "kind": a["kind"], "segment": j})
                    if a["name"] not in visible[a["kind"]]:
                        visible[a["kind"]].append(a["name"])
                else:
                    name = a["asset_name"] + (f"/{a['variant']}" if a["variant"] and a["kind"] == "character" else "")
                    if name not in visible[a["kind"]]:
                        visible[a["kind"]].append(name)
            utterances = []
            for use in segment.dialogue:
                d = catalogue.dialogues.get(use.dialogue_id)
                if use.dialogue_id in used_lines:
                    normalizations.append(
                        {
                            "code": "duplicate_source_dialogue",
                            "dialogue_id": use.dialogue_id,
                            "shot_key": shot.key,
                            "segment": j,
                        }
                    )
                    continue
                if use.dialogue_id not in allowed_lines:
                    issues.append(
                        {
                            "path": [*path, "dialogue"],
                            "message": f"台词ID {use.dialogue_id} 不属于当前窗口，须选择输入dialogues表中的原句ID；不改写台词。",
                        }
                    )
                    continue
                if d["event_id"] not in shot.event_ids:
                    issues.append({"path": [*base, "event_ids"], "message": "承载台词时必须关联其来源事件"})
                if catalogue.sources[d["source_id"]]["end"] > cutoff:
                    issues.append({"path": [*path, "dialogue"], "message": "台词不能提前取用后续事件"})
                used_lines.add(use.dialogue_id)
                source_ids.append(d["source_id"])
                speaker = next(
                    (
                        a["asset_name"]
                        for a in catalogue.assets.values()
                        if not a["pending"]
                        and a["kind"] == "character"
                        and a["name"] == d["speaker"]
                        and asset_available(
                            catalogue, a, shot.event_ids, unit.get("scene_event_ids", unit["event_ids"])
                        )
                    ),
                    None,
                )
                mode = use.delivery
                if (
                    mode == "on_screen"
                    and speaker
                    and not any(n == speaker or n.startswith(speaker + "/") for n in visible["character"])
                ):
                    issues.append(
                        {
                            "path": path,
                            "message": f"画内说话人{speaker}未绑定出镜资产；其候选ID为"
                            + ",".join(
                                k
                                for k, a in catalogue.assets.items()
                                if a.get("asset_name") == speaker
                                and catalogue.sources[a["source_id"]]["start"] < cutoff
                            )
                            + "。请修订本SEG的visible_asset_ids，或按真实演出改为off_screen/inner；不要重写台词。",
                        }
                    )
                if mode == "narration":
                    issues.append(
                        {"path": [*path, "dialogue"], "message": "来源角色台词不能改成叙述旁白；未知说话人保留未确认"}
                    )
                if mode == "on_screen" and speaker:
                    speaker = next(
                        (n for n in visible["character"] if n == speaker or n.startswith(speaker + "/")), speaker
                    )
                utterances.append(
                    {
                        "kind": "dialogue",
                        "speaker": speaker,
                        "text": d["text"],
                        "delivery": mode,
                        "origin": "source",
                        "basis_quote": "",
                    }
                )
                uses.append({"segment": j, "utterance": len(utterances) - 1, "dialogue_id": d["id"]})
            segments.append(
                {
                    "duration_seconds": segment.duration_seconds,
                    "start_frame": segment.start_frame,
                    "end_frame": segment.end_frame,
                    "scene_description": segment.action,
                    "characters_in_scene": visible["character"],
                    "scenes": visible["scene"],
                    "props": visible["prop"],
                    "utterances": utterances,
                    "asset_states": [],
                }
            )
        refs = [catalogue.sources[s] for s in dict.fromkeys(source_ids)]
        source = catalogue.chunk(shot.event_ids)
        start, end = min(r["start"] for r in refs), max(r["end"] for r in refs)
        evidence = {
            "note_id": catalogue.note["id"],
            "source_file": source["source_file"],
            "start": start,
            "end": end,
            "quote": catalogue.texts[source["source_file"]][start:end],
        }
        rows.append(
            {
                "local_key": shot.key,
                "title": shot.title,
                "segments": segments,
                "evidence": evidence,
                "quote": evidence["quote"],
                "source_refs": [catalogue.sources[s] for s in dict.fromkeys(source_ids)],
                "source_dialogue_uses": uses,
                "pending_asset_refs": pending,
                "reference_draft": shot.model_dump(),
                "production": {
                    "event_ids": shot.event_ids,
                    "moment_ids": shot.moment_ids,
                    "svt_id": catalogue.svt["id"],
                    "design": {
                        k: getattr(shot, k)
                        for k in (
                            "purpose",
                            "shot_size",
                            "camera_angle",
                            "camera_movement",
                            "framing",
                            "continuity",
                            "sound",
                        )
                    },
                    "assets": [],
                    "dialogue_sources": uses,
                },
            }
        )
    if not set(unit["primary_event_ids"]) <= covered:
        issues.append({"path": ["shots"], "message": "本场主承载事件未全部落镜；不得只生成部分事件就结束"})
    omitted = set(value.omitted_dialogues)
    if omitted - allowed_lines or omitted & used_lines or (allowed_lines - used_lines) != omitted:
        issues.append(
            {"path": ["omitted_dialogues"], "message": "未安排台词须逐个列出剩余原句ID；不能既承载又省略或静默遗漏"}
        )
    if omitted and not value.omission_reason.strip():
        issues.append(
            {"path": ["omission_reason"], "message": "省略台词须提供因果和理解不受损的具体取舍理由，供编导决定"}
        )
    if issues:
        # Multiple checks may describe one editable field.
        unique = {tuple(i["path"]): i for i in issues}
        raise ContractError(list(unique.values()))
    return {
        "shots": rows,
        "omitted_dialogues": sorted(omitted),
        "omission_reason": value.omission_reason,
        "normalizations": normalizations,
    }
