"""Migration and business invariants, without provider calls."""

import json
import sqlite3

import pytest

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import atomic_write_json
from lib.novel_workflow import storage, store
from lib.novel_workflow.storage_migration import migrate, rollback, snapshot
from lib.novel_workflow.storage_schema_v1 import DDL


@pytest.fixture
def migrated(tmp_path):
    project = tmp_path / "book"
    root = project / "novel_workflow"
    root.mkdir(parents=True)
    atomic_write_json(root / "index.json", {"notes": [{"id": "n1", "basis": "source1"}], "groups": []})
    (root / "notes/n1").mkdir(parents=True)
    atomic_write_json(
        root / "notes/n1/key.json", {"basis": "v1", "events": [{"id": "e1", "dialogues": [{"id": "d1"}]}]}
    )
    atomic_write_json(
        root / "svts.json",
        {
            "svts": [
                {
                    "id": "s1",
                    "note_ids": ["n1"],
                    "event_ids": ["e1"],
                    "climaxes": [{"event_ids": ["e1"], "dialogue_ids": ["d1"]}],
                }
            ]
        },
    )
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        for sql in DDL:
            conn.execute(sql)
    before = {str(f.relative_to(root)): json.loads(f.read_text()) for f in root.rglob("*.json")}
    migrate(project, db)
    return project, db, before


def test_migration_and_portable_export_preserve_values(migrated):
    project, db, before = migrated
    assert migrate(project, db) == {"already_migrated": True}
    values = snapshot(project)
    assert {key.removeprefix("novel_workflow/"): json.loads(value) for key, value in values.items()} == before
    assert not list((project / "novel_workflow").rglob("*.json"))
    assert [f.name for f in (store.root(project) / "notes/n1").glob("*.json")] == ["key.json"]
    with sqlite3.connect(db) as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT note_id,svt_id FROM nw_note_svt").fetchall() == [("n1", "s1")]


def test_no_fallback_to_old_json(migrated):
    project, db, _ = migrated
    atomic_write_json(project / "novel_workflow/index.json", {"corrupt": True})
    assert "corrupt" not in store.state(project)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM nw_documents WHERE path='index.json'")
    assert store.state(project) is None
    assert "index.json" not in [f.name for f in store.root(project).glob("*.json")]


def test_document_conflict_preserves_newest(migrated):
    project, _, _ = migrated
    old, latest = store.state(project), store.state(project)
    latest["updated"] = 1
    store.write(store.root(project) / "index.json", latest)
    latest["updated"] = 2
    store.write(store.root(project) / "index.json", latest)
    old["updated"] = 99
    with pytest.raises(ValueError, match="更新"):
        store.write(store.root(project) / "index.json", old)
    assert store.state(project)["updated"] == 2


def test_multiple_writes_roll_back_on_duplicate_adoption(migrated):
    project, db, _ = migrated
    before = snapshot(project)

    def conflicting_update():
        with project_metadata_lock(project):
            store.write(store.root(project) / "scope.json", {"chapter_start": 2})
            svt = storage.load_json(store.root(project) / "svts.json")
            svt["svts"].append({"id": "s2", "note_ids": ["n1"], "event_ids": ["e1"]})
            store.write(store.root(project) / "svts.json", svt)

    with pytest.raises(sqlite3.IntegrityError):
        conflicting_update()
    assert snapshot(project) == before
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM nw_revisions").fetchone()[0] == 3
        assert not conn.execute("SELECT 1 FROM nw_entities WHERE entity_id='s2'").fetchone()


def test_unknown_event_is_rejected_without_partial_revision(migrated):
    project, _, _ = migrated
    before = snapshot(project)
    with pytest.raises(ValueError, match="Missing event"):
        store.write(
            store.root(project) / "svts.json", {"svts": [{"id": "s1", "note_ids": ["n1"], "event_ids": ["absent"]}]}
        )
    assert snapshot(project) == before


def test_rollback_exports_latest_database_version(migrated):
    project, _, _ = migrated
    data = store.state(project)
    data["title"] = "latest"
    store.write(store.root(project) / "index.json", data)
    assert rollback(project)["documents"] == 3
    assert storage.marker(project) is None
    assert store.state(project)["title"] == "latest"


@pytest.mark.asyncio
async def test_real_reading_and_svt_flow_uses_sqlite(tmp_path):
    from lib.novel_workflow.service import generate_svts, read_notes
    from tests.unit.lib.episode.test_novel_workflow import Reader, SVTReader
    from tests.unit.lib.episode.test_novel_workflow import project as fixture_project

    _project_data, notebook = fixture_project(tmp_path)
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        for sql in DDL:
            conn.execute(sql)
    migrate(tmp_path, db)
    ids = [n["id"] for n in notebook["notes"]]
    await read_notes(tmp_path, Reader(), ids, notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[0]], notebook["source_basis"])
    await generate_svts(tmp_path, SVTReader(), [ids[1]], notebook["source_basis"])
    assert len(store.valid_readings(tmp_path)) == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM nw_note_svt").fetchone()[0] == 2
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_export_reimport_preserves_overwritten_reading_evidence(migrated, tmp_path):
    project, db, _ = migrated
    note = store.root(project) / "notes/n1/key.json"
    value = storage.load_json(note)
    value["basis"] = "v2"
    value["events"] = []
    store.write(note, value)
    assert storage.reading_version(project, "n1", "v1")["events"][0]["id"] == "e1"
    restored = tmp_path / "restored"
    for relative, content in snapshot(project).items():
        destination = restored / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    migrate(restored, db)
    assert storage.load_json(store.root(restored) / "notes/n1/key.json")["basis"] == "v2"
    assert storage.reading_version(restored, "n1", "v1")["events"][0]["id"] == "e1"
    assert storage.marker(restored)["project_id"] != storage.marker(project)["project_id"]


def test_export_snapshot_contains_sql_documents_without_locator(migrated, tmp_path):
    from types import SimpleNamespace

    from server.services.project.project_archive import ProjectArchiveService

    project, _, before = migrated
    service = ProjectArchiveService(SimpleNamespace(projects_dir=project.parent, PROJECT_FILE="project.json"))
    target = tmp_path / "archive"
    atomic_write_json(project / "novel_workflow/scope.json", {"obsolete": True})
    service._capture_stable_visible_tree(project, target)
    assert json.loads((target / "novel_workflow/index.json").read_text()) == before["index.json"]
    assert not (target / ".arcreel/novel-storage.json").exists()
    assert not (target / "novel_workflow/scope.json").exists()


def test_migration_schema_matches_registered_metadata(migrated):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from lib.db.base import Base
    from lib.db.models import register_models

    _, database, _ = migrated
    register_models()
    engine = create_engine("sqlite:///" + str(database))
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_object": lambda obj, name, kind, reflected, compare_to: (
                    name.startswith("nw_") if kind == "table" else True
                ),
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()
