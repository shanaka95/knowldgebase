"""Ask conversations

Revision ID: c4e91a7b2d55
Revises: 7a109a76b1c6
Create Date: 2026-09-14

A thread of questions and answers, private to the person who asked. Threads
outlive the page they were pinned to and the space they were asked in - both
foreign keys are ``SET NULL`` - because a deleted page should not take somebody
else's reading of it with it.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e91a7b2d55"
down_revision: str | None = "7a109a76b1c6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "askconversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("namespace_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["namespace_id"], ["namespace.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The history rail's only question: my threads, newest first.
    op.create_index(
        "ix_askconversation_user_updated",
        "askconversation",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "askmessage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["askconversation.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_askmessage_conversation_seq", "askmessage", ["conversation_id", "seq"]
    )


def downgrade() -> None:
    op.drop_index("ix_askmessage_conversation_seq", table_name="askmessage")
    op.drop_table("askmessage")
    op.drop_index("ix_askconversation_user_updated", table_name="askconversation")
    op.drop_table("askconversation")
