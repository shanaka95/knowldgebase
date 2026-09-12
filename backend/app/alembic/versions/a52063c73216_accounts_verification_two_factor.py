"""accounts: email verification, two-factor codes, session epochs

Revision ID: a52063c73216
Revises: 72d563bcfe03
Create Date: 2026-09-12

Adds the state an account needs to be safe in public: whether its address has
been confirmed, how many recent password attempts have failed, and which
generation of access tokens is still valid.

Accounts that already exist are marked confirmed. They were created before this
requirement existed, and nobody can confirm an address on their behalf, so the
alternative is locking every existing user out of their own knowledge base.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "a52063c73216"
down_revision: str | None = "72d563bcfe03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # server_default so the column can be NOT NULL on a table that already has
    # rows; the application sets it explicitly from here on.
    op.add_column(
        "user",
        sa.Column(
            "session_epoch", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "user",
        sa.Column(
            "failed_logins", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "user",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Grandfather in everyone who registered before confirmation was required.
    op.execute(
        'UPDATE "user" SET email_verified_at = COALESCE(created_at, now()) '
        "WHERE email_verified_at IS NULL"
    )

    op.create_table(
        "authcode",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column(
            "code_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "sent_to", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Redemption looks a secret up by hash alone, so this index carries the
    # whole hot path.
    op.create_index("ix_authcode_code_hash", "authcode", ["code_hash"])
    # Rate limiting and retiring older codes both scan by account and purpose.
    op.create_index("ix_authcode_user_id", "authcode", ["user_id"])
    op.create_index(
        "ix_authcode_user_purpose", "authcode", ["user_id", "purpose", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_authcode_user_purpose", table_name="authcode")
    op.drop_index("ix_authcode_user_id", table_name="authcode")
    op.drop_index("ix_authcode_code_hash", table_name="authcode")
    op.drop_table("authcode")
    op.drop_column("user", "last_failed_login_at")
    op.drop_column("user", "failed_logins")
    op.drop_column("user", "locked_until")
    op.drop_column("user", "session_epoch")
    op.drop_column("user", "email_verified_at")
