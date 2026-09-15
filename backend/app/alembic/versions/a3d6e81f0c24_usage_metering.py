"""Usage metering, by account, day and model

Revision ID: a3d6e81f0c24
Revises: f2a71c38b9e4
Create Date: 2026-09-15

One table, no backfill, nothing altered. There is no history to migrate because
none was ever kept: the provider has been returning a `usage` block on every
response all along and the code discarded it.

The table stores what is read rather than what happens. Providers are called
many times per request - retries, fallbacks, one embedding per query and one
vision call per page of a PDF - but every question asked of the data is "whose,
which day, which model", so that is the grain of the row. Requests accumulate
their calls in memory and fold them in with a single UPSERT.

Two details worth stating:

* **`uq_usagedaily_bucket` is the UPSERT target**, not a data-quality
  constraint. `ON CONFLICT ... DO UPDATE SET col = col + EXCLUDED.col` is what
  makes concurrent writers add to each other instead of overwriting, and it
  needs a named constraint to conflict against.
* **`model` is `''` and never NULL** on the bookkeeping rows that count what a
  person did rather than what answered them. It is part of that unique key,
  and NULLs are distinct in a unique index, so a nullable column here would
  silently insert a new row every time instead of adding to the existing one.

Deleting an account takes its usage with it - `ON DELETE CASCADE`. Past totals
on the admin dashboard therefore shrink when somebody is removed, which is the
right trade for not keeping spending records against people who are gone.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "a3d6e81f0c24"
down_revision: str | None = "f2a71c38b9e4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "usagedaily",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("feature", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column(
            "model",
            sqlmodel.sql.sqltypes.AutoString(length=160),
            nullable=False,
            server_default="",
        ),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "reasoning_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "cache_write_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("search_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost_nanos", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "day", "user_id", "feature", "kind", "model", name="uq_usagedaily_bucket"
        ),
    )
    # "my usage over this range" - the only question the user's own dashboard
    # asks, and it is answered from the index.
    op.create_index("ix_usagedaily_user_day", "usagedaily", ["user_id", "day"])
    # "everyone's usage over this range" - the admin one. Per-group roll-ups
    # join `user.group_id`, which `ix_user_group_id` already covers.
    op.create_index("ix_usagedaily_day", "usagedaily", ["day"])


def downgrade() -> None:
    op.drop_index("ix_usagedaily_day", table_name="usagedaily")
    op.drop_index("ix_usagedaily_user_day", table_name="usagedaily")
    op.drop_table("usagedaily")
