"""Shot decisions and traceable story links; native visual authoring remains the only prompt writer."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store
from lib.novel_workflow.assets import mentions as source_mentions
from lib.novel_workflow.assets import reference
from lib.novel_workflow.models import StrictModel
from lib.references.reference_catalog import split_derivative_reference


class ShotDesign(StrictModel):
    purpose: str = Field(min_length=1, max_length=1000)
    shot_size: str = Field(min_length=1, max_length=200)
    camera_angle: str = Field(min_length=1, max_length=200)
    camera_movement: str = Field(min_length=1, max_length=500)
    framing: str = Field(min_length=1, max_length=1000)
    continuity: str = Field(min_length=1, max_length=1500)
    sound: str = Field(min_length=1, max_length=1000)


class ShotDecisions(StrictModel):
    shot_id: str
    event_ids: list[str] = Field(default_factory=list)
    moment_ids: list[str] = Field(default_factory=list)
    design: ShotDesign


class Decisions(StrictModel):
    shots: list[ShotDecisions]


def within(evidence, chunk):
    return (
        evidence.get("note_id") == chunk["note_id"]
        and evidence.get("source_file") == chunk["source_file"]
        and chunk["start"] <= evidence.get("start", -1) < evidence.get("end", -1) <= chunk["end"]
    )


def context(path, reading, chunk):
    """Never pass a cross-chapter moment's complete synopsis into an earlier source fragment."""
    from lib.novel_workflow.svt_contract import valid_svts

    notebook = store.state(path)
    file = store.root(path) / "svts.json"
    data = load_json(file) if file.exists() else None
    live = valid_svts(path, data, store.valid_readings(path, notebook))
    svt = next(
        (s for s in live if chunk["note_id"] in s["note_ids"] and s.get("breakdown_status") != "needs_review"), None
    )
    events = [e for e in reading.get("events", []) if within(e["evidence"], chunk)]
    event_ids = {e["id"] for e in events}
    dialogues = {d["id"]: d for e in reading.get("events", []) for d in e.get("dialogues", [])}
    dialogues.update({d["id"]: d for d in reading.get("dialogues", [])})
    moments = []
    if svt:
        for kind in ("climaxes", "payoffs"):
            for m in svt.get(kind, []):
                local_ids = [i for i in m["event_ids"] if i in event_ids]
                local_dialogues = [
                    dialogues[i]
                    for i in m["dialogue_ids"]
                    if i in dialogues and within(dialogues[i]["evidence"], chunk)
                ]
                if not local_ids:
                    continue
                complete = (
                    set(m["event_ids"]) <= event_ids
                    and len(local_dialogues) == len(m["dialogue_ids"])
                    and set(m["note_ids"]) == {chunk["note_id"]}
                )
                moments.append(
                    {
                        "id": "MOM-" + digest([svt["id"], kind, m["event_ids"], m["dialogue_ids"], m["scene"]])[:20],
                        "kind": kind,
                        "svt_id": svt["id"],
                        "note_ids": [chunk["note_id"]],
                        "event_ids": local_ids,
                        "dialogues": local_dialogues,
                        "partial": not complete,
                        "scene": m["scene"]
                        if complete
                        else "；".join(e["title"] + "：" + e.get("action", "") for e in events if e["id"] in local_ids),
                        "reason": m["reason"] if complete else "跨片段爆点，仅展示当前原文可见部分。",
                    }
                )
    return {"svt_id": svt["id"] if svt else None, "events": events, "moments": moments}


def validate_decisions(value, shots, ctx):
    if len(value.shots) != len(shots) or {s.shot_id for s in value.shots} != set(shots):
        raise ValueError("每个输入镜头必须且只能返回一次；不得新增、删减或重排镜头")
    events = {e["id"] for e in ctx["events"]}
    moments = {m["id"]: m for m in ctx["moments"]}
    for item in value.shots:
        if not set(item.event_ids) <= events or not set(item.moment_ids) <= set(moments):
            raise ValueError("只关联输入中当前可见的事件和爆点")
        if any(not set(moments[i]["event_ids"]) & set(item.event_ids) for i in item.moment_ids):
            raise ValueError("镜头爆点关联必须有对应事件支持")
    return value.model_dump()


