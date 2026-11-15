"""Evidence-backed scene/shot candidates, before any episode exists."""

from __future__ import annotations

from difflib import SequenceMatcher
from uuid import uuid4

from lib.artifacts.formal_write import formal_write_transaction, project_metadata_lock
from lib.novel_workflow import chapters, store, understanding
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.evidence import expand_scene_excerpt, locate
from lib.novel_workflow.scene_models import Segment
from lib.novel_workflow.storage import load_json


def catalog(path):
    file = store.root(path) / "scene_library.json"
    return load_json(file) if file.exists() else {"batches": {}}


def svt_event_tags(path, note_id, reading):
    """Only local event membership crosses from SVTs; later summaries and endings never do."""
    file = store.root(path) / "svts.json"
    if not file.exists():
        return []
    value = load_json(file)
    if (
        value.get("schema_version") != 2
        or value.get("rule_basis") != digest(store.effective_rule(path, "svt"))
        or value.get("note_bases", {}).get(note_id) != reading["basis"]
    ):
        return []
    local_ids = {event["id"] for event in reading["events"]}
    return [
        {"svt_id": svt["id"], "event_ids": [i for i in svt["event_ids"] if i in local_ids]}
        for svt in value.get("svts", [])
        if not svt.get("stale")
        and svt.get("breakdown_status") != "needs_review"
        and note_id in svt["note_ids"]
        and value.get("note_assignments", {}).get(note_id) == svt["id"]
    ]


def stale_reasons(path, batch, notebook, readings, dependency_cache=None):
    reasons = []
    if any(g.get("usage") == "reference" and set(g["note_ids"]) & set(batch["note_bases"]) for g in notebook["groups"]):
        reasons.append("reference_group")
    if batch["source_basis"] != notebook["source_basis"]:
        reasons.append("source")
    if batch.get("pipeline_version") != 2 and batch["rule_basis"] != digest(store.effective_rule(path, "scene_shots")):
        reasons.append("rules")
    if any(readings.get(i, {}).get("basis") != b for i, b in batch["note_bases"].items()):
        reasons.append("notes")
    reading = readings.get(batch["note_id"])
    if batch.get("pipeline_version") == 2:
        from lib.novel_workflow import scene_material, scene_pipeline

        note = next((n for n in notebook["notes"] if n["id"] == batch["note_id"]), None)
        try:
            if note is None or reading is None:
                raise ValueError("原章节已不在当前目录或尚无有效 Note")
            cache = dependency_cache if dependency_cache is not None else {}
            if batch["note_id"] not in cache:
                current = scene_material.load(path, note, reading)
                cache[batch["note_id"]] = scene_pipeline.dependencies(path, current)
            deps = cache[batch["note_id"]]
            # Review rules update the review stage, not the narrative draft itself.
            old = batch.get("dependencies", {})
            if any(old.get(k) != deps[k] for k in ("material", "outline_rule", "shot_rule")):
                reasons.append("rules")
        except (ValueError, FileNotFoundError, KeyError):
            reasons.append("notes")
    if "svt_basis" in batch:
        tags = svt_event_tags(path, batch["note_id"], reading) if reading else []
        if len(tags) != 1 or batch["svt_basis"] != digest(tags):
            reasons.append("svt")
    try:
        understanding.require_understood(path, list(batch["note_bases"]))
        if (
            batch["understanding_basis"]
            != understanding.production_context(
                path, list(batch["note_bases"]), source_offset=batch.get("source_start")
            )["basis"]
        ):
            reasons.append("understanding")
    except ValueError:
        reasons.append("understanding")
    return reasons


def valid_batch(path, batch, notebook, readings):
    return not stale_reasons(path, batch, notebook, readings)


