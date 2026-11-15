"""Edition-first scene manifests, independent units, reference compilation and scoped review."""

import asyncio
from copy import deepcopy

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_workflow import scene_material, store, understanding
from lib.novel_workflow.cancellation import check_stop
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.scene_contracts import ScenePlan, SceneShots, compile_shots, validate_plan
from lib.novel_workflow.scene_source import snapshot
from lib.novel_workflow.stage_runner import REPAIR_LIMIT, run
from lib.novel_workflow.storage import load_json


def cache_material(value):
    """Derived availability hints do not change the underlying narrative candidate."""
    value = deepcopy(value)
    for event in value.get("events", []):
        event.pop("available_asset_ids", None)
    for line in value.get("dialogues", []):
        line.pop("speaker_asset_ids", None)
    return value


def dependencies(path, catalogue):
    return {
        "material": catalogue.basis,
        "fidelity_rule": digest(store.effective_rule(path, "fidelity")),
        "constraints": catalogue.reading.get("conclusion_basis"),
        "outline_rule": digest(store.effective_rule(path, "scene_outline")),
        "shot_rule": digest(store.effective_rule(path, "scene_shots")),
        "inspection_rule": digest(store.effective_rule(path, "scene_inspection")),
        "patch_rule": digest(store.effective_rule(path, "scene_patch")),
    }


def manifests(path):
    from lib.novel_workflow.scene_library import catalog

    return catalog(path).get("plans", {})


def status(path, notebook, readings):
    """Only a current manifest can mark a whole chapter complete."""
    from lib.novel_workflow.scene_library import catalog

    library = catalog(path)
    result = {}
    for note in notebook["notes"]:
        plan = library.get("plans", {}).get(note["id"])
        legacy = [
            b for b in library["batches"].values() if b["note_id"] == note["id"] and b.get("pipeline_version") != 2
        ]
        if not plan:
            if legacy:
                result[note["id"]] = {
                    "status": "partial",
                    "completed": 0,
                    "total": None,
                    "retained_drafts": len(legacy),
                    "units": [],
                }
            continue
        try:
            current = dependencies(path, scene_material.load(path, note, readings.get(note["id"])))
            fresh = current == plan["dependencies"]
        except (ValueError, FileNotFoundError, KeyError):
            fresh = False
        units = plan["units"]
        completed = sum(u["status"] == "ready" for u in units)
        result[note["id"]] = {
            "status": "stale" if not fresh else "complete" if completed == len(units) else "partial",
            "completed": completed,
            "total": len(units),
            "retained_drafts": len(legacy),
            "units": [{k: u.get(k) for k in ("id", "title", "status", "error", "stage")} for u in units],
            "repair_limit": REPAIR_LIMIT,
        }
    return result


def update_unit(path, note_id, plan_basis, unit_id, **values):
    from lib.novel_workflow.scene_library import catalog

    with project_metadata_lock(path):
        library = catalog(path)
        plan = library["plans"][note_id]
        if plan["basis"] != plan_basis:
            raise ValueError("场面规划已变化，不覆盖其他版本")
        unit = next(u for u in plan["units"] if u["id"] == unit_id)
        unit.update(**values, updated_at=now())
        store.write(store.root(path) / "scene_library.json", library)


async def ensure_plan(path, generator, catalogue):
    from lib.novel_workflow.scene_library import catalog

    deps = await asyncio.to_thread(dependencies, path, catalogue)
    previous = (await asyncio.to_thread(catalog, path)).get("plans", {}).get(catalogue.note["id"])
    outline_basis = digest([catalogue.basis, deps["outline_rule"], deps["fidelity_rule"]])
    if previous and all(
        previous["dependencies"].get(k, deps[k]) == deps[k] for k in ("material", "outline_rule", "fidelity_rule")
    ):
        outline_basis = previous["outline_basis"]
    if previous and previous.get("outline_basis") == outline_basis:
        if previous["dependencies"] == deps and not any(u["status"] == "skipped" for u in previous["units"]):
            return previous
        # A review/shot rule update keeps the chapter scene plan and stable SCN IDs.
        plan = deepcopy(previous)
        plan.update(dependencies=deps, basis=digest([outline_basis, deps]))
        for u in plan["units"]:
            u.update(status="pending", stage="update", error=None)
    else:
        rule = await asyncio.to_thread(store.effective_rule, path, "scene_outline")
        material = await asyncio.to_thread(catalogue.material)
        value = await run(
            path,
            generator,
            ScenePlan,
            rule,
            material,
            digest(["outline", outline_basis]),
            lambda v: validate_plan(v, catalogue),
            source_lookup=catalogue.lookup,
            output_limit=8000,
        )
        plan = {
            "basis": digest([outline_basis, deps]),
            "outline_basis": outline_basis,
            "dependencies": deps,
            "note_id": catalogue.note["id"],
            "units": value["scenes"],
            "created_at": now(),
        }

    def commit():
        with project_metadata_lock(path):
            if dependencies(path, scene_material.load(path, catalogue.note)) != deps:
                raise ValueError("规划期间上游材料已变化，已保存模型结果")
            library = catalog(path)
            for i, u in enumerate(plan["units"]):
                if not u.get("id"):
                    library["scene_counter"] = library.get("scene_counter", 0) + 1
                    u["id"] = f"SCN-{library['scene_counter']:04}"
                    u.update(status="pending", stage="planned", error=None)
                u["order"] = i
            library.setdefault("plans", {})[catalogue.note["id"]] = plan
            store.write(store.root(path) / "scene_library.json", library)
        return plan

    return await run_noninterruptible_sync(commit)