def asset_bindings(project, reading, shot):
    """Use existing asset registry and variants, not a second registry inside the shot."""
    result = []
    evidence = shot["evidence"]
    for field, kind, bucket in (
        ("characters_in_scene", "character", "characters"),
        ("scenes", "scene", "scenes"),
        ("props", "prop", "props"),
    ):
        for name in dict.fromkeys(n for seg in shot["segments"] for n in seg.get(field, [])):
            base, explicit_variant = split_derivative_reference(name) if kind == "character" else (name, "")
            mentions = []
            for mention in source_mentions(project, reading):
                ev = mention["evidence"]
                if (
                    mention["kind"] != kind
                    or ev["source_file"] != evidence["source_file"]
                    or ev["end"] > evidence["end"]
                ):
                    continue
                ref = reference(project, mention)
                if ref.get("asset_name") == base and not ref.get("asset_missing"):
                    mentions.append((ev["start"], ref))
            latest = max(mentions, key=lambda pair: pair[0])[1] if mentions else {}
            asset = project.get(bucket, {}).get(base, {})
            if explicit_variant:
                asset = asset.get("derivatives", {}).get(explicit_variant, {})
                latest = {
                    "asset_id": asset.get("asset_id"),
                    "asset_code": asset.get("asset_code"),
                    "variant": explicit_variant,
                }
            result.append(
                {
                    "kind": kind,
                    "name": base,
                    **({"reference": name} if explicit_variant else {}),
                    "asset_id": latest.get("asset_id", asset.get("asset_id")),
                    "asset_code": latest.get("asset_code", asset.get("asset_code")),
                    "variant": latest.get("variant"),
                    **({"state": latest["state"]} if latest.get("state") else {}),
                    "segments": [i for i, seg in enumerate(shot["segments"]) if name in seg.get(field, [])],
                    "missing": not bool(latest.get("asset_id", asset.get("asset_id")))
                    or bool(latest.get("asset_issue") and latest.get("asset_issue_blocking", True)),
                }
            )
    return result


def dialogue_links(reading, shot):
    dialogues = {d["id"]: d for e in reading.get("events", []) for d in e.get("dialogues", [])}
    dialogues.update({d["id"]: d for d in reading.get("dialogues", [])})
    result = []
    for i, segment in enumerate(shot["segments"]):
        for j, u in enumerate(segment["utterances"]):
            text = "".join(u["text"].split()).strip('「」『』“”‘’"')
            candidates = [
                d
                for d in dialogues.values()
                if text
                and text in "".join(d["quote"].split())
                and d["evidence"]["note_id"] == shot["evidence"]["note_id"]
                and shot["evidence"]["start"]
                <= d["evidence"]["start"]
                < d["evidence"]["end"]
                <= shot["evidence"]["end"]
            ]
            result.append(
                {"segment": i, "utterance": j, "dialogue_id": candidates[0]["id"] if len(candidates) == 1 else None}
            )
    return result


def issues(shot):
    result = []
    if not shot.get("production"):
        result.append({"code": "design", "blocking": True})
    for i, seg in enumerate(shot["segments"]):
        if any(u["kind"] == "dialogue" and not u.get("speaker") for u in seg["utterances"]):
            result.append({"code": "speaker", "segment": i, "blocking": True})
        if sum(len(u["text"]) for u in seg["utterances"]) > seg["duration_seconds"] * 6:
            result.append({"code": "timing", "segment": i, "blocking": False})
    result.extend(
        {"code": "asset", "blocking": True}
        for asset in shot.get("production", {}).get("assets", [])
        if asset.get("missing")
    )
    return result


