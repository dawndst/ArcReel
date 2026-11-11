"""Director-selected, ordered logical shots become a native episode content plan."""

from __future__ import annotations

from lib.episode.episode_paths import SCRIPT_PLAN_FILENAMES, episode_drafts_dir
from lib.episode.episode_source_commands import add_own_source_episode
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import scene_library, store, understanding
from lib.script.script_models import DramaNormalizedScript
from lib.script.script_review import formal_script_plan_lock, write_formal_script_plan_locked


def content_from_selection(selected, episode, title):
    from lib.novel_workflow.scene_library import require_attributed

    for _batch, _scene, shot in selected:
        require_attributed(shot)
    rows, mapping = [], []
    last_scene, scene_number, shot_number = None, 0, 0
    for _batch, scene, shot in selected:
        if scene["id"] != last_scene:
            scene_number += 1
            shot_number = 0
            last_scene = scene["id"]
        shot_number += 1
        for index, segment in enumerate(shot["segments"], 1):
            row_id = f"E{episode}S{len(rows) + 1:03}"
            rows.append(
                {
                    **segment,
                    "scene_id": row_id,
                    "scene_number": scene_number,
                    "shot_number": shot_number,
                    "segment_number": index if len(shot["segments"]) > 1 else None,
                    "segment_break": shot_number == 1 and index == 1,
                    "source_text": shot["evidence"]["quote"],
                }
            )
            mapping.append(
                {
                    "scene_id": row_id,
                    "library_scene_id": scene["id"],
                    "library_shot_id": shot["id"],
                    "evidence": shot["evidence"],
                }
            )
    return DramaNormalizedScript.model_validate({"title": title, "scenes": rows}).model_dump(), mapping


def assemble(manager, name, shot_ids, title, expected, request_id):
    path = manager.get_project_path(name)
    # Serializes retries of the same request and source registration + native plan publication.
    lock = store.root(path) / ".director.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    signature = digest([shot_ids, title, expected])
    with manager.file_lock(lock):
        project = manager.load_project(name)
        if project.get("content_mode") != "drama" or project.get("generation_mode") == "reference_video":
            raise ValueError("当前项目不支持场镜编排模式")
        notebook = store.require_current(path, project, expected)
        readings = store.valid_readings(path, notebook)
        selected = scene_library.selected_shots(path, notebook, readings, shot_ids)
        for _batch, _scene, shot in selected:
            scene_library.require_attributed(shot)
            from lib.novel_workflow.scene_review import require_reviewed

            require_reviewed(_batch, shot)
        if len(shot_ids) > 300:
            raise ValueError("单集最多编排300个镜头")
        existing = next(
            (e for e in project["episodes"] if e.get("director_selection", {}).get("request_id") == request_id), None
        )
        if existing and existing["director_selection"]["signature"] != signature:
            raise ValueError("本次编排已提交不同内容，请刷新后新建编排")
        if existing and not existing["director_selection"].get("pending"):
            return existing["episode"]
        note_ids = list(dict.fromkeys(b["note_id"] for b, _, _ in selected))
        understanding.require_understood(path, note_ids)
        known = understanding.production_context(path, note_ids)
        # Only chosen shots contribute the episode source. Unselected Note passages cannot re-enter planning.
        text = "\n\n".join(dict.fromkeys(shot["evidence"]["quote"] for _, _, shot in selected))
        title = title.strip()
        if not title:
            raise ValueError("请填写本集标题")
        if len(text) > 60000:
            raise ValueError("所选镜头原文超过单集上下文预算，请减少镜头")
        if existing:
            episode = existing["episode"]
        else:
            with manager.locked_source_registration(name) as (_, current, undo):
                fresh_book = store.require_current(path, current, expected)
                fresh_selection = scene_library.selected_shots(
                    path, fresh_book, store.valid_readings(path, fresh_book), shot_ids
                )
                if digest(fresh_selection) != digest(selected):
                    raise ValueError("场镜在编排期间发生变化，请刷新后重试")
                episode = add_own_source_episode(path, current, text, undo=undo, title=title, source_kind="novel")
                entry = current["episodes"][-1]
                content, mapping = content_from_selection(selected, episode, title)
                entry["director_selection"] = {
                    "request_id": request_id,
                    "signature": signature,
                    "pending": True,
                    "shot_ids": shot_ids,
                    "mapping": mapping,
                    "shot_bases": {s["id"]: digest(s) for _, _, s in selected},
                }
                entry["note_source"] = {
                    "source_basis": expected,
                    "note_bases": {i: readings[i]["basis"] for i in note_ids},
                    "understanding_basis": known["basis"],
                    "text_basis": digest(text),
                }
        content, mapping = content_from_selection(selected, episode, title)
        plan_path = episode_drafts_dir(path, episode) / SCRIPT_PLAN_FILENAMES["drama"]
        # Native publication keeps review, prompt authoring and artifact tracking on the standard path.
        # A failed publication leaves an explicit pending assembly; the same request resumes, never duplicates.
        with formal_script_plan_lock(path, episode, plan_path):
            if not plan_path.exists():
                write_formal_script_plan_locked(path, episode, plan_path, content, expected_fingerprint=None)
            elif load_json(plan_path) != content:
                raise ValueError("本集内容已被编辑，不覆盖；请在集内检查已有编排")

        def complete(current):
            entry = next(e for e in current["episodes"] if e["episode"] == episode)
            entry["director_selection"]["pending"] = False

        manager.update_project(name, complete)
        return episode
