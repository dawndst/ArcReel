"""Explicit SQLite storage for migrated novel-workflow business documents.

Only selected business paths are database-owned. Rules, model responses, caches,
source text and media keep their file semantics. No reads fall back to JSON after
activation; the marker is a locator, never a second copy of business state.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from lib.infra.json_io import load_json as file_load

ROOT_FILES = {"index.json", "scope.json", "svts.json", "scene_library.json", "ledger.json"}
FOLDERS = {
    "notes",
    "editions",
    "conclusion_decisions",
    "delivery_reviews",
    "delivery_asset_reviews",
    "reviews",
    "selection_reviews",
}
_connections = ContextVar("novel_storage_connections", default=None)


def managed(relative):
    parts = Path(relative).parts
    return relative in ROOT_FILES or (
        relative.endswith(".json")
        and (
            parts[0] in FOLDERS
            or (parts[0] == "conclusions" and len(parts) == 2)
            or (parts[:2] in (("understanding", "reports"), ("understanding", "question_register")))
        )
    )


def marker(project):
    target = Path(project) / ".arcreel" / "novel-storage.json"
    return file_load(target) if target.is_file() else None


def scope(path):
    path = Path(path).absolute()
    parts = path.parts
    if "novel_workflow" not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index("novel_workflow")
    project = Path(*parts[:index])
    location = marker(project)
    if not location:
        return None
    return project, Path(*parts[index + 1 :]).as_posix(), location


def connect(project, location):
    database = (Path(project) / location["database"]).resolve()
    if not database.is_file():
        raise RuntimeError("小说业务数据库不存在；请恢复数据库，不能回退到旧JSON")
    conn = sqlite3.connect(database, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def transaction(project, *, writing=False):
    location = marker(project)
    if not location:
        yield
        return
    key = str(Path(project).absolute())
    opened = _connections.get() or {}
    if key in opened:
        yield
        return
    conn = connect(project, location)
    token = _connections.set({**opened, key: conn})
    try:
        conn.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        _connections.reset(token)
        conn.close()


@contextmanager
def connection(project, location):
    existing = (_connections.get() or {}).get(str(Path(project).absolute()))
    if existing is not None:
        yield existing
    else:
        conn = connect(project, location)
        try:
            yield conn
        finally:
            conn.close()


class Document(dict):
    """A loaded document carries the revision required for optimistic updates."""

    revision_id: str


def row(path):
    found = scope(path)
    if not found or not managed(found[1]):
        return None
    project, relative, location = found
    with connection(project, location) as conn:
        value = conn.execute(
            "SELECT r.* FROM nw_documents d JOIN nw_revisions r ON r.id=d.revision_id "
            "WHERE d.project_id=? AND d.path=?",
            (location["project_id"], relative),
        ).fetchone()
    if value is None:
        raise FileNotFoundError(str(path))
    return value


def load_json(path):
    value = row(path)
    if value is None:
        return file_load(Path(path))
    result = json.loads(value["payload"])
    if isinstance(result, dict):
        result = Document(result)
        result.revision_id = value["id"]
    return result


def put(conn, project_id, relative, value, *, expected=None, created_at=None, importing=False):
    from lib.novel_workflow.storage_graph import project as project_graph

    current = conn.execute(
        "SELECT r.id,r.version,r.digest FROM nw_documents d JOIN nw_revisions r ON r.id=d.revision_id "
        "WHERE d.project_id=? AND d.path=?",
        (project_id, relative),
    ).fetchone()
    if expected is not None and (current is None or current["id"] != expected):
        raise ValueError("内容已被其他操作更新，请刷新后重试；未覆盖新版本")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    if current and current["digest"] == digest:
        return current["id"]
    identity = uuid4().hex
    conn.execute(
        "INSERT INTO nw_revisions VALUES(?,?,?,?,?,?,?)",
        (
            identity,
            project_id,
            relative,
            current["version"] + 1 if current else 1,
            digest,
            encoded,
            created_at or time.time(),
        ),
    )
    project_graph(conn, project_id, relative, identity, value, importing=importing)
    conn.execute(
        "INSERT INTO nw_documents VALUES(?,?,?) ON CONFLICT(project_id,path) DO UPDATE SET revision_id=excluded.revision_id",
        (project_id, relative, identity),
    )
    return identity


def write(path, value):
    found = scope(path)
    if not found or not managed(found[1]):
        return False
    project, relative, location = found
    with transaction(project, writing=True), connection(project, location) as conn:
        revision = put(conn, location["project_id"], relative, value, expected=getattr(value, "revision_id", None))
    if isinstance(value, Document):
        value.revision_id = revision
    return True


class WorkflowPath(type(Path())):
    """Path-shaped workflow document locator; selected JSON paths live in SQLite."""

    def exists(self, *, follow_symlinks=True):
        found = scope(self)
        if found and managed(found[1]):
            try:
                row(self)
                return True
            except FileNotFoundError:
                return False
        return Path(self).exists()

    def is_file(self, *, follow_symlinks=True):
        found = scope(self)
        return self.exists() if found and managed(found[1]) else Path(self).is_file()

    def stat(self, *, follow_symlinks=True):
        value = row(self)
        if value is None:
            return Path(self).stat(follow_symlinks=follow_symlinks)
        stamp = value["created_at"]
        return os.stat_result((0o100600, 0, 0, 1, 0, 0, len(value["payload"].encode()), stamp, stamp, stamp))

    def read_text(self, encoding=None, errors=None):
        value = row(self)
        return value["payload"] if value is not None else Path(self).read_text(encoding=encoding, errors=errors)

    def glob(self, pattern, *, case_sensitive=None):
        found = scope(self)
        values = {
            str(p): WorkflowPath(p)
            for p in Path(self).glob(pattern)
            if not found or not managed(p.relative_to(found[0] / "novel_workflow").as_posix())
        }
        if found:
            project, relative, location = found
            prefix = "" if relative == "." else relative.rstrip("/") + "/"
            with connection(project, location) as conn:
                rows = conn.execute(
                    "SELECT path FROM nw_documents WHERE project_id=?", (location["project_id"],)
                ).fetchall()
            for item in rows:
                name = item["path"]
                if name.startswith(prefix):
                    tail = name[len(prefix) :]
                    if fnmatch.fnmatchcase(tail, str(pattern)) and ("/" in str(pattern) or "/" not in tail):
                        p = WorkflowPath(project / "novel_workflow" / name)
                        values[str(p)] = p
        yield from values.values()


def adopted_svts(project):
    """Return the database-enforced Note → primary SVT relation, or None before migration."""
    location = marker(project)
    if not location:
        return None
    with connection(project, location) as conn:
        return dict(
            conn.execute("SELECT note_id,svt_id FROM nw_note_svt WHERE project_id=?", (location["project_id"],))
        )


def reading_version(project, note_id, basis):
    """Historical evidence survives overwriting the same reading-key document."""
    location = marker(project)
    if not location:
        return None
    with connection(project, location) as conn:
        rows = conn.execute(
            "SELECT payload FROM nw_revisions WHERE project_id=? AND path LIKE ? ORDER BY created_at DESC",
            (location["project_id"], "notes/" + note_id + "/%"),
        )
        for row in rows:
            value = json.loads(row[0])
            if value.get("basis") == basis:
                return value
    return None