def view(path, notebook, readings, *, shot_ids=None):
    from lib.novel_workflow.shot_production import context, issues, planning_inputs

    library = catalog(path)
    batches = [
        b
        for b in library["batches"].values()
        if (b.get("pipeline_version") == 2 or b["note_id"] not in library.get("plans", {}))
        and (
            shot_ids is None
            or any(s["id"] in shot_ids for scene in b["scenes"] for s in scene["shots"])
        )
    ]
    project = load_json(path / "project.json")
    chunk_cache = {}
    dependency_cache = {}
    current_batches = []
    for batch in batches:
        batch["stale_reasons"] = stale_reasons(path, batch, notebook, readings, dependency_cache)
        batch["stale"] = bool(batch["stale_reasons"])
        if batch["stale"]:
            continue
        current_batches.append(batch)
        batch["production_stale"] = False
        if batch.get("pipeline_version") == 2:
            from lib.novel_workflow.scene_inspection import pending_shots

            batch["review_pending_shot_ids"] = pending_shots(
                batch, dependency_cache[batch["note_id"]]["inspection_rule"]
            )
            batch["review_pending"] = bool(batch["review_pending_shot_ids"])
        if (
            batch.get("pipeline_version") != 2
            and not batch["stale"]
            and batch.get("production_context")
            and batch["note_id"] in readings
        ):
            note_id = batch["note_id"]
            if note_id not in chunk_cache:
                note = next(n for n in notebook["notes"] if n["id"] == note_id)
                chunk_cache[note_id] = chapters.chunks(path, project, note)
            chunk = chunk_cache[note_id][batch["part"]]
            ctx = context(path, readings[note_id], chunk)
            rules = store.effective_rule(path, "scene_shots")
            shots = {sh["id"]: sh for sc in batch["scenes"] for sh in sc["shots"]}
            batch["production_stale"] = (
                batch.get("production_basis") != planning_inputs(ctx, rules, shots, project, readings[note_id])[2]
            )
        if batch["source_basis"] == notebook["source_basis"]:
            from lib.novel_workflow.dialogue_coverage import report

            note_id = batch["note_id"]
            coverage_reading = readings.get(note_id)
            if coverage_reading:
                from lib.novel_workflow.scene_source import source_chunk

                batch["dialogue_coverage"] = report(batch, coverage_reading, source_chunk(path, project, batch))
        if "review" in batch:
            batch["review_revision"] = digest(batch["review"])
        for scene in batch["scenes"]:
            for shot in scene["shots"]:
                shot["revision"] = digest(shot)
                shot["issues"] = issues(shot)
                from lib.novel_workflow.execution import inspect

                shot["execution_checks"] = inspect(shot, project)
                if shot.get("execution_draft"):
                    from lib.novel_workflow.execution import content_basis

                    draft = shot["execution_draft"]
                    draft["stale"] = draft["basis"] != content_basis(shot) or draft.get("rule_basis") != digest(
                        store.effective_rule(path, "shot_execution")
                    )
    return sorted(current_batches, key=lambda b: (b["note_order"], b["part"]))


def selected_shots(path, notebook, readings, ids):
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("请选择不重复的镜头")
    available = {}
    for batch in view(path, notebook, readings, shot_ids=set(ids)):
        for scene in batch["scenes"]:
            for shot in scene["shots"]:
                available[shot["id"]] = (batch, scene, shot)
    if any(i not in available or available[i][0]["stale"] for i in ids):
        raise ValueError("所选场镜已变化或依据失效，请刷新场镜素材库")
    return [available[i] for i in ids]


def in_chunk(evidence, chunk):
    return (
        evidence["source_file"] == chunk["source_file"]
        and evidence["note_id"] == chunk["note_id"]
        and chunk["start"] <= evidence["start"]
        and evidence["end"] <= chunk["end"]
    )


def asset_available(asset, chunk):
    evidence = asset["evidence"]
    return in_chunk(evidence, chunk) or (
        evidence["source_file"] == chunk["source_file"]
        and evidence["note_id"] == chunk["note_id"]
        and evidence["end"] <= chunk["start"]
        and asset["raw_name"] in chunk["text"]
    )