def design_text(production):
    if not production:
        return ""
    labels = {
        "purpose": "镜头目的",
        "shot_size": "景别",
        "camera_angle": "机位",
        "camera_movement": "运镜",
        "framing": "构图与调度",
        "continuity": "连续性与起止状态",
        "sound": "声音设计",
    }
    states = "\n".join(f"资产状态：{a['name']}：{a['state']}" for a in production.get("assets", []) if a.get("state"))
    return (
        states
        + "\n镜头设计（改编决定，视觉提示词须继承，不改变已定动作和台词）：\n"
        + "\n".join(f"{label}：{production['design'][key]}" for key, label in labels.items())
    )


async def complete_batch(path, generator, batch, reading, project, chunk):
    from lib.novel_workflow.service import ask

    ctx = await asyncio.to_thread(context, path, reading, chunk)
    rules = await asyncio.to_thread(store.effective_rule, path, "shot_production")
    shots = {sh["id"]: sh for sc in batch["scenes"] for sh in sc["shots"]}
    clean, bindings, basis = planning_inputs(ctx, rules, shots, project, reading)
    if batch.get("production_basis") == basis and all(sh.get("production") for sh in shots.values()):
        return
    if not ctx["svt_id"] or not ctx["events"]:
        raise ValueError("本片段缺少可用主线事件，请先完善 Note 与 SVT")
    progress_file = store.root(path) / "progress.json"
    progress = (
        await asyncio.to_thread(load_json, progress_file) if await asyncio.to_thread(progress_file.exists) else {}
    )
    await run_noninterruptible_sync(store.write, progress_file, {**progress, "step": "production"})
    cache = store.root(path) / "shot_decisions" / f"{basis}.json"
    if await asyncio.to_thread(cache.exists):
        result = await asyncio.to_thread(load_json, cache)
    else:
        result = await ask(
            path,
            generator,
            Decisions,
            rules
            + "\n"
            + json.dumps(
                {"original": chunk["text"], "context": ctx, "shots": clean, "asset_bindings": bindings},
                ensure_ascii=False,
            ),
            lambda value: validate_decisions(value, shots, ctx),
            max_output_tokens=16000,
            grow_output=True,
        )
        await run_noninterruptible_sync(store.write, cache, result)

    def commit():
        from lib.novel_workflow.scene_library import catalog

        with project_metadata_lock(path):
            library = catalog(path)
            current = next((b for b in library["batches"].values() if b["basis"] == batch["basis"]), None)
            if current != batch:
                raise ValueError("场镜在完善期间已被编辑，请刷新重试；已保留模型结果")
            fresh = load_json(path / "project.json")
            if context(path, reading, chunk) != ctx or planning_inputs(ctx, rules, shots, fresh, reading)[2] != basis:
                raise ValueError("主线或爆点在完善期间已变化，请刷新重试")
            store.write(store.root(path) / "history" / f"shot-decisions-{uuid4().hex}.json", current)
            for item in result["shots"]:
                sh = next(sh for sc in current["scenes"] for sh in sc["shots"] if sh["id"] == item["shot_id"])
                sh["production"] = {
                    **item,
                    "svt_id": ctx["svt_id"],
                    "assets": asset_bindings(fresh, reading, sh),
                    "dialogue_sources": dialogue_links(reading, sh),
                }
            current.update(
                production_basis=basis,
                production_context=ctx,
                production_rule_basis=digest(rules),
                production_updated_at=now(),
            )
            store.write(store.root(path) / "scene_library.json", library)

    await run_noninterruptible_sync(commit)


