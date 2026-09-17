"""Chunks and jobs for indexing a note

Revision ID: b2d5a8f31c74
Revises: a1c4f7e92b60
Create Date: 2026-09-17

Parallel tables rather than nullable columns on `documentchunk` and
`embeddingjob`. Eight functions in the worker load a Document straight off
`job.document_id` and compare versions before writing anything; making that
column optional puts a branch in each of them, on the busiest table in the
system, where getting one wrong fails silently rather than loudly - a note
stuck mid-stage, or the wrong row marked failed. `importjob` made the same
choice for the same reason.

It also costs nothing structurally: the foreign key is what makes a deleted
note take its chunks and jobs with it, and a polymorphic entity id cannot have
one.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d5a8f31c74"
down_revision: str | None = "a1c4f7e92b60"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "notechunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("doc_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "note_id", "doc_version", "chunk_index", name="uq_note_chunk"
        ),
    )
    op.create_index("ix_notechunk_note_id", "notechunk", ["note_id"])

    op.create_table(
        "noteembeddingjob",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("doc_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column(
            "locked_by", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column(
            "stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_noteembeddingjob_status_run_after",
        "noteembeddingjob",
        ["status", "run_after"],
    )
    op.create_index(
        "ix_noteembeddingjob_note_created",
        "noteembeddingjob",
        ["note_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_noteembeddingjob_note_created", table_name="noteembeddingjob")
    op.drop_index(
        "ix_noteembeddingjob_status_run_after", table_name="noteembeddingjob"
    )
    op.drop_table("noteembeddingjob")
    op.drop_index("ix_notechunk_note_id", table_name="notechunk")
    op.drop_table("notechunk")
