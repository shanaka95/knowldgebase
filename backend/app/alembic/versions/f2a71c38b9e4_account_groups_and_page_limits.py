"""Account groups, and a limit on how many pages an account may create

Revision ID: f2a71c38b9e4
Revises: e6b3c92d15af
Create Date: 2026-09-15

Limits resolve through four tiers - the account's own override, its group, the
default group, then a built-in constant - and NULL at any tier means "inherit".
That is why the two limits that already existed have to *become* nullable here:
as NOT NULL columns with a default of 50 they cannot express "no opinion", so
they could never inherit anything.

Two details in here are load-bearing and easy to miss:

* ``server_default=None`` on the alters. Both columns were created with
  ``server_default="50"``. Dropping NOT NULL without dropping the default
  leaves every *new* row getting a database-side 50 - including rows made by
  code paths that do not mention the field at all - so inheritance would look
  fine in any test that inspects a Python object and be broken in the database.
* The default group is inserted with a **fixed id**, so the migration, the
  boot-time seed and the resolver all converge on one row without scanning for
  a boolean.

Existing values that are not 50 are kept as genuine per-account overrides
rather than being flattened, so nothing an administrator deliberately set is
lost.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "f2a71c38b9e4"
down_revision: str | None = "e6b3c92d15af"
branch_labels: str | None = None
depends_on: str | None = None

# Must match app.services.quota.DEFAULT_GROUP_ID.
DEFAULT_GROUP_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.create_table(
        "usergroup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column(
            "description", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True
        ),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("max_pages", sa.Integer(), nullable=True),
        sa.Column("max_shares_per_document", sa.Integer(), nullable=True),
        sa.Column("max_members_per_space", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(max_pages IS NULL OR max_pages >= 0) AND "
            "(max_shares_per_document IS NULL OR max_shares_per_document >= 0) AND "
            "(max_members_per_space IS NULL OR max_members_per_space >= 0)",
            name="ck_usergroup_limits_nonneg",
        ),
    )
    op.create_index("ix_usergroup_slug", "usergroup", ["slug"], unique=True)
    # Names are compared the way a person would compare them, as elsewhere.
    op.execute(
        "CREATE UNIQUE INDEX uq_usergroup_name ON usergroup (lower(name))"
    )
    # At most one default. It cannot enforce *at least* one, which is why the
    # row is also re-seeded at every boot by `quota.ensure_default_group`.
    op.execute(
        "CREATE UNIQUE INDEX uq_usergroup_one_default "
        "ON usergroup (is_default) WHERE is_default"
    )

    op.execute(
        f"""
        INSERT INTO usergroup (
            id, slug, name, description, is_default, is_system,
            max_pages, max_shares_per_document, max_members_per_space,
            created_at, updated_at
        )
        VALUES (
            '{DEFAULT_GROUP_ID}', 'default', 'Default',
            'Applies to everyone who has not been put in another group.',
            true, true, 100, 50, 50, NOW(), NOW()
        )
        """
    )

    op.add_column("user", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_user_group_id",
        "user",
        "usergroup",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Deleting a group sets this null across every member, which scans `user`
    # without an index; it is also how "who is in this group" is answered.
    op.create_index("ix_user_group_id", "user", ["group_id"])
    op.add_column("user", sa.Column("max_pages", sa.Integer(), nullable=True))

    # The two that already existed learn to say "no opinion". Dropping the
    # server default is the half of this that is easy to forget and impossible
    # to notice from Python.
    for column in ("max_shares_per_document", "max_members_per_space"):
        op.alter_column(
            "user", column, existing_type=sa.Integer(), nullable=True, server_default=None
        )
        # Anything still at the old default was never a decision; anything else
        # was, and survives as a per-account override.
        op.execute(f'UPDATE "user" SET {column} = NULL WHERE {column} = 50')

    # Whoever runs the installation should not be locked out of it by a number
    # that did not exist yesterday - and on an instance that has been running a
    # while, theirs is the account most likely to be past it already. A plain
    # override, so it is visible in the admin table and can be lowered.
    op.execute('UPDATE "user" SET max_pages = 100000 WHERE is_superuser')

    # Both counters run on every page creation and neither column was indexed.
    op.create_index("ix_document_created_by", "document", ["created_by"])
    op.create_index(
        "ix_importjob_created_by_status", "importjob", ["created_by", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_importjob_created_by_status", table_name="importjob")
    op.drop_index("ix_document_created_by", table_name="document")

    for column in ("max_shares_per_document", "max_members_per_space"):
        op.execute(f'UPDATE "user" SET {column} = 50 WHERE {column} IS NULL')
        op.alter_column(
            "user",
            column,
            existing_type=sa.Integer(),
            nullable=False,
            server_default="50",
        )

    op.drop_column("user", "max_pages")
    op.drop_index("ix_user_group_id", table_name="user")
    op.drop_constraint("fk_user_group_id", "user", type_="foreignkey")
    op.drop_column("user", "group_id")

    op.execute("DROP INDEX IF EXISTS uq_usergroup_one_default")
    op.execute("DROP INDEX IF EXISTS uq_usergroup_name")
    op.drop_index("ix_usergroup_slug", table_name="usergroup")
    op.drop_table("usergroup")
