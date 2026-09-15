"""Credits: a monthly allowance, and grants on top of it

Revision ID: c71d0e83a5b6
Revises: b5c19e4a72f8
Create Date: 2026-09-15

`monthly_credits` is the fourth entry in the limits registry, so it arrives the
way the docstring in `app/services/quota.py` promised one would: a nullable
column on `user` and on `usergroup`, and nothing else. NULL means inherit, as
everywhere else, which is why neither column has a default - a default would
make "no opinion" unsayable and inheritance would silently stop working.

The default group is given 1000, so every existing account gets a working
allowance the moment this runs rather than falling through to the constant.

`creditgrant` holds one-off top-ups. `expires_at` is NOT NULL on purpose: a
grant that never expired would sit on the balance for ever, and working out how
much of it had been spent would need a stored counter - which is exactly what
this design avoids by deriving the balance from `usagedaily` instead. A
permanent raise has its own tool, the account's own `monthly_credits`.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "c71d0e83a5b6"
down_revision: str | None = "b5c19e4a72f8"
branch_labels: str | None = None
depends_on: str | None = None

# Must match app.core.config.Settings.MONTHLY_CREDITS.
DEFAULT_MONTHLY_CREDITS = 1000


def upgrade() -> None:
    for table in ("user", "usergroup"):
        op.add_column(table, sa.Column("monthly_credits", sa.Integer(), nullable=True))

    # So the default group is a working floor from the first request, rather
    # than everyone resolving through to the built-in constant.
    op.execute(
        f"UPDATE usergroup SET monthly_credits = {DEFAULT_MONTHLY_CREDITS} "
        "WHERE is_default"
    )

    op.create_table(
        "creditgrant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount_milli", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sqlmodel.sql.sqltypes.AutoString(length=300),
            nullable=False,
            server_default="",
        ),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        # The grant outlives the administrator who made it; who gave it is
        # history, not a dependency.
        sa.ForeignKeyConstraint(["granted_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_milli > 0", name="ck_creditgrant_positive"),
    )
    # "what is this account holding right now", asked before every metered
    # operation, so it is answered from the index.
    op.create_index(
        "ix_creditgrant_user_expires", "creditgrant", ["user_id", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_creditgrant_user_expires", table_name="creditgrant")
    op.drop_table("creditgrant")
    for table in ("usergroup", "user"):
        op.drop_column(table, "monthly_credits")
