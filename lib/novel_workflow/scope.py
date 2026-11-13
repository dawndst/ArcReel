"""The released/available chapters of an unfinished book, independent of task selection."""

from pathlib import Path
from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_understanding.store import digest, now
from lib.novel_workflow.storage import load_json


def get(path: Path) -> dict | None:
    from lib.novel_workflow.storage import WorkflowPath

    file = WorkflowPath(path) / "novel_workflow" / "scope.json"
    return load_json(file) if file.exists() else None


def available_ids(path, notebook) -> set[str]:
    config = get(path)
    all_ids = {note["id"] for note in notebook["notes"]}
    return all_ids & set(config["note_ids"]) if config is not None else all_ids


def basis(path, notebook) -> str:
    return digest(sorted(available_ids(path, notebook)))


def require(path, notebook, note_ids) -> None:
    if not set(note_ids) <= available_ids(path, notebook):
        raise ValueError("所选章节不在当前可用范围，请先加入范围或选择范围内的章节")


def configure(path, project, note_ids, expected, *, extend=False):
    from lib.novel_workflow import store

    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        ids = {note["id"] for note in notebook["notes"]}
        if not note_ids or len(set(note_ids)) != len(note_ids) or not set(note_ids) <= ids:
            raise ValueError("请选择有效章节作为当前可用范围")
        previous = get(path)
        selected = set(note_ids) | (set(previous["note_ids"]) if extend and previous else set())
        value = {
            "note_ids": [note["id"] for note in notebook["notes"] if note["id"] in selected],
            "updated_at": now(),
            "mode": "ongoing",
        }
        if previous is not None and previous["note_ids"] != value["note_ids"]:
            store.write(path / "novel_workflow" / "history" / f"scope-{uuid4().hex}.json", previous)
        store.write(path / "novel_workflow" / "scope.json", value)
        return value


def prepare_read(path, note_ids, expected):
    project = load_json(path / "project.json")
    return configure(path, project, note_ids, expected, extend=True)


def view(path, notebook, readings):
    config = get(path)
    allowed = available_ids(path, notebook)
    return {
        "configured": config is not None,
        "note_ids": sorted(allowed) if config else [],
        "available_count": len(allowed) if config else 0,
        "read_count": sum(i in allowed for i in readings),
        "total_count": len(notebook["notes"]),
        "mode": "ongoing",
    }
