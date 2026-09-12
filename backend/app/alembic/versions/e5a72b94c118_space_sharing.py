"""sharing: a space can be shared the same way a page can

Revision ID: e5a72b94c118
Revises: d3f81c25a740
Create Date: 2026-09-12

An invitation was to a page. It can now be to a page *or* a space, because the
two are the same promise at different scales and giving them one redemption path
means an address confirmed once collects everything waiting for it.

``document_id`` therefore becomes nullable and ``namespace_id`` joins it, with
exactly one of the pair set on any row. ``role`` widens from the page roles
(viewer, editor) to also carry the space roles (viewer, editor, admin); it was
already a VARCHAR, so this is a change of meaning rather than of type.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a72b94c118"
down_revision: str | None = "d3f81c25a740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "shareinvitation", "document_id", existing_type=sa.Uuid(), nullable=True
    )
    op.add_column(
        "shareinvitation", sa.Column("namespace_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_shareinvitation_namespace",
        "shareinvitation",
        "namespace",
        ["namespace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_shareinvitation_namespace_id", "shareinvitation", ["namespace_id"]
    )
    # An invitation is to one thing. Enforced here rather than trusted to the
    # application, because a row with both or neither would be unredeemable and
    # nothing would notice until somebody confirmed their address.
    op.create_check_constraint(
        "ck_shareinvitation_one_target",
        "shareinvitation",
        "(document_id IS NULL) <> (namespace_id IS NULL)",
    )

    op.add_column(
        "user",
        sa.Column(
            "max_members_per_space",
            sa.Integer(),
            nullable=False,
            server_default="50",
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "max_members_per_space")
    op.drop_constraint(
        "ck_shareinvitation_one_target", "shareinvitation", type_="check"
    )
    op.drop_index("ix_shareinvitation_namespace_id", table_name="shareinvitation")
    op.drop_constraint(
        "fk_shareinvitation_namespace", "shareinvitation", type_="foreignkey"
    )
    op.drop_column("shareinvitation", "namespace_id")
    # Rows invited to a space cannot survive a column that only names pages.
    op.execute("DELETE FROM shareinvitation WHERE document_id IS NULL")
    op.alter_column(
        "shareinvitation", "document_id", existing_type=sa.Uuid(), nullable=False
    )
