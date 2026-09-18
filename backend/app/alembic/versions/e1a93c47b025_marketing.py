"""Somewhere to keep a list, and a record of what was sent to it

Three tables, and the first one is the argument. A marketing contact is not a
`User`, however much it looks like one. `register_user` treats an existing
unverified row as somebody signing up again and only re-sends verification, so
a contact row - which has no password anybody knows - would have locked every
person on the list out of ever creating an account. `reset_password` sets
`email_verified_at`, so a cold address could have promoted itself into a
verified account. And the admin user list selects every `User` with no filter,
so the console, the account count and the per-row quota and credit arithmetic
would all have been computed over several hundred strangers.

`marketingdelivery.send_after` is where the pacing lives. Each row is stamped a
second after the one before it, so exactly one becomes due per second and the
send rate is a property of the data rather than of a sleeping process. The
partial index is the claim query and nothing else.

The unique key on (campaign, contact) is the at-most-once guarantee. The row is
written and committed before the message goes out, so a crash between the two
loses a send rather than repeating one - the same trade `notereminderdelivery`
makes, and for the same reason.

Revision ID: e1a93c47b025
Revises: d4f1c827e903
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e1a93c47b025"
down_revision = "d4f1c827e903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketingcontact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("unsubscribe_token", sa.String(length=64), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_marketingcontact_email"),
        sa.UniqueConstraint(
            "unsubscribe_token", name="uq_marketingcontact_unsubscribe_token"
        ),
    )
    op.create_index(
        "ix_marketingcontact_unsubscribed", "marketingcontact", ["unsubscribed_at"]
    )
    op.create_index(
        "ix_marketingcontact_token", "marketingcontact", ["unsubscribe_token"]
    )

    op.create_table(
        "marketingcampaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marketingcampaign_created", "marketingcampaign", ["created_at"])

    op.create_table(
        "marketingdelivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["marketingcampaign.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["marketingcontact.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id", "contact_id", name="uq_marketingdelivery_once"
        ),
    )
    op.create_index(
        "ix_marketingdelivery_due",
        "marketingdelivery",
        ["send_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_marketingdelivery_campaign",
        "marketingdelivery",
        ["campaign_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketingdelivery_campaign", table_name="marketingdelivery")
    op.drop_index("ix_marketingdelivery_due", table_name="marketingdelivery")
    op.drop_table("marketingdelivery")
    op.drop_index("ix_marketingcampaign_created", table_name="marketingcampaign")
    op.drop_table("marketingcampaign")
    op.drop_index("ix_marketingcontact_token", table_name="marketingcontact")
    op.drop_index("ix_marketingcontact_unsubscribed", table_name="marketingcontact")
    op.drop_table("marketingcontact")
