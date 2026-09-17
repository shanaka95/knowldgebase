"""Give a drawing somewhere to live that nobody else can reach

A note's files get their own table rather than joining `attachment`. The
check on an attachment with no document falls back to the namespace, so a
drawing filed in a shared space would have been downloadable by every member
of it - which is the one thing notes promise cannot happen.

`user_id` is on the row rather than reached through the note, so the ownership
test is a column comparison and can never become a join somebody forgets.

Revision ID: d4f1c827e903
Revises: c3e6b90d5a18
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4f1c827e903"
down_revision = "c3e6b90d5a18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "noteasset",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_noteasset_object_key"),
    )
    op.create_index("ix_noteasset_note", "noteasset", ["note_id", "created_at"])
    op.create_index("ix_noteasset_user", "noteasset", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_noteasset_user", table_name="noteasset")
    op.drop_index("ix_noteasset_note", table_name="noteasset")
    op.drop_table("noteasset")
