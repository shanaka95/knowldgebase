"""One name per kind per level, like a file manager

Revision ID: e6b3c92d15af
Revises: d8f2a61c4b97
Create Date: 2026-09-15

Two folders called "Invoices" in the same folder were possible, and so were two
pages called "Notes" side by side. Names are now unique among their siblings -
case-insensitively, the way macOS and Windows treat them - while the same name
in two different folders stays perfectly legal.

Spaces already carried ``uq_namespace_owner_name``, so this only adds the two
that were missing. Existing duplicates are renamed rather than refused: the
oldest keeps the name and the rest gain "(2)", "(3)"…

``NULLS NOT DISTINCT`` is what makes this work at the root of a space, where
``parent_id`` and ``folder_id`` are NULL and would otherwise all be considered
different from each other.
"""

from alembic import op

revision: str = "e6b3c92d15af"
down_revision: str | None = "d8f2a61c4b97"
branch_labels: str | None = None
depends_on: str | None = None


# Oldest sibling keeps the name; the others are numbered in creation order.
_DEDUPE = """
    WITH ranked AS (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY {scope}, lower({name_column})
                   ORDER BY created_at, id
               ) AS position
        FROM {table}
    )
    UPDATE {table} AS t
    SET {name_column} = left(t.{name_column}, {limit}) || ' (' || ranked.position || ')'
    FROM ranked
    WHERE t.id = ranked.id AND ranked.position > 1
"""


def upgrade() -> None:
    op.execute(
        _DEDUPE.format(
            table="folder",
            scope="namespace_id, parent_id",
            name_column="name",
            limit=140,
        )
    )
    op.execute(
        _DEDUPE.format(
            table="document",
            scope="namespace_id, folder_id",
            name_column="title",
            limit=290,
        )
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_folder_sibling_name
        ON folder (namespace_id, parent_id, lower(name))
        NULLS NOT DISTINCT
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_document_sibling_title
        ON document (namespace_id, folder_id, lower(title))
        NULLS NOT DISTINCT
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_document_sibling_title")
    op.execute("DROP INDEX IF EXISTS uq_folder_sibling_name")