def ground(value, chunk, assets, durations):
    if not value.scenes and not value.skipped_reason.strip():
        raise ValueError("不生成场镜时必须说明跳过原因")
    for scene in value.scenes:
        for shot in scene.shots:
            try:
                start, end = locate(chunk["text"], shot.quote)
            except ValueError:
                try:
                    start, end = expand_scene_excerpt(chunk["text"], shot.quote)
                except ValueError as exc:
                    match = SequenceMatcher(None, shot.quote[:600], chunk["text"]).find_longest_match()
                    matched = chunk["text"][match.b : match.b + match.size]
                    hint = ""
                    if len("".join(matched.split())) >= 8 and chunk["text"].count(matched) == 1:
                        start = max(0, match.b - 60)
                        excerpt = chunk["text"][start : start + 240]
                        hint = f"。补正参考（附近连续原文，仍须逐字核对，不代表完整镜头依据）：{excerpt}"
                    raise ValueError(
                        f"镜头《{shot.title}》依据必须是当前原文中的逐字摘录（允许排版空白差异）：{shot.quote[:600]}"
                        + hint
                    ) from exc
            shot.quote = chunk["text"][start:end]
            uttered = []
            total_seconds = sum(seg.duration_seconds for seg in shot.segments)
            if len(shot.segments) > 1 and total_seconds <= 15:
                if total_seconds not in durations:
                    raise ValueError("不超过15秒的镜头应使用单个片段；合计时长必须是模型支持档位")
                # This is one logical shot. Keep every action and utterance in order, without a model rewrite.
                shot.segments = [
                    Segment(
                        duration_seconds=total_seconds,
                        scene_description="\n".join(seg.scene_description for seg in shot.segments),
                        characters_in_scene=list(
                            dict.fromkeys(name for seg in shot.segments for name in seg.characters_in_scene)
                        ),
                        scenes=list(dict.fromkeys(name for seg in shot.segments for name in seg.scenes)),
                        props=list(dict.fromkeys(name for seg in shot.segments for name in seg.props)),
                        utterances=[u for seg in shot.segments for u in seg.utterances],
                    )
                ]
            for segment in shot.segments:
                if segment.duration_seconds not in durations:
                    raise ValueError("片段时长不在当前模型支持档位内")
                for field, kind in [("characters_in_scene", "character"), ("scenes", "scene"), ("props", "prop")]:
                    unknown = set(getattr(segment, field)) - assets[kind]
                    if unknown:
                        raise ValueError(
                            f"镜头《{shot.title}》的 {field} 引用了未登记资产：{sorted(unknown)}。"
                            f"当前可引用：{sorted(assets[kind])}。普通背景物可保留在画面描述中，不要伪造资产引用。"
                        )
                for utterance in segment.utterances:
                    if utterance.text not in chunk["text"]:
                        try:
                            start, end = locate(chunk["text"], utterance.text)
                            utterance.text = chunk["text"][start:end]
                        except ValueError as exc:
                            raise ValueError(f"对白或旁白必须有当前原文的逐字依据：{utterance.text[:100]}") from exc
                    uttered.append(utterance.text)
                    if uttered.count(utterance.text) > chunk["text"].count(utterance.text):
                        raise ValueError("不得在SEG之间重复复制整段对白")
                    if utterance.speaker and utterance.speaker not in assets["character"]:
                        raise ValueError("说话人必须引用当前可用的已登记人物资产")
                    if (
                        utterance.delivery == "on_screen"
                        and utterance.speaker
                        and utterance.speaker not in segment.characters_in_scene
                    ):
                        raise ValueError("画内对白的说话人必须出现在本镜头角色列表中")
    return value.model_dump()


async def generate(path, generator, note_ids, expected, *, durations=None):
    from lib.novel_workflow.scene_pipeline import generate as run_pipeline

    return await run_pipeline(path, generator, note_ids, expected, durations=durations)


def require_attributed(shot):
    for segment in shot["segments"]:
        for utterance in segment["utterances"]:
            if utterance["kind"] == "dialogue" and not (utterance.get("speaker") or "").strip():
                raise ValueError(
                    f"{shot['id']} 有对白尚未确认说话人：{utterance['text'][:60]}。请在场镜素材库确认后再组集。"
                )


