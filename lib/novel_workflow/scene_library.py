"""Evidence-backed scene/shot candidates, before any episode exists."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding.service import check_stop
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import chapters, store, understanding
from lib.novel_workflow.evidence import locate
from lib.novel_workflow.scene_models import SceneBatch


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
        or value.get("rule_basis") != digest(store.rule(path, "svt"))
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


def valid_batch(path, batch, notebook, readings):
    if any(g.get("usage") == "reference" and set(g["note_ids"]) & set(batch["note_bases"]) for g in notebook["groups"]):
        return False
    if batch["source_basis"] != notebook["source_basis"] or batch["rule_basis"] != digest(store.rule(path, "scenes")):
        return False
    if any(readings.get(i, {}).get("basis") != b for i, b in batch["note_bases"].items()):
        return False
    if "svt_basis" in batch and len(svt_event_tags(path, batch["note_id"], readings[batch["note_id"]])) != 1:
        return False
    if "svt_basis" in batch and batch["svt_basis"] != digest(
        svt_event_tags(path, batch["note_id"], readings[batch["note_id"]])
    ):
        return False
    try:
        understanding.require_understood(path, list(batch["note_bases"]))
        return (
            batch["understanding_basis"] == understanding.production_context(path, list(batch["note_bases"]))["basis"]
        )
    except ValueError:
        return False


def view(path, notebook, readings):
    batches = list(catalog(path)["batches"].values())
    for batch in batches:
        batch["stale"] = not valid_batch(path, batch, notebook, readings)
        if "review" in batch:
            batch["review_revision"] = digest(batch["review"])
        for scene in batch["scenes"]:
            for shot in scene["shots"]:
                shot["revision"] = digest(shot)
    return sorted(batches, key=lambda b: (b["note_order"], b["part"]))


def selected_shots(path, notebook, readings, ids):
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("请选择不重复的镜头")
    available = {}
    for batch in view(path, notebook, readings):
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
            except ValueError as exc:
                raise ValueError("镜头依据必须是当前原文中的逐字摘录（允许排版空白差异）") from exc
            shot.quote = chunk["text"][start:end]
            uttered = []
            if len(shot.segments) > 1 and sum(seg.duration_seconds for seg in shot.segments) <= 15:
                raise ValueError("不超过15秒的镜头应使用单个片段")
            for segment in shot.segments:
                if segment.duration_seconds not in durations:
                    raise ValueError("片段时长不在当前模型支持档位内")
                for field, kind in [("characters_in_scene", "character"), ("scenes", "scene"), ("props", "prop")]:
                    if not set(getattr(segment, field)) <= assets[kind]:
                        raise ValueError("镜头引用了当前阅读资料以外的资产")
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
                    if utterance.speaker and utterance.speaker not in segment.characters_in_scene:
                        raise ValueError("说话人必须出现在本镜头角色列表中")
    return value.model_dump()


async def generate(path, generator, note_ids, expected, *, durations=None):
    from lib.novel_workflow.assets import reference
    from lib.novel_workflow.service import ask, current

    notebook = await asyncio.to_thread(current, path, expected)
    readings = await asyncio.to_thread(store.valid_readings, path, notebook)
    notes = [n for n in notebook["notes"] if n["id"] in note_ids]
    if not notes or len(notes) != len(set(note_ids)) or any(n["id"] not in readings for n in notes):
        raise ValueError("请先为所选章节泛读生成 Notes")
    if any(g.get("usage") == "reference" and set(g["note_ids"]) & set(note_ids) for g in notebook["groups"]):
        raise ValueError("所选章节包含仅留档资料，请先改为改编候选再生成场镜")
    from lib.novel_workflow.svt_contract import assignments, valid_svts

    svt_file = store.root(path) / "svts.json"
    svt_data = await asyncio.to_thread(load_json, svt_file) if await asyncio.to_thread(svt_file.exists) else None
    live_svts = await asyncio.to_thread(valid_svts, path, svt_data, readings)
    primary = assignments(live_svts)
    if any(n["id"] not in primary for n in notes):
        raise ValueError("请先为每个 Note 完成唯一主归属 SVT 的拆分，再生成场镜")
    if any(s.get("breakdown_status") == "needs_review" and set(s["note_ids"]) & set(note_ids) for s in live_svts):
        raise ValueError("主归属 SVT 已调整，请先选中该 SVT 的来源 Notes 重新提炼，核对梗概和爆点后再生成场镜")
    await asyncio.to_thread(understanding.require_understood, path, note_ids)
    project = await asyncio.to_thread(load_json, path / "project.json")
    if project.get("content_mode") != "drama" or project.get("generation_mode") == "reference_video":
        raise ValueError("场镜素材库目前适用于剧情演绎的分镜制作模式")
    if durations is None:
        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        capabilities = await ConfigResolver(async_session_factory).video_capabilities_for_project(project)
        durations = [d for d in capabilities["supported_durations"] if d <= 15]
    if not durations:
        raise ValueError("请配置支持15秒以内片段的视频模型")
    rules = await asyncio.to_thread(store.rule, path, "scenes")
    chunks_by_note = {n["id"]: await asyncio.to_thread(chapters.chunks, path, project, n) for n in notes}
    total = sum(len(v) for v in chunks_by_note.values())
    progress = {"phase": "scenes", "done": 0, "total": total}
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
    completed = 0
    try:
        for note in notes:
            reading = readings[note["id"]]
            known = await asyncio.to_thread(understanding.production_context, path, [note["id"]])
            tags = await asyncio.to_thread(svt_event_tags, path, note["id"], reading)
            chunks = chunks_by_note[note["id"]]
            assets = []
            for asset in reading["assets"]:
                if asset.get("source_kind") == "annotation" or asset.get("claim_type") in {
                    "inference",
                    "statement",
                    "adaptation",
                }:
                    continue
                ref = reference(project, asset)
                if ref.get("asset_missing"):
                    raise ValueError("原文关联资产已删除，请先处理资产引用")
                name = ref.get("asset_name", asset["name"])
                assets.append(
                    {
                        "name": name,
                        "raw_name": asset["name"],
                        "kind": asset["kind"],
                        "variant": asset.get("variant"),
                        "evidence": asset["evidence"],
                    }
                )
            for part, chunk in enumerate(chunks):
                check_stop()
                seed = [note["id"], part, reading["basis"], rules, known["basis"], durations, tags]
                key = digest(seed)
                slot = f"{note['id']}:{part}"
                existing = (await asyncio.to_thread(catalog, path))["batches"].get(slot)
                if existing and existing["basis"] == key:
                    completed += 1
                    continue
                # Keep each request bounded: only assets grounded in this fragment and already-revealed context.
                local_assets = [
                    {
                        **a,
                        "variant": a["variant"] if in_chunk(a["evidence"], chunk) else None,
                        "evidence": a["evidence"] if in_chunk(a["evidence"], chunk) else None,
                    }
                    for a in assets
                    if asset_available(a, chunk)
                ]
                local_names = {
                    kind: {a["name"] for a in local_assets if a["kind"] == kind}
                    for kind in ("character", "scene", "prop")
                }
                payload = {
                    "note_title": note["title"],
                    "original": chunk["text"],
                    "assets": local_assets,
                    "known": known["links"],
                    "duration_options": durations,
                    "mainline_links": [
                        {
                            "svt_id": tag["svt_id"],
                            "event_ids": [
                                i
                                for i in tag["event_ids"]
                                if any(e["id"] == i and in_chunk(e["evidence"], chunk) for e in reading["events"])
                            ],
                        }
                        for tag in tags
                    ],
                    "events": [e for e in reading["events"] if in_chunk(e["evidence"], chunk)],
                    "highlights": [e for e in reading.get("highlights", []) if in_chunk(e["evidence"], chunk)],
                }
                draft_file = store.root(path) / "scene_drafts" / f"{key}.json"
                if await asyncio.to_thread(draft_file.exists):
                    result = await asyncio.to_thread(load_json, draft_file)
                else:
                    result = await ask(
                        path,
                        generator,
                        SceneBatch,
                        rules + "\n当前原文与事实：" + json.dumps(payload, ensure_ascii=False),
                        lambda value, chunk=chunk, local_names=local_names: ground(
                            value, chunk, local_names, durations
                        ),
                        grow_output=True,
                        max_output_tokens=24000,
                    )
                    await run_noninterruptible_sync(store.write, draft_file, result)
                from lib.novel_workflow.scene_review import review

                review_file = store.root(path) / "scene_reviews" / f"{key}.json"
                if await asyncio.to_thread(review_file.exists):
                    semantic_review = await asyncio.to_thread(load_json, review_file)
                else:
                    semantic_review = (
                        await review(path, generator, result["scenes"], chunk["text"])
                        if result["scenes"]
                        else {"revisions": [], "unresolved": []}
                    )
                    await run_noninterruptible_sync(store.write, review_file, semantic_review)
                scenes = []
                for scene in result["scenes"]:
                    for shot in scene["shots"]:
                        offset = chunk["text"].index(shot["quote"])
                        shot["evidence"] = {
                            "note_id": note["id"],
                            "source_file": chunk["source_file"],
                            "start": chunk["start"] + offset,
                            "end": chunk["start"] + offset + len(shot["quote"]),
                            "quote": shot["quote"],
                        }
                    scenes.append(scene)
                batch = {
                    "basis": key,
                    "note_id": note["id"],
                    "note_order": note["order"],
                    "part": part,
                    "note_bases": {note["id"]: reading["basis"]},
                    "source_basis": expected,
                    "rule_basis": digest(rules),
                    "understanding_basis": known["basis"],
                    "svt_basis": digest(tags),
                    "scenes": scenes,
                    "review": semantic_review,
                    "skipped_reason": result["skipped_reason"],
                    "created_at": now(),
                }

                def commit(batch=batch, slot=slot):
                    with project_metadata_lock(path):
                        fresh_book = current(path, expected)
                        fresh = store.valid_readings(path, fresh_book)
                        if not valid_batch(path, batch, fresh_book, fresh):
                            raise ValueError("生成期间原文或理解依据发生变化，请重新生成")
                        library = catalog(path)
                        for scene in batch["scenes"]:
                            library["scene_counter"] = library.get("scene_counter", 0) + 1
                            scene["id"] = f"SCN-{library['scene_counter']:04}"
                            for shot in scene["shots"]:
                                library["shot_counter"] = library.get("shot_counter", 0) + 1
                                shot["id"] = f"SH-{library['shot_counter']:04}"
                        if old := library["batches"].get(slot):
                            store.write(store.root(path) / "history" / f"scene-{uuid4().hex}.json", old)
                        library["batches"][slot] = batch
                        store.write(store.root(path) / "scene_library.json", library)

                await run_noninterruptible_sync(commit)
                completed += 1
                await run_noninterruptible_sync(
                    store.write,
                    store.root(path) / "progress.json",
                    {
                        "phase": "scenes",
                        "done": completed,
                        "total": total,
                        "note_id": note["id"],
                    },
                )
    except BaseException as exc:
        await run_noninterruptible_sync(
            store.write,
            store.root(path) / "progress.json",
            {"phase": "scenes", "done": completed, "total": total, "error": str(exc)},
        )
        raise
    await run_noninterruptible_sync(
        store.write, store.root(path) / "progress.json", {"phase": "idle", "done": completed, "total": total}
    )
    return {"batches": completed}


def require_attributed(shot):
    for segment in shot["segments"]:
        for utterance in segment["utterances"]:
            if utterance["kind"] == "dialogue" and not (utterance.get("speaker") or "").strip():
                raise ValueError(
                    f"{shot['id']} 有对白尚未确认说话人：{utterance['text'][:60]}。请在场镜素材库确认后再组集。"
                )


def attribute_dialogue(path, project, shot_id, segment_index, utterance_index, speaker, expected, shot_basis):
    """Human attribution is local, versioned and guarded against stale edits."""
    with project_metadata_lock(path):
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
                    if speaker not in project.get("characters", {}):
                        raise ValueError("请选择项目中已登记的人物资产；未明确身份可建立无名角色资产")
                    store.write(store.root(path) / "history" / f"scene-attribution-{uuid4().hex}.json", batch)
                    utterance["speaker"] = speaker
                    if speaker not in segment["characters_in_scene"]:
                        segment["characters_in_scene"].append(speaker)
                    shot.setdefault("attribution_history", []).append(
                        {
                            "segment": segment_index,
                            "utterance": utterance_index,
                            "speaker": speaker,
                            "confirmed_by": "human",
                            "created_at": now(),
                        }
                    )
                    store.write(store.root(path) / "scene_library.json", library)
                    return {"shot_id": shot_id}
        raise ValueError("镜头不存在")