async def generate(path, generator, note_ids, expected, *, durations=None):
    from lib.novel_workflow import conclusions, scope

    notebook = await asyncio.to_thread(
        store.require_current, path, await asyncio.to_thread(load_json, path / "project.json"), expected
    )
    await asyncio.to_thread(scope.require, path, notebook, note_ids)
    if any(g.get("usage") == "reference" and set(g["note_ids"]) & set(note_ids) for g in notebook["groups"]):
        raise ValueError("所选 Note 属于仅留档资料组，请先调整用途后再生成场镜")
    await asyncio.to_thread(understanding.require_understood, path, note_ids)
    # Exact speech is retained; disputed world-rule interpretations stay review issues,
    # while unresolved identity/causal problems still require an upstream decision.
    await asyncio.to_thread(conclusions.require_ready, path, note_ids, stage="svt")
    notes = [n for n in notebook["notes"] if n["id"] in set(note_ids)]
    if len(notes) != len(set(note_ids)) or not notes:
        raise ValueError("请选择当前可用的章节")
    project = await asyncio.to_thread(load_json, path / "project.json")
    if project.get("content_mode") != "drama" or project.get("generation_mode") == "reference_video":
        raise ValueError("当前项目不支持剧情场镜规划")
    progress = {"phase": "scene_planning", "done": 0, "total": None, "repair_limit": REPAIR_LIMIT}
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
    completed = 0
    total = 0
    errors = []
    try:
        for note in notes:
            progress.update(phase="scene_planning", done=0, total=None, note_id=note["id"], unit_title=None)
            await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
            catalogue = await asyncio.to_thread(scene_material.load, path, note)
            plan = await ensure_plan(path, generator, catalogue)
            total += len(plan["units"])
            note_errors = len(errors)
            for unit in plan["units"]:
                check_stop()
                progress.update(
                    phase="scene_shots",
                    done=sum(
                        u["status"] == "ready" for u in (await asyncio.to_thread(manifests, path))[note["id"]]["units"]
                    ),
                    total=len(plan["units"]),
                    note_id=note["id"],
                    unit_id=unit["id"],
                    unit_title=unit["title"],
                )
                await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
                if unit["status"] == "ready":
                    completed += 1
                    continue
                try:
                    await generate_unit(path, generator, catalogue, plan, unit, project)
                    completed += 1
                except Exception as exc:
                    errors.append(f"{unit['title']}：{exc}")
                    await run_noninterruptible_sync(
                        update_unit, path, note["id"], plan["basis"], unit["id"], status="failed", error=str(exc)[:1600]
                    )
                    # A failed local field never discards other scenes. Continue other units;
                    # service/provider failures stop paid work instead of multiplying requests.
                    from lib.novel_workflow.stage_runner import StageRepairRequired

                    if not isinstance(exc, StageRepairRequired):
                        raise
            if len(errors) == note_errors:
                await run_noninterruptible_sync(retire_drafts, path, note["id"], plan["basis"])
        if errors:
            from lib.novel_workflow.stage_runner import StageRepairRequired

            raise StageRepairRequired("已保留成功场面；以下单元可继续局部修订：" + "；".join(errors)[:1500])
    except BaseException as exc:
        progress.update(phase="failed", done=completed, total=total or None, error=str(exc))
        await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
        raise
    from lib.novel_workflow.scene_bindings import refresh as refresh_bindings

    await run_noninterruptible_sync(refresh_bindings, path)
    progress.update(phase="complete", done=completed, total=total)
    await run_noninterruptible_sync(store.write, store.root(path) / "progress.json", progress)
    return {"scenes": completed}


