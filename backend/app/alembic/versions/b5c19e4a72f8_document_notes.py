"""Notes on a page, indexed with it

Revision ID: b5c19e4a72f8
Revises: a3d6e81f0c24
Create Date: 2026-09-15

A note is what somebody wanted to say about a document that the document does
not say: why it was kept, what it supersedes, that the invoice was already
disputed. It has an author and a time, so it is its own row rather than text
appended to the page - a scan should still read as the scan.

But a note nobody can find by searching for it is a note nobody will read
again, so the page's search vector has to cover it. A Postgres generated
column may only reference its own row, which is why `document.notes_text`
exists: a denormalised copy of every note on the page, maintained by
`app/services/notes.py` and nowhere else.

The generated column is therefore **dropped and recreated**, which is the only
way to change a `GENERATED ALWAYS` expression in Postgres. That rewrites the
tsvector for every row and rebuilds the GIN index on it - so on a large
installation this migration is not instant, and it takes an ACCESS EXCLUSIVE
lock on `document` while it runs. It is one statement on a table whose row
count is bounded by what people have actually written, so this is accepted
rather than worked around.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b5c19e4a72f8"
down_revision: str | None = "a3d6e81f0c24"
branch_labels: str | None = None
depends_on: str | None = None

# Must match app.models.Document.search_vector.
WITH_NOTES = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', left(coalesce(content_text, ''), 500000)), 'B') || "
    "setweight(to_tsvector('english', left(coalesce(notes_text, ''), 100000)), 'B')"
)
WITHOUT_NOTES = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', left(coalesce(content_text, ''), 500000)), 'B')"
)


def _replace_search_vector(expression: str) -> None:
    """Swap the generated column's expression.

    Dropping it takes its index with it, so the index is recreated too. Named
    exactly as the model declares it, or autogenerate would propose adding it
    back on the next revision.
    """
    op.drop_column("document", "search_vector")
    op.add_column(
        "document",
        sa.Column(
            "search_vector",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed(expression, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_search_vector",
        "document",
        ["search_vector"],
        postgresql_using="gin",
    )


def upgrade() -> None:
    op.create_table(
        "documentnote",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        # Kept when the account goes: the note is part of the page's history,
        # and deleting somebody should not silently edit what a page says.
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_documentnote_document_created",
        "documentnote",
        ["document_id", "created_at"],
    )

    op.add_column(
        "document",
        sa.Column("notes_text", sa.Text(), nullable=False, server_default=""),
    )
    _replace_search_vector(WITH_NOTES)

    # What the uploader wanted to say about the file, carried to the page the
    # import creates and kept as its first note.
    op.add_column("importjob", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("importjob", "note")
    _replace_search_vector(WITHOUT_NOTES)
    op.drop_column("document", "notes_text")
    op.drop_index("ix_documentnote_document_created", table_name="documentnote")
    op.drop_table("documentnote")
