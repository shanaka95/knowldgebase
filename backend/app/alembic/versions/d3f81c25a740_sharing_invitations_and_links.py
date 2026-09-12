"""sharing: invitations, public links, and a per-account limit

Revision ID: d3f81c25a740
Revises: c9e2f1a4b806
Create Date: 2026-09-12

Three additions, all to do with giving somebody else access to one page:

* ``shareinvitation`` records a page shared with an address that has no account
  yet. It is not access - it becomes a real share when that address is
  confirmed on an account.
* ``document.public_slug`` marks a page readable by anyone holding its link. A
  random slug rather than the page id, so withdrawing and re-sharing produces a
  new link instead of quietly re-publishing to whoever kept the old one.
* ``user.max_shares_per_document`` is how widely one of an account's pages may
  be shared. Per account so it can follow a plan later without another
  migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "d3f81c25a740"
down_revision: str | None = "c9e2f1a4b806"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shareinvitation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column(
            "token_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Redemption finds every invitation for one address; the interface lists
    # them per page; the link is looked up by hash alone.
    op.create_index("ix_shareinvitation_email", "shareinvitation", ["email"])
    op.create_index("ix_shareinvitation_document", "shareinvitation", ["document_id"])
    op.create_index(
        "ix_shareinvitation_document_id", "shareinvitation", ["document_id"]
    )
    op.create_index(
        "ix_shareinvitation_token_hash", "shareinvitation", ["token_hash"]
    )

    op.add_column(
        "document",
        sa.Column(
            "public_slug", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True
        ),
    )
    op.create_index(
        "ix_document_public_slug", "document", ["public_slug"], unique=True
    )
    op.add_column(
        "document",
        sa.Column("public_shared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("document", sa.Column("public_shared_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_document_public_shared_by_user",
        "document",
        "user",
        ["public_shared_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "user",
        sa.Column(
            "max_shares_per_document",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "max_shares_per_document")
    op.drop_constraint(
        "fk_document_public_shared_by_user", "document", type_="foreignkey"
    )
    op.drop_column("document", "public_shared_by")
    op.drop_column("document", "public_shared_at")
    op.drop_index("ix_document_public_slug", table_name="document")
    op.drop_column("document", "public_slug")
    op.drop_index("ix_shareinvitation_token_hash", table_name="shareinvitation")
    op.drop_index("ix_shareinvitation_document_id", table_name="shareinvitation")
    op.drop_index("ix_shareinvitation_document", table_name="shareinvitation")
    op.drop_index("ix_shareinvitation_email", table_name="shareinvitation")
    op.drop_table("shareinvitation")
