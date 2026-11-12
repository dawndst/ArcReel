"""Version-bound director decisions and reviewable production handoff packages."""

import hashlib
import io
import json
import zipfile
from copy import deepcopy

from pydantic import ConfigDict, Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import execution, store
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_library import selected_shots

CHECK_VERSION = 1


class DirectorDecision(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    basis: str
    reviewer: str = Field(min_length=1, max_length=100)
    story_intent: str = Field(min_length=10, max_length=3000)
    withheld: str = Field(min_length=1, max_length=2000)
    story_checked: bool
    timing_checked: bool
    continuity_checked: bool
    decisions: dict[str, str] = Field(default_factory=dict)


def _file(path, relative):
    if not relative or not isinstance(relative, str):
        return None
    target = (path / relative).resolve()
    if not target.is_relative_to(path.resolve()) or not target.is_file():
        return None
    return target


def _image(path, item):
    relative = next((item.get(k) for k in ("character_sheet", "scene_image", "prop_image") if item.get(k)), None)
    file = _file(path, relative)
    if not file:
        return {"image": None, "image_hash": None}
    if file.stat().st_size > 30 * 1024 * 1024:
        return {"image": relative, "image_hash": None, "image_error": "图片超过30MB，需缩小后交付"}
    return {"image": relative, "image_hash": hashlib.sha256(file.read_bytes()).hexdigest()}


def preview(path, project, shot_ids, title, expected):
    book = store.require_current(path, project, expected)
    readings = store.valid_readings(path, book)
    selected = selected_shots(path, book, readings, shot_ids)
    issues, shots, used = [], [], {}
    seen_batches = set()
    for batch, scene, shot in selected:
        from lib.novel_workflow.shot_production import effective_segment

        shot = deepcopy(shot)
        shot["segments"] = [effective_segment(seg, shot.get("production"), i) for i, seg in enumerate(shot["segments"])]
        checks = execution.inspect(shot, project)
        if batch.get("production_stale"):
            checks.append(
                {
                    "id": digest([shot["id"], "design_stale"])[:24],
                    "code": "design_stale",
                    "hard": True,
                    "shot_id": shot["id"],
                    "segment": None,
                    "details": {},
                }
            )
        issues.extend(checks)
        shots.append(
            {
                "id": shot["id"],
                "scene_id": scene["id"],
                "scene": {k: scene.get(k, "") for k in ("id", "title", "location", "time", "purpose")},
                "story_links": {
                    "svt_id": shot.get("production", {}).get("svt_id"),
                    "events": [
                        e
                        for e in batch.get("production_context", {}).get("events", [])
                        if e["id"] in shot.get("production", {}).get("event_ids", [])
                    ],
                    "moments": [
                        m
                        for m in batch.get("production_context", {}).get("moments", [])
                        if m["id"] in shot.get("production", {}).get("moment_ids", [])
                    ],
                },
                "title": shot["title"],
                "purpose": shot.get("production", {}).get("design", {}).get("purpose", ""),
                "segments": shot["segments"],
                "design": shot.get("production", {}).get("design", {}),
                "source": shot["evidence"],
            }
        )
        for seg in shot["segments"]:
            for field, kind in (("characters_in_scene", "character"), ("scenes", "scene"), ("props", "prop")):
                for name in seg.get(field, []):
                    used.setdefault((kind, name), {"visible": True, "voice": False})["visible"] = True
            for line in seg["utterances"]:
                if line.get("speaker"):
                    used.setdefault(("character", line["speaker"]), {"visible": False, "voice": False})["voice"] = True
        if batch["basis"] not in seen_batches and batch.get("review", {}).get("unresolved"):
            seen_batches.add(batch["basis"])
            questions = batch["review"]["unresolved"]
            issues.append(
                {
                    "id": digest([batch["basis"], questions])[:24],
                    "code": "source_question",
                    "hard": False,
                    "shot_id": shot["id"],
                    "segment": None,
                    "details": {"questions": questions},
                }
            )
        pending = [
            r
            for r in batch.get("review", {}).get("revisions", [])
            if not r.get("applied")
            and not r.get("superseded")
            and batch["scenes"][r["scene_index"]]["shots"][r["shot_index"]]["id"] == shot["id"]
        ]
        if pending:
            issues.append(
                {
                    "id": digest([shot["id"], pending])[:24],
                    "code": "source_review",
                    "hard": False,
                    "shot_id": shot["id"],
                    "segment": None,
                    "details": {"reasons": [r["reason"] for r in pending]},
                }
            )
    assets = []
    for (kind, name), use in used.items():
        item = execution.asset(project, kind, name)
        assets.append(
            {
                "kind": kind,
                "name": name,
                "asset_id": item.get("asset_id"),
                "asset_code": item.get("asset_code"),
                "description": item.get("description", ""),
                "voice_style": item.get("voice_style")
                or execution.asset(project, kind, name.split("/", 1)[0]).get("voice_style", ""),
                **use,
                **_image(path, item),
            }
        )
    basis = digest(
        [
            CHECK_VERSION,
            expected,
            title.strip(),
            [execution.content_basis(s) for _, _, s in selected],
            [{k: v for k, v in a.items() if k not in {"image", "image_hash"}} for a in assets],
            store.rule(path, "shot_execution"),
            store.rule(path, "selection_story"),
        ]
    )
    file = store.root(path) / "delivery_reviews" / f"{basis}.json"
    decision = load_json(file) if file.exists() else None
    ai_file = store.root(path) / "selection_reviews" / f"{basis}.json"
    ai_review = load_json(ai_file) if ai_file.exists() else None
    approved = bool(decision and decision.get("advice_basis") == digest(ai_review))
    return {
        "basis": basis,
        "title": title.strip(),
        "shot_ids": shot_ids,
        "shots": shots,
        "assets": assets,
        "issues": issues,
        "seconds": sum(s["duration_seconds"] for sh in shots for s in sh["segments"]),
        "aspect_ratio": project.get("aspect_ratio", "16:9"),
        "approved": approved,
        "decision": decision,
        "ai_review": ai_review,
        "note_ids": list(dict.fromkeys(b["note_id"] for b, _, _ in selected)),
    }


def approve(path, shot_ids, title, expected, decision, *, actor_id=None):
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        current = preview(path, project, shot_ids, title, expected)
        if decision.basis != current["basis"]:
            raise ValueError("镜头、排序、资产或规则已变化，请重新预览并确认")
        if any(i["hard"] for i in current["issues"]):
            raise ValueError("请先修复结构、对白归属和引用错误，人工确认不能跳过这些错误")
        if not (decision.story_checked and decision.timing_checked and decision.continuity_checked):
            raise ValueError("编导须确认故事、节奏和连续性")
        codes = {i["code"] for i in current["issues"] if not i["hard"]}
        codes.update("story:" + i["kind"] for i in (current.get("ai_review") or {}).get("findings", []))
        if any(len(decision.decisions.get(code, "").strip()) < 10 for code in codes):
            raise ValueError("每类待判断提示须记录具体处理依据，至少10字")
        payload = {
            **decision.model_dump(),
            "title": title.strip(),
            "shot_ids": shot_ids,
            "source_basis": expected,
            "confirmed_at": now(),
            "advice_basis": digest(current.get("ai_review")),
            "actor_id": actor_id,
        }
        store.write(store.root(path) / "delivery_reviews" / f"{current['basis']}.json", payload)
        return payload


def list_plans(path):
    folder = store.root(path) / "delivery_reviews"
    return [
        {
            "basis": p.stem,
            "title": d["title"],
            "shot_ids": d["shot_ids"],
            "source_basis": d["source_basis"],
            "confirmed_at": d["confirmed_at"],
        }
        for p in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
        if (d := load_json(p))
    ]


def asset_approval(path, shot_ids, title, expected, basis, asset_id, image_hash, reviewer, *, actor_id=None):
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        current = preview(path, project, shot_ids, title, expected)
        if current["basis"] != basis or not current["approved"]:
            raise ValueError("请先确认当前版本的文字分镜方案")
        item = next((a for a in current["assets"] if a["asset_id"] == asset_id), None)
        if not item or not item["visible"] or not item.get("image_hash") or item["image_hash"] != image_hash:
            raise ValueError("参考图不存在或已更换，请重新查看后确认")
        file = store.root(path) / "delivery_asset_reviews" / f"{basis}.json"
        data = load_json(file) if file.exists() else {}
        data[asset_id] = {"image_hash": image_hash, "reviewer": reviewer, "at": now(), "actor_id": actor_id}
        store.write(file, data)
        return data


def director_notes(review, shot_id, segment_index):
    decision = review.get("decision") or {}
    notes = list(
        dict.fromkeys(
            decision.get("decisions", {}).get(i["code"], "")
            for i in review["issues"]
            if i["shot_id"] == shot_id and i.get("segment") in (None, segment_index)
        )
    )
    notes = [n for n in notes if n]
    return "\n".join(notes)


def handoff(path, project, shot_ids, title, expected):
    from lib.speech.delivery import DELIVERY_DIRECTIONS

    current = preview(path, project, shot_ids, title, expected)
    file = store.root(path) / "delivery_asset_reviews" / f"{current['basis']}.json"
    approvals = load_json(file) if file.exists() else {}
    missing = []
    for item in current["assets"]:
        item["image_approved"] = bool(
            item.get("image_hash") and approvals.get(item["asset_id"], {}).get("image_hash") == item["image_hash"]
        )
        if item["visible"] and not item["image_approved"]:
            missing.append({"code": "reference_image", "asset_id": item["asset_id"], "name": item["name"]})
        if item["voice"] and not item["voice_style"].strip():
            missing.append({"code": "voice_style", "asset_id": item["asset_id"], "name": item["name"]})
    episode = next(
        (
            e
            for e in project.get("episodes", [])
            if not e.get("director_selection", {}).get("pending")
            and e.get("director_selection", {}).get(
                "selection_basis", e.get("director_selection", {}).get("delivery_basis")
            )
            == current["basis"]
        ),
        None,
    )
    current["episode"] = episode["episode"] if episode else None
    if episode:
        from lib.episode.episode_paths import SCRIPT_PLAN_FILENAMES, episode_drafts_dir

        plan_file = episode_drafts_dir(path, episode["episode"]) / SCRIPT_PLAN_FILENAMES["drama"]
        if not plan_file.exists() or digest(load_json(plan_file)) != episode["director_selection"].get(
            "published_content_basis"
        ):
            missing.append({"code": "formal_plan_changed", "asset_id": None, "name": title})
    prefix = f"EP{episode['episode']:02d}" if episode else "EP待组集"
    scene_number, shot_number, previous_scene = 0, 0, None
    for shot in current["shots"]:
        if shot["scene_id"] != previous_scene:
            scene_number += 1
            shot_number = 0
            previous_scene = shot["scene_id"]
        shot_number += 1
        shot["display_id"] = f"{prefix}-SC{scene_number:02d}-SH{shot_number:03d}"
        for i, segment in enumerate(shot["segments"], 1):
            human_notes = director_notes(current, shot["id"], i - 1)
            spoken = "\n".join(
                f"{u.get('speaker') or '叙述旁白'}：{u['text']} [{DELIVERY_DIRECTIONS.get(u.get('delivery'), '发声方式待确认')}]"
                for u in segment["utterances"]
            )
            reference_names = [
                name for key in ("characters_in_scene", "scenes", "props") for name in segment.get(key, [])
            ]
            references = "\n".join(
                f"{a['asset_code']} {a['name']}：{a['description']}"
                for a in current["assets"]
                if a["visible"] and a["name"] in reference_names
            )
            voices = "\n".join(
                f"{a['name']}：{a['voice_style']}"
                for a in current["assets"]
                if a["voice"] and any(u.get("speaker") == a["name"] for u in segment["utterances"])
            )
            states = "\n".join(
                f"{s['name']}（{s['visibility']}）：{s.get('start', '')} → {s.get('end', '')}；{s.get('attachment', '')}"
                for s in segment.get("asset_states", [])
            )
            segment["canvas_prompt"] = (
                f"画幅：{current['aspect_ratio']}；模型原生配音；使用供应商最低可用画质；参考时长{segment['duration_seconds']}秒（实际生成与剪辑时长可调整）。\n仅导入以下出镜参考：{references}\n发声角色声音设定：{voices}\n编导处理：{human_notes}\n画面：{segment['scene_description']}\n起始：{segment.get('start_frame', '')}\n结束：{segment.get('end_frame', '')}\n状态约束：{states}\n镜头设计：{json.dumps(shot['design'], ensure_ascii=False)}\n有序发声（逐句保留，不添加字幕或额外台词）：\n{spoken}"
            )
            segment["delivery_id"] = shot["display_id"] + (f"-SEG{i}" if len(shot["segments"]) > 1 else "")
    if not episode:
        missing.append({"code": "assembly", "asset_id": None, "name": title})
    current.update(
        missing_materials=missing,
        ready=current["approved"] and not missing and not any(i["hard"] for i in current["issues"]),
    )
    return current


def export(path, project, shot_ids, title, expected, *, final=False):
    current = handoff(path, project, shot_ids, title, expected)
    if final and not current["ready"]:
        raise ValueError("制作包尚未完成当前版本的编导与美术参考确认；可先下载筹备清单")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {**current, "export_status": "approved" if final else "draft"}
        total_bytes = 0
        for item in manifest["assets"]:
            file = _file(path, item.get("image"))
            if file and item.get("image_hash") and item["visible"]:
                target = f"assets/{item['asset_code']}{file.suffix}"
                data = file.read_bytes()
                if hashlib.sha256(data).hexdigest() != item["image_hash"]:
                    raise ValueError("参考图在打包期间已变化，请刷新后重新确认")
                total_bytes += len(data)
                if total_bytes > 150 * 1024 * 1024:
                    raise ValueError("参考资产超过150MB，请分批交付")
                archive.writestr(target, data)
                item["package_image"] = target
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        lines = [
            f"# {title}",
            "已验收制作包" if final else "筹备清单：供核对使用，不作为最终制作指令",
            f"画幅 {current['aspect_ratio']}；累计参考时长 {current['seconds']} 秒，非实际生成时长约束。",
            "声音角色只使用声音设定，非出镜角色不导入图片。每个SEG按序使用起止状态与参考图，不自动补写台词。",
            "## 待补资料",
        ]
        lines.extend(f"- {m['name']}：{m['code']}" for m in current["missing_materials"])
        for shot in current["shots"]:
            lines.append(f"\n## {shot['display_id']} {shot['title']}")
            lines.append(
                f"场景：{shot['scene']['location']} · {shot['scene']['time']}\n叙事目的：{shot['scene']['purpose']}"
            )
            links = shot["story_links"]
            lines.append("主线事件：" + (links["svt_id"] or "待编导补充"))
            lines.extend("事件："
                    + event.get("title", "")
                    + "\n"
                    + "；".join(event.get(k, "") for k in ("cause", "conflict", "action", "outcome")) for event in links["events"])
            for moment in links["moments"]:
                lines.append("爆点场面：" + moment["scene"])
                lines.extend(
                    "关键对白：" + (d.get("speaker") or "待确认") + "：" + d["quote"]
                    for d in moment.get("dialogues", [])
                )
            lines.append("原文依据：" + shot["source"]["quote"])
            lines.extend(f"\n### {seg['delivery_id']}\n{seg['canvas_prompt']}" for seg in shot["segments"])
        archive.writestr("制作清单.md", "\n".join(lines))
        archive.writestr("编导确认.json", json.dumps(current.get("decision"), ensure_ascii=False, indent=2))
    return buffer.getvalue()