async def generate_unit(path, generator, catalogue, plan, unit, project):
    from lib.novel_workflow.scene_library import catalog

    note_id = catalogue.note["id"]
    slot = f"{note_id}:scene:{unit['id']}"
    rule = await asyncio.to_thread(store.effective_rule, path, "scene_shots")
    material = await asyncio.to_thread(catalogue.material, unit["event_ids"])
    material["scene"] = {
        k: unit[k] for k in ("id", "title", "location", "time", "purpose", "event_ids", "primary_event_ids")
    }
    prior = (await asyncio.to_thread(catalog, path))["batches"]
    previous = [
        b
        for b in prior.values()
        if b.get("pipeline_version") == 2
        and b["note_id"] == note_id
        and b["part"] < unit["order"]
        and b.get("plan_basis") == plan["outline_basis"]
    ]
    if previous:
        last = max(previous, key=lambda b: b["part"])["scenes"][-1]["shots"][-1]
        material["previous_scene_end"] = last["segments"][-1].get("end_frame", "")
    semantic_basis = digest(
        [
            catalogue.basis,
            plan["outline_basis"],
            rule,
            cache_material({k: v for k, v in material.items() if k != "previous_scene_end"}),
        ]
    )
    if unit.get("candidate_semantic_basis") == semantic_basis:
        if unit.get("candidate_previous_end") is None:
            material.pop("previous_scene_end", None)
        else:
            material["previous_scene_end"] = unit["candidate_previous_end"]
    draft_basis = digest(["shots", catalogue.basis, plan["outline_basis"], cache_material(material), rule])
    existing = prior.get(slot)
    reusable = bool(
        existing
        and existing.get("plan_basis") == plan["outline_basis"]
        and all(
            existing.get("dependencies", {}).get(k) == plan["dependencies"].get(k)
            for k in ("material", "outline_rule", "shot_rule")
        )
    )
    if reusable:
        context = await asyncio.to_thread(
            understanding.production_context, path, [note_id], source_offset=existing.get("source_start")
        )
        reusable = (
            existing.get("understanding_basis") == context["basis"]
            and existing.get("dependencies", {}).get("constraints", plan["dependencies"]["constraints"])
            == plan["dependencies"]["constraints"]
        )
    await run_noninterruptible_sync(
        update_unit,
        path,
        note_id,
        plan["basis"],
        unit["id"],
        stage="drafting",
        status="running",
        error=None,
        candidate_semantic_basis=semantic_basis,
        candidate_previous_end=material.get("previous_scene_end"),
    )
    if reusable:
        batch = existing
    else:
        # Transport windows follow event boundaries inside one stable SCN.
        # Each event's speech has exactly one owning window; supporting context cannot duplicate it.
        value = {"shots": [], "omitted_dialogues": [], "omission_reason": "", "normalizations": []}
        windows, window = [], []
        for event_id in unit["primary_event_ids"]:
            lines = sum(len(catalogue.events[e]["dialogue_ids"]) for e in [*window, event_id])
            if window and (len(window) >= 4 or lines > 60):
                windows.append(window)
                window = []
            window.append(event_id)
        if window:
            windows.append(window)
        for index, event_ids in enumerate(windows):
            pack = await asyncio.to_thread(catalogue.material, event_ids)
            pack["scene"] = material["scene"]
            pack["transport_window"] = {"index": index + 1, "total": len(windows), "primary_event_ids": event_ids}
            if value["shots"]:
                pack["previous_scene_end"] = value["shots"][-1]["segments"][-1]["end_frame"]
            elif "previous_scene_end" in material:
                pack["previous_scene_end"] = material["previous_scene_end"]
            scoped_unit = {
                **unit,
                "event_ids": event_ids,
                "primary_event_ids": event_ids,
                "scene_event_ids": unit["event_ids"],
            }
            part = await run(
                path,
                generator,
                SceneShots,
                rule,
                pack,
                digest([draft_basis, index, cache_material(pack)]),
                lambda v, scoped=scoped_unit: compile_shots(v, catalogue, scoped),
                source_lookup=catalogue.lookup,
            )
            value["shots"].extend(part["shots"])
            value["normalizations"].extend(part.get("normalizations", []))
            value["omitted_dialogues"].extend(part["omitted_dialogues"])
            if part["omission_reason"]:
                value["omission_reason"] += part["omission_reason"] + "\n"
        batch = await asyncio.to_thread(build_batch, path, catalogue, plan, unit, draft_basis, value)
        batch = await run_noninterruptible_sync(commit_draft, path, catalogue, plan, slot, batch)
    from lib.novel_workflow.scene_inspection import basis as inspection_basis
    from lib.novel_workflow.scene_inspection import review, shot_inputs

    review_basis = inspection_basis(batch, plan["dependencies"]["inspection_rule"])
    if batch.get("inspection_basis") != review_basis:
        await run_noninterruptible_sync(update_unit, path, note_id, plan["basis"], unit["id"], stage="reviewing")
        result = await review(path, generator, catalogue, unit, batch)

        def commit_review():
            with project_metadata_lock(path):
                library = catalog(path)
                current = library["batches"].get(slot)
                if current != batch:
                    raise ValueError("复审期间场镜已被编辑，不覆盖当前内容")
                current.update(
                    review=result,
                    dependencies=plan["dependencies"],
                    inspection_basis=review_basis,
                    inspection_rule_basis=plan["dependencies"]["inspection_rule"],
                    inspection_shots={s["id"]: digest(s) for s in shot_inputs(batch)},
                )
                store.write(store.root(path) / "scene_library.json", library)

        await run_noninterruptible_sync(commit_review)
    await run_noninterruptible_sync(
        update_unit, path, note_id, plan["basis"], unit["id"], stage="complete", status="ready", error=None
    )


