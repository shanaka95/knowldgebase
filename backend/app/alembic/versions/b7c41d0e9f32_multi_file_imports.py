"""imports: several files can become one page

Revision ID: b7c41d0e9f32
Revises: a52063c73216
Create Date: 2026-09-12

An import used to be exactly one file, and most still are - those keep using the
job's own ``object_key`` and have no rows here. Rows appear only when several
uploads are being combined into a single page, where their order matters and
each original has to stay downloadable afterwards.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "b7c41d0e9f32"
down_revision: str | None = "a52063c73216"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "importfile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "filename", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "content_type",
            sqlmodel.sql.sqltypes.AutoString(length=127),
            nullable=False,
        ),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "object_key", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["importjob.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The worker reads a job's parts in order, and nothing ever reads them any
    # other way.
    op.create_index("ix_importfile_job_position", "importfile", ["job_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_importfile_job_position", table_name="importfile")
    op.drop_table("importfile")
