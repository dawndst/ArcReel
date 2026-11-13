"""Novel workflow transactional documents, versions and relations.

Revision ID: a81d247e96c0
Revises: f6d2a8c4b931
"""

from alembic import op

revision = "a81d247e96c0"
down_revision = "f6d2a8c4b931"
branch_labels = None
depends_on = None


def upgrade():
    from lib.novel_workflow.storage_schema_v1 import DDL

    for statement in DDL:
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    for table in ("nw_note_svt", "nw_links", "nw_entities", "nw_documents", "nw_revisions", "nw_projects"):
        op.drop_table(table)