def build_batch(path, catalogue, plan, unit, draft_basis, value):
    note_id = catalogue.note["id"]
    chunk = catalogue.chunk(unit["event_ids"])
    return {
        "pipeline_version": 2,
        "basis": draft_basis,
        "draft_basis": draft_basis,
        "plan_basis": plan["outline_basis"],
        "dependencies": plan["dependencies"],
        "note_id": note_id,
        "note_order": catalogue.note["order"],
        "part": unit["order"],
        "source_start": chunk["start"],
        "source_snapshot": snapshot(chunk),
        "source_basis": store.state(path)["source_basis"],
        "note_bases": {note_id: catalogue.reading["basis"]},
        "rule_basis": digest(store.effective_rule(path, "scene_shots")),
        "understanding_basis": understanding.production_context(path, [note_id], source_offset=chunk["start"])["basis"],
        "scenes": [
            {
                "id": unit["id"],
                **{k: unit[k] for k in ("title", "location", "time", "purpose")},
                "suggested_omission": unit["skipped_reason"],
                "shots": value["shots"],
            }
        ],
        "skipped_reason": "",
        "omitted_dialogues": value["omitted_dialogues"],
        "normalizations": value.get("normalizations", []),
        "omission_reason": value["omission_reason"],
        "created_at": now(),
    }


def commit_draft(path, catalogue, plan, slot, batch):
    from lib.novel_workflow.scene_library import catalog
    from lib.novel_workflow.shot_production import asset_bindings, context, dialogue_links

    with project_metadata_lock(path):
        current = scene_material.load(path, catalogue.note)
        if dependencies(path, current) != plan["dependencies"]:
            raise ValueError("生成期间来源或规则变化，已保存可复用候选")
        library = catalog(path)
        for sc in batch["scenes"]:
            for shot in sc["shots"]:
                library["shot_counter"] = library.get("shot_counter", 0) + 1
                shot["id"] = f"SH-{library['shot_counter']:04}"
                shot["production"]["shot_id"] = shot["id"]
                shot["production"]["assets"] = asset_bindings(catalogue.project, catalogue.reading, shot)
                shot["production"]["dialogue_sources"] = dialogue_links(catalogue.reading, shot)
        batch["production_context"] = context(path, catalogue.reading, batch["source_snapshot"]["chunk"])
        library["batches"][slot] = batch
        store.write(store.root(path) / "scene_library.json", library)
    return batch


def retire_drafts(path, note_id, plan_basis):
    from lib.novel_workflow.scene_library import catalog

    with project_metadata_lock(path):
        library = catalog(path)
        if library["plans"][note_id]["basis"] != plan_basis:
            return
        old = {
            key: b
            for key, b in library["batches"].items()
            if b["note_id"] == note_id and b.get("pipeline_version") != 2
        }
        library["retained_drafts"] = {
            key: b for key, b in library.get("retained_drafts", {}).items() if b["note_id"] != note_id
        }
        if not library["retained_drafts"]:
            library.pop("retained_drafts")
        library["batches"] = {key: b for key, b in library["batches"].items() if key not in old}
        store.write(store.root(path) / "scene_library.json", library)