def update(path, project, shot_id, expected, revision, decisions):
    from lib.novel_workflow.scene_library import catalog, valid_batch

    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        library = catalog(path)
        for b in library["batches"].values():
            for sc in b["scenes"]:
                for sh in sc["shots"]:
                    if sh["id"] != shot_id:
                        continue
                    if digest(sh) != revision or not valid_batch(
                        path, b, notebook, store.valid_readings(path, notebook)
                    ):
                        raise ValueError("场镜已变化，请刷新后编辑")
                    if not sh.get("production"):
                        raise ValueError("请先完善镜头制作信息")
                    if decisions.shot_id != shot_id:
                        raise ValueError("镜头ID不一致")
                    validate_decisions(Decisions(shots=[decisions]), {shot_id: sh}, b["production_context"])
                    store.write(store.root(path) / "history" / f"shot-edit-{uuid4().hex}.json", b)
                    sh["production"].update(decisions.model_dump())
                    store.write(store.root(path) / "scene_library.json", library)
                    return {"shot_id": shot_id}
        raise ValueError("镜头不存在")


def native_segment(segment, production, index):
    """Project library bindings into the native name/variant reference syntax once at assembly."""
    value = deepcopy(segment)
    from lib.speech.delivery import DELIVERY_DIRECTIONS

    start, end = value.pop("start_frame", ""), value.pop("end_frame", "")
    states = value.pop("asset_states", [])
    instructions = []
    if start:
        instructions.append("起始画面：" + start)
    if end:
        instructions.append("结束画面与下片段衔接：" + end)
    instructions.extend(
        f"资产状态 {state['name']}（{state['visibility']}）：{state.get('start', '')} → {state.get('end', '')}；{state.get('attachment', '')}"
        for state in states
    )
    for line in value.get("utterances", []):
        line.pop("origin", None)
        line.pop("basis_quote", None)
        mode = line.get("delivery") or ("narration" if line["kind"] == "voiceover" else None)
        if mode == "narration":
            line["delivery"] = "narration"
        if mode == "unclassified":
            line.pop("delivery", None)
        elif mode in DELIVERY_DIRECTIONS:
            instructions.append(f"发声 {line.get('speaker') or '叙述旁白'}：{DELIVERY_DIRECTIONS[mode]}")
    if instructions:
        value["scene_description"] += "\n" + "\n".join(instructions)
    return effective_segment(value, production, index)


def effective_segment(segment, production, index):
    """Resolve bound visual variants consistently for review, handoff and native publication."""
    from lib.references.reference_catalog import derivative_reference

    value = deepcopy(segment)
    if not production:
        return value
    for binding in production.get("assets", []):
        if index not in binding["segments"]:
            continue
        name = binding["name"]
        source = binding.get("reference", name)
        target = derivative_reference(name, binding["variant"]) if binding.get("variant") else name
        field = {"character": "characters_in_scene", "scene": "scenes", "prop": "props"}[binding["kind"]]
        value[field] = [target if n == source else n for n in value[field]]
        for state in value.get("asset_states", []):
            if state["kind"] == binding["kind"] and state["name"] == source:
                state["name"] = target
        if binding["kind"] == "character":
            for u in value["utterances"]:
                if u.get("speaker") in {source, name}:
                    u["speaker"] = target
    return value


def require_ready(shot, project):
    if not shot.get("production"):
        raise ValueError("请先在场镜素材库完善镜头设计与爆点关联，再组集")
    for binding in shot["production"]["assets"]:
        bucket = {"character": "characters", "scene": "scenes", "prop": "props"}[binding["kind"]]
        asset = project.get(bucket, {}).get(binding["name"], {})
        if binding.get("variant"):
            asset = asset.get("derivatives", {}).get(binding["variant"], {})
        if not binding.get("asset_id") or asset.get("asset_id") != binding["asset_id"]:
            raise ValueError("镜头资产已删除或改名，请更新制作信息后再组集")


def planning_inputs(ctx, rules, shots, project, reading):
    clean = {
        key: {
            k: v
            for k, v in sh.items()
            if k
            not in (
                "production",
                "revision",
                "issues",
                "speaker_suggestions",
                "execution_draft",
                "edit_history",
                "execution_checks",
            )
        }
        for key, sh in shots.items()
    }
    bindings = {key: asset_bindings(project, reading, sh) for key, sh in shots.items()}
    return clean, bindings, digest([ctx, rules, clean, bindings])