def attribute_dialogue(
    path,
    project,
    shot_id,
    segment_index,
    utterance_index,
    speaker,
    expected,
    shot_basis,
    register_role=False,
    *,
    pending_reference=False,
):
    """Human attribution is local, versioned and guarded against stale edits."""
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        notebook = store.require_current(path, project, expected)
        reading = store.valid_readings(path, notebook)
        library = catalog(path)
        for batch in library["batches"].values():
            for scene in batch["scenes"]:
                for shot in scene["shots"]:
                    if shot["id"] != shot_id:
                        continue
                    if not valid_batch(path, batch, notebook, reading) or digest(shot) != shot_basis:
                        raise ValueError("镜头已变化，请刷新后确认说话人")
                    try:
                        segment = shot["segments"][segment_index]
                        utterance = segment["utterances"][utterance_index]
                    except IndexError as exc:
                        raise ValueError("对白位置不存在") from exc
                    if segment_index < 0 or utterance_index < 0 or utterance["kind"] != "dialogue":
                        raise ValueError("只能确认角色对白的说话人")
                    from lib.novel_workflow.shot_production import asset_bindings, planning_inputs

                    shots = {sh["id"]: sh for sc in batch["scenes"] for sh in sc["shots"]}
                    rules = store.effective_rule(path, "scene_shots")
                    ctx = batch.get("production_context")
                    production_current = bool(
                        ctx
                        and batch.get("production_basis")
                        == planning_inputs(ctx, rules, shots, project, reading[batch["note_id"]])[2]
                    )
                    proposal = None
                    if register_role:
                        from lib.novel_workflow.scene_source import batch_source
                        from lib.novel_workflow.source_roles import register

                        proposal = next(
                            (
                                x
                                for x in shot.get("speaker_suggestions", {}).get("items", [])
                                if x["segment_index"] == segment_index
                                and x["utterance_index"] == utterance_index
                                and x.get("proposed_role") == speaker
                                and x.get("speaker") is None
                            ),
                            None,
                        )
                        if not proposal or not proposal.get("source_quote"):
                            raise ValueError("新增角色必须采用当前镜头中有原文依据的角色建议")
                        original = batch_source(path, project, batch["basis"])
                        begin, end = locate(original["text"], proposal["source_quote"])
                        note = next(n for n in notebook["notes"] if n["id"] == batch["note_id"])
                        ev = {
                            "note_id": note["id"],
                            "source_file": original["source_file"],
                            "start": original["start"] + begin,
                            "end": original["start"] + end,
                            "quote": original["text"][begin:end],
                        }
                        store.write(store.root(path) / "history" / f"source-role-project-{uuid4().hex}.json", project)
                        speaker = register(project, note, reading[batch["note_id"]]["basis"], speaker, ev)
                    if pending_reference:
                        from lib.novel_workflow.pending_speakers import register as register_pending

                        store.write(
                            store.root(path) / "history" / f"pending-speaker-project-{uuid4().hex}.json", project
                        )
                        speaker = register_pending(project, notebook, shot, segment_index, utterance_index)
                    if speaker not in project.get("characters", {}):
                        raise ValueError("请选择项目中已登记的人物资产；未明确身份可建立无名角色资产")
                    store.write(store.root(path) / "history" / f"scene-attribution-{uuid4().hex}.json", batch)
                    suggestion = proposal or next(
                        (
                            x
                            for x in shot.get("speaker_suggestions", {}).get("items", [])
                            if x["segment_index"] == segment_index
                            and x["utterance_index"] == utterance_index
                            and x.get("speaker") == speaker
                        ),
                        None,
                    )
                    utterance["speaker"] = speaker
                    if (
                        not pending_reference
                        and utterance.get("delivery") == "on_screen"
                        and speaker not in segment["characters_in_scene"]
                    ):
                        segment["characters_in_scene"].append(speaker)
                    shot.setdefault("attribution_history", []).append(
                        {
                            "segment": segment_index,
                            "utterance": utterance_index,
                            "speaker": speaker,
                            "confirmed_by": "reference_placeholder" if pending_reference else "human",
                            "created_at": now(),
                            **({"ai_suggestion": suggestion} if suggestion else {}),
                        }
                    )
                    if shot.get("production"):
                        shot["production"]["assets"] = asset_bindings(project, reading[batch["note_id"]], shot)
                    if production_current:
                        batch["production_basis"] = planning_inputs(
                            ctx, rules, shots, project, reading[batch["note_id"]]
                        )[2]
                    with formal_write_transaction(path / "project.json", store.root(path) / "scene_library.json"):
                        if register_role or pending_reference:
                            store.write(path / "project.json", project)
                        store.write(store.root(path) / "scene_library.json", library)
                    return {"shot_id": shot_id, "speaker": speaker}
        raise ValueError("镜头不存在")
