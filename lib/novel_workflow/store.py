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
        for name in ("read", "svt"):
            file = root(path) / "rules" / f"{name}.md"
            if not file.exists():
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(rule(path, name), encoding="utf-8")
        write(root(path) / "index.json", result)
        return result


def reading_key(path: Path, note: dict) -> str:
    return digest([note["basis"], rule(path, "read")])


def note_result(path: Path, note: dict) -> dict | None:
    target = root(path) / "notes" / note["id"] / f"{reading_key(path, note)}.json"
    return load_json(target) if target.exists() else None


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
        ordered = sorted(note_ids, key=lambda i: by_id[i]["order"])
        group = {
            "id": uuid4().hex,
            "title": title.strip() or " / ".join(by_id[i]["chapter"] for i in ordered),
            "note_ids": ordered,
            "source_basis": expected,
            "created_at": now(),
            "created_by": "human",
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
        return {"initialized": False, "notes": [], "groups": [], "svts": [], "progress": None, "stale": False}
    preview = chapters.index(path, project)
    stale = preview["source_basis"] != current["source_basis"]
    notes = []
    for note in current["notes"]:
        result = note_result(path, note) if not stale else None
        notes.append({**note, "reading": result, "status": "stale" if stale else "read" if result else "unread"})
    progress_file = root(path) / "progress.json"
    svt_file = root(path) / "svts.json"
    svts = load_json(svt_file) if svt_file.exists() else None
    valid_results = {n["id"]: n["reading"]["basis"] for n in notes if n["reading"]}
    svt_stale = bool(
        svts
        and (
            stale
            or svts.get("rule_basis") != digest(rule(path, "svt"))
            or any(valid_results.get(i) != basis for i, basis in svts.get("note_bases", {}).items())
        )
    )
    return {
        **current,
        "initialized": True,
        "notes": notes,
        "stale": stale,
        "svts": svts.get("svts", []) if svts else [],
        "svt_stale": svt_stale,
        "suggestions": svts.get("suggestions", []) if svts else [],
        "progress": load_json(progress_file) if progress_file.exists() else None,
    }
