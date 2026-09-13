"""Agents and channel connections

Revision ID: f7b3d52c9014
Revises: e5a72b94c118
Create Date: 2026-09-13

An agent is a conversational assistant backed by its own Hermes profile; a
channel connection binds a proven platform identity to one. The unique
constraint on ``(channel_type, platform_identity)`` is the product rule - one
channel account connects once - enforced where a race cannot get past it.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "f7b3d52c9014"
down_revision: str | None = "e5a72b94c118"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column(
            "persona", sqlmodel.sql.sqltypes.AutoString(length=4000), nullable=True
        ),
        sa.Column(
            "profile_name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("shard_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "status_detail",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=True,
        ),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column(
            "llm_token_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["apikey.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_agent_user_name"),
    )
    op.create_index("ix_agent_user_id", "agent", ["user_id"])
    op.create_index("ix_agent_shard", "agent", ["shard_id"])
    op.create_index("ix_agent_profile_name", "agent", ["profile_name"], unique=True)
    op.create_index("ix_agent_llm_token_hash", "agent", ["llm_token_hash"])

    op.create_table(
        "channelconnection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column(
            "platform_identity",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_type", "platform_identity", name="uq_channel_identity"
        ),
    )
    op.create_index("ix_channelconnection_agent_id", "channelconnection", ["agent_id"])

    op.create_table(
        "channellinkcode",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column(
            "code_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channellinkcode_code_hash", "channellinkcode", ["code_hash"], unique=True
    )
    op.create_index("ix_channellinkcode_agent", "channellinkcode", ["agent_id"])

    op.create_table(
        "channelconfig",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "public_handle",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channelconfig_channel_type", "channelconfig", ["channel_type"], unique=True
    )


def downgrade() -> None:
    op.drop_table("channelconfig")
    op.drop_table("channellinkcode")
    op.drop_table("channelconnection")
    op.drop_table("agent")
