"""Bill dictation by the second

One column. Speech to text is priced per second of audio rather than per token
or per call, so it is the first kind of work `usagedaily` cannot express - and
the credit balance reads straight out of that table, which means the column has
to exist before the first recording rather than being derived later.

Backfills to 0, which is the true answer for every row written before there was
anything to dictate into.

Revision ID: c3e6b90d5a18
Revises: a74cac4ef220
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3e6b90d5a18"
down_revision = "a74cac4ef220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usagedaily",
        sa.Column(
            "audio_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    # The default was only ever for the backfill: every insert names the column.
    op.alter_column("usagedaily", "audio_seconds", server_default=None)


def downgrade() -> None:
    op.drop_column("usagedaily", "audio_seconds")
