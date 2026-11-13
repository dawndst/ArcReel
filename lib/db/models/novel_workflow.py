"""SQLAlchemy metadata for the workflow repository's relational tables."""

from sqlalchemy import (
    REAL,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from lib.db.base import Base


def register_tables():
    metadata = Base.metadata
    if "nw_projects" in metadata.tables:
        return
    Table(
        "nw_projects",
        metadata,
        Column("project_id", Text, primary_key=True),
        Column("name", Text, nullable=False),
        Column("created_at", REAL, nullable=False),
    )
    Table(
        "nw_revisions",
        metadata,
        Column("id", Text, primary_key=True),
        Column("project_id", Text, ForeignKey("nw_projects.project_id"), nullable=False),
        Column("path", Text, nullable=False),
        Column("version", Integer, nullable=False),
        Column("digest", Text, nullable=False),
        Column("payload", Text, nullable=False),
        Column("created_at", REAL, nullable=False),
        UniqueConstraint("project_id", "path", "version"),
        UniqueConstraint("project_id", "path", "id"),
        Index("nw_revisions_path", "project_id", "path", "created_at"),
    )
    Table(
        "nw_documents",
        metadata,
        Column("project_id", Text, primary_key=True),
        Column("path", Text, primary_key=True),
        Column("revision_id", Text, nullable=False),
        ForeignKeyConstraint(
            ["project_id", "path", "revision_id"], ["nw_revisions.project_id", "nw_revisions.path", "nw_revisions.id"]
        ),
    )
    Table(
        "nw_entities",
        metadata,
        Column("project_id", Text, ForeignKey("nw_projects.project_id"), primary_key=True),
        Column("kind", Text, primary_key=True),
        Column("entity_id", Text, primary_key=True),
        Column("revision_id", Text, ForeignKey("nw_revisions.id")),
        Column("basis", Text),
        Column("deleted", Integer, nullable=False, server_default="0"),
        CheckConstraint("deleted IN (0,1)"),
        Index("nw_entities_revision", "project_id", "revision_id"),
    )
    Table(
        "nw_links",
        metadata,
        *(
            Column(name, Text, primary_key=True)
            for name in (
                "project_id",
                "document_path",
                "source_kind",
                "source_id",
                "target_kind",
                "target_id",
                "relation",
            )
        ),
        Column("expected_basis", Text, nullable=False, server_default=""),
        ForeignKeyConstraint(
            ["project_id", "source_kind", "source_id"],
            ["nw_entities.project_id", "nw_entities.kind", "nw_entities.entity_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "target_kind", "target_id"],
            ["nw_entities.project_id", "nw_entities.kind", "nw_entities.entity_id"],
        ),
        Index("nw_links_target", "project_id", "target_kind", "target_id"),
    )
    Table(
        "nw_note_svt",
        metadata,
        Column("project_id", Text, primary_key=True),
        Column("note_kind", Text, nullable=False, server_default="note"),
        Column("note_id", Text, primary_key=True),
        Column("svt_kind", Text, nullable=False, server_default="svt"),
        Column("svt_id", Text, nullable=False),
        CheckConstraint("note_kind='note'"),
        CheckConstraint("svt_kind='svt'"),
        ForeignKeyConstraint(
            ["project_id", "note_kind", "note_id"],
            ["nw_entities.project_id", "nw_entities.kind", "nw_entities.entity_id"],
        ),
        ForeignKeyConstraint(
            ["project_id", "svt_kind", "svt_id"],
            ["nw_entities.project_id", "nw_entities.kind", "nw_entities.entity_id"],
        ),
    )


register_tables()
