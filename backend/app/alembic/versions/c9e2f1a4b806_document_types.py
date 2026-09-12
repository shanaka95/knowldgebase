"""documents carry a type

Revision ID: c9e2f1a4b806
Revises: b7c41d0e9f32
Create Date: 2026-09-12

What kind of thing a page is - a letter, an invoice, a runbook. Free text rather
than an enumeration, because the useful set is different for every person and
nobody should have to request a new category.

Nullable, and left null on existing pages: guessing a type for thousands of
pages would be worse than admitting we do not know.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "c9e2f1a4b806"
down_revision: str | None = "b7c41d0e9f32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "doc_type", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=True
        ),
    )
    # Filtering a space by type is the whole point of having one.
    op.create_index("ix_document_doc_type", "document", ["doc_type"])

    op.add_column(
        "importjob",
        sa.Column(
            "doc_type", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("importjob", "doc_type")
    op.drop_index("ix_document_doc_type", table_name="document")
    op.drop_column("document", "doc_type")
