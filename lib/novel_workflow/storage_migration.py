"""Offline-safe activation, verification and rollback of workflow SQL storage."""

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from lib.infra.json_io import atomic_write_json, load_json
from lib.novel_workflow import storage


def migrate(project, database):
    from lib.artifacts.formal_write import project_metadata_lock

    project, database = Path(project).resolve(), Path(database).resolve()
    if storage.marker(project):
        return {"already_migrated": True}
    if not database.is_file():
        raise FileNotFoundError(database)
    with project_metadata_lock(project):
        if storage.marker(project):
            return {"already_migrated": True}
        root = project / "novel_workflow"
        files = [f for f in root.rglob("*.json") if storage.managed(f.relative_to(root).as_posix())]

        def rank(f):
            folder = f.relative_to(root).parts[0]
            priority = 0 if f.name == "index.json" else 1 if folder == "notes" else 3 if f.name == "svts.json" else 4
            return priority, f.stat().st_mtime

        files.sort(key=rank)
        project_id = uuid4().hex
        location = {"format": 1, "project_id": project_id, "database": os.path.relpath(database, project)}
        archive = project / ".arcreel" / "novel-json-before-sqlite" / project_id
        archive.mkdir(parents=True)
        conn = sqlite3.connect(database, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        counts = {}
        try:
            conn.execute("INSERT INTO nw_projects VALUES(?,?,?)", (project_id, project.name, time.time()))
            history = root / "storage_history.json"
            if history.is_file():
                shutil.copy2(history, archive / "storage_history.json")
                for item in load_json(history):
                    relative = item["path"]
                    if not storage.managed(relative) or ".." in Path(relative).parts or Path(relative).is_absolute():
                        raise ValueError("Invalid workflow history path")
                    storage.put(
                        conn, project_id, relative, item["payload"], created_at=item["created_at"], importing=True
                    )
            for file in files:
                relative = file.relative_to(root).as_posix()
                value = load_json(file)
                backup = archive / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, backup)
                storage.put(conn, project_id, relative, value, created_at=file.stat().st_mtime, importing=True)
                stored = conn.execute(
                    "SELECT payload FROM nw_revisions r JOIN nw_documents d ON r.id=d.revision_id WHERE d.project_id=? AND d.path=?",
                    (project_id, relative),
                ).fetchone()
                if json.loads(stored[0]) != value:
                    raise ValueError(f"Migration verification failed: {relative}")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Migration foreign-key verification failed")
            for table in ("nw_documents", "nw_revisions", "nw_entities", "nw_links", "nw_note_svt"):
                counts[table] = conn.execute(
                    f"SELECT count(*) FROM {table} WHERE project_id=?", (project_id,)
                ).fetchone()[0]
            conn.commit()
            atomic_write_json(archive / "migration.json", {"location": location, "counts": counts})
            # After activation, JSON is ignored even if archival cleanup is interrupted.
            atomic_write_json(project / ".arcreel" / "novel-storage.json", location)
            for file in files + ([history] if history.is_file() else []):
                destination = archive / file.relative_to(root)
                os.replace(file, destination)
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        return {"project_id": project_id, "counts": counts, "archive": str(archive)}


def ensure(project):
    """Use the existing application SQLite database for all new workflow projects."""
    if storage.marker(project):
        return
    from sqlalchemy.engine import make_url

    from lib.db.engine import get_database_url

    url = make_url(get_database_url())
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("小说业务存储当前要求文件型SQLite数据库")
    migrate(project, Path(url.database))


def snapshot(project):
    """Portable core documents for project export; never export database locators."""
    location = storage.marker(project)
    if not location:
        return {}
    with storage.transaction(project), storage.connection(project, location) as conn:
        rows = conn.execute(
            "SELECT d.path,r.payload FROM nw_documents d JOIN nw_revisions r ON d.revision_id=r.id WHERE d.project_id=?",
            (location["project_id"],),
        ).fetchall()
        result = {"novel_workflow/" + r["path"]: r["payload"].encode() for r in rows}
        revisions = conn.execute(
            "SELECT r.path,r.payload,r.created_at FROM nw_revisions r JOIN nw_documents d ON r.project_id=d.project_id AND r.path=d.path WHERE r.project_id=? AND r.id<>d.revision_id ORDER BY r.created_at,r.version",
            (location["project_id"],),
        ).fetchall()
        if revisions:
            result["novel_workflow/storage_history.json"] = json.dumps(
                [
                    {"path": r["path"], "payload": json.loads(r["payload"]), "created_at": r["created_at"]}
                    for r in revisions
                ],
                ensure_ascii=False,
            ).encode()
        return result


def rollback(project):
    """Export the latest SQL state before reverting to file storage (service stopped)."""
    project = Path(project)
    location = storage.marker(project)
    if not location:
        return {"already_files": True}
    values = snapshot(project)
    for name, content in values.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, json.loads(content))
    marker = project / ".arcreel" / "novel-storage.json"
    os.replace(marker, marker.with_name("novel-storage-rolled-back-" + str(int(time.time())) + ".json"))
    return {"documents": sum(name != "novel_workflow/storage_history.json" for name in values)}
