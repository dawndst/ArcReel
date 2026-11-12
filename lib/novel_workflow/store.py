"""Project-local notebooks and manual groups; original chapter Notes never disappear."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import atomic_write_json, load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import chapters

RULES = Path(__file__).parent / "rules"


def root(path: Path) -> Path:
    return path / "novel_workflow"


def rule(path: Path, name: str) -> str:
    local = root(path) / "rules" / f"{name}.md"
    return (local if local.exists() else RULES / f"{name}.md").read_text(encoding="utf-8")


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)


def state(path: Path) -> dict | None:
    target = root(path) / "index.json"
    return load_json(target) if target.exists() else None


def initialize(path: Path, project: dict, expected: str) -> dict:
    with project_metadata_lock(path):
        preview = chapters.index(path, project)
        if preview["source_basis"] != expected:
            raise ValueError("Source changed; refresh chapter preview")
        previous = state(path)
        result = {**preview, "groups": previous.get("groups", []) if previous else [], "initialized_at": now()}
        if previous:
            write(root(path) / "history" / f"{uuid4().hex}.json", previous)
        for name in (
            "read",
            "chapter",
            "svt",
            "review",
            "understand",
            "group",
            "scenes",
            "scope",
            "production",
            "overview",
        ):
            file = root(path) / "rules" / f"{name}.md"
            if not file.exists():
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(rule(path, name), encoding="utf-8")
        write(root(path) / "index.json", result)
        return result


def reading_key(path: Path, note: dict) -> str:
    from lib.novel_workflow.settings import chapter_rule

    return digest([note["basis"], rule(path, "read"), chapter_rule(path), 2])


def valid_readings(path: Path, notebook=None, *, before=None, respect_scope=True) -> dict:
    """Resolve cache validity once in reveal order, with bounded file reads."""
    notebook = notebook if notebook is not None else state(path)
    bases, readings = {}, {}
    from lib.novel_workflow.settings import chapter_rule as configured_chapter_rule

    read_rule, chapter_rule = rule(path, "read"), configured_chapter_rule(path)
    from lib.novel_workflow import scope

    allowed = (
        (scope.available_ids(path, notebook) if respect_scope else {n["id"] for n in notebook["notes"]})
        if notebook
        else set()
    )
    for note in notebook["notes"] if notebook else []:
        if note["id"] not in allowed:
            continue
        if before is not None and note["order"] >= before:
            break
        key = digest([note["basis"], read_rule, chapter_rule, 2])
        target = root(path) / "notes" / note["id"] / f"{key}.json"
        if target.exists():
            result = load_json(target)
            if "context_basis" not in result or result["context_basis"] == digest(bases):
                bases[note["id"]] = result["basis"]
                readings[note["id"]] = result
    return readings


def reading_context(path: Path, note: dict) -> dict:
    return {i: r["basis"] for i, r in valid_readings(path, before=note["order"]).items()}


def note_result(path: Path, note: dict) -> dict | None:
    return valid_readings(path, before=note["order"] + 1).get(note["id"])


def display_note_result(path: Path, note: dict) -> dict | None:
    """Reading material stays browsable outside the production/retrieval scope."""
    active = note_result(path, note)
    historical = valid_readings(path, before=note["order"] + 1, respect_scope=False).get(note["id"])
    cached = root(path) / "notes" / note["id"] / f"{reading_key(path, note)}.json"
    return active or historical or (load_json(cached) if cached.exists() else None)


def require_current(path: Path, project: dict, expected: str) -> dict:
    current = state(path)
    if (
        current is None
        or current["source_basis"] != expected
        or chapters.index(path, project)["source_basis"] != expected
    ):
        raise ValueError("Source or chapter index changed; refresh Notes before continuing")
    return current


def group_notes(path: Path, project: dict, note_ids: list[str], title: str, expected: str) -> dict:
    with project_metadata_lock(path):
        current = require_current(path, project, expected)
        by_id = {n["id"]: n for n in current["notes"]}
        if not note_ids or len(set(note_ids)) != len(note_ids) or any(i not in by_id for i in note_ids):
            raise ValueError("Select existing, distinct Notes")
        if any(set(g["note_ids"]) & set(note_ids) for g in current["groups"]):
            raise ValueError("章节已在资料组中，请先解散原组合再重新归组")
        ordered = sorted(note_ids, key=lambda i: by_id[i]["order"])
        group = {
            "id": uuid4().hex,
            "title": title.strip() or " / ".join(by_id[i]["chapter"] for i in ordered),
            "note_ids": ordered,
            "source_basis": expected,
            "created_at": now(),
            "created_by": "human",
            "usage": "candidate",
        }
        current["groups"].append(group)
        write(root(path) / "index.json", current)
        return group


def dissolve_group(path: Path, group_id: str) -> None:
    with project_metadata_lock(path):
        current = state(path)
        if current is None:
            raise ValueError("No chapter Notes")
        target = next((g for g in current["groups"] if g["id"] == group_id), None)
        if target is None:
            raise ValueError("Group not found")
        write(root(path) / "history" / f"group-{uuid4().hex}.json", target)
        current["groups"] = [g for g in current["groups"] if g["id"] != group_id]
        write(root(path) / "index.json", current)


def view(path: Path, project: dict) -> dict:
    current = state(path)
    if current is None:
        from lib.novel_workflow import settings

        return {
            "settings": settings.get(path),
            "initialized": False,
            "notes": [],
            "groups": [],
            "svts": [],
            "progress": None,
            "stale": False,
        }
    preview = chapters.index(path, project)
    stale = preview["source_basis"] != current["source_basis"]
    from lib.novel_workflow import scope
    from lib.novel_workflow.assets import annotate

    allowed = scope.available_ids(path, current)
    notes = []
    readings = valid_readings(path, current) if not stale else {}
    from lib.novel_workflow.condensation import metadata as load_edition

    display_readings = {**valid_readings(path, current, respect_scope=False), **readings} if not stale else {}
    for note in current["notes"]:
        result = display_readings.get(note["id"])
        if result is None and not stale:
            cached = root(path) / "notes" / note["id"] / f"{reading_key(path, note)}.json"
            result = load_json(cached) if cached.exists() else None
        current_reading = note["id"] in (readings if note["id"] in allowed else display_readings)
        older = any((root(path) / "notes" / note["id"]).glob("*.json")) if result is None else False
        notes.append(
            {
                **note,
                "reading": annotate(project, result),
                "edition": load_edition(path, note, result),
                "in_scope": note["id"] in allowed,
                "status": "stale"
                if stale
                else "read"
                if current_reading
                else "outdated"
                if result or older
                else "unread",
            }
        )
    progress_file = root(path) / "progress.json"
    svt_file = root(path) / "svts.json"
    svts = load_json(svt_file) if svt_file.exists() else None
    valid_results = {n["id"]: n["reading"]["basis"] for n in notes if n["reading"]}
    svt_stale = bool(
        svts
        and (
            stale
            or svts.get("schema_version") != 2
            or svts.get("rule_basis") != digest(rule(path, "svt"))
            or any(valid_results.get(i) != basis for i, basis in svts.get("note_bases", {}).items())
        )
    )
    from lib.novel_workflow.svt_contract import assignments, valid_svts

    display_svts = valid_svts(path, svts, display_readings)
    primary = assignments(display_svts)
    by_svt = {s["id"]: s for s in display_svts}
    for note in notes:
        assigned = by_svt.get(primary.get(note["id"]))
        note["svt_id"] = assigned["id"] if assigned else None
        note["svt_title"] = assigned["title"] if assigned else None
        note["svt_status"] = assigned.get("breakdown_status", "needs_details") if assigned else "unassigned"
        note["svt_candidates"] = [
            c
            for c in (svts or {}).get("note_candidates", {}).get(note["id"], [])
            if assigned and c.get("basis") == display_readings.get(note["id"], {}).get("basis")
        ]
    from lib.novel_workflow import memory, settings, understanding

    book = memory.ledger(path, current, readings=display_readings) if not stale else None
    reviews = []
    for file in sorted((root(path) / "reviews").glob("*.json")):
        review = load_json(file)
        review["stale"] = (
            stale
            or review["rule_basis"] != digest(rule(path, "review"))
            or any(valid_results.get(i) != b for i, b in review["note_bases"].items())
        )
        reviews.append(review)
    from lib.novel_workflow import scene_library

    groups = []
    for group in current["groups"]:
        group = dict(group)
        group["summary_stale"] = bool(group.get("synopsis")) and (
            stale
            or group.get("summary_rule_basis") != digest(rule(path, "group"))
            or any(valid_results.get(i) != b for i, b in group.get("summary_bases", {}).items())
        )
        groups.append(group)
    return {
        **current,
        "groups": groups,
        "scene_batches": scene_library.view(path, current, readings),
        "pending_assemblies": [
            {
                "episode": e["episode"],
                "title": e["title"],
                "source_basis": e["note_source"]["source_basis"],
                **e["director_selection"],
            }
            for e in project.get("episodes", [])
            if e.get("director_selection", {}).get("pending")
        ],
        "settings": settings.get(path),
        "scope": scope.view(path, current, readings),
        "understanding": understanding.view(path, current) if not stale else {"links": [], "reports": []},
        "ledger": book,
        "reviews": sorted(reviews, key=lambda r: r["created_at"], reverse=True),
        "initialized": True,
        "notes": notes,
        "stale": stale,
        "svts": svts.get("svts", []) if svts else [],
        "svt_stale": svt_stale,
        "suggestions": svts.get("suggestions", []) if svts else [],
        "progress": load_json(progress_file) if progress_file.exists() else None,
    }
