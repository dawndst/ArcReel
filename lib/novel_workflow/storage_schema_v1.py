"""Frozen relational schema for the first novel-workflow storage migration."""

DDL = (
    """CREATE TABLE nw_projects (
        project_id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, created_at REAL NOT NULL
    )""",
    """CREATE TABLE nw_revisions (
        id TEXT PRIMARY KEY NOT NULL, project_id TEXT NOT NULL REFERENCES nw_projects(project_id),
        path TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL,
        payload TEXT NOT NULL, created_at REAL NOT NULL,
        UNIQUE(project_id, path, version), UNIQUE(project_id, path, id)
    )""",
    """CREATE TABLE nw_documents (
        project_id TEXT NOT NULL, path TEXT NOT NULL, revision_id TEXT NOT NULL,
        PRIMARY KEY(project_id,path),
        FOREIGN KEY(project_id,path,revision_id) REFERENCES nw_revisions(project_id,path,id)
    )""",
    """CREATE TABLE nw_entities (
        project_id TEXT NOT NULL REFERENCES nw_projects(project_id), kind TEXT NOT NULL,
        entity_id TEXT NOT NULL, revision_id TEXT REFERENCES nw_revisions(id),
        basis TEXT, deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
        PRIMARY KEY(project_id,kind,entity_id)
    )""",
    """CREATE TABLE nw_links (
        project_id TEXT NOT NULL, document_path TEXT NOT NULL,
        source_kind TEXT NOT NULL, source_id TEXT NOT NULL,
        target_kind TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL,
        expected_basis TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(project_id,document_path,source_kind,source_id,target_kind,target_id,relation),
        FOREIGN KEY(project_id,source_kind,source_id) REFERENCES nw_entities(project_id,kind,entity_id),
        FOREIGN KEY(project_id,target_kind,target_id) REFERENCES nw_entities(project_id,kind,entity_id)
    )""",
    """CREATE TABLE nw_note_svt (
        project_id TEXT NOT NULL, note_kind TEXT NOT NULL DEFAULT 'note' CHECK(note_kind='note'),
        note_id TEXT NOT NULL, svt_kind TEXT NOT NULL DEFAULT 'svt' CHECK(svt_kind='svt'),
        svt_id TEXT NOT NULL,
        PRIMARY KEY(project_id,note_id),
        FOREIGN KEY(project_id,note_kind,note_id) REFERENCES nw_entities(project_id,kind,entity_id),
        FOREIGN KEY(project_id,svt_kind,svt_id) REFERENCES nw_entities(project_id,kind,entity_id)
    )""",
    "CREATE INDEX nw_links_target ON nw_links(project_id,target_kind,target_id)",
    "CREATE INDEX nw_revisions_path ON nw_revisions(project_id,path,created_at)",
    "CREATE INDEX nw_entities_revision ON nw_entities(project_id,revision_id)",
)
