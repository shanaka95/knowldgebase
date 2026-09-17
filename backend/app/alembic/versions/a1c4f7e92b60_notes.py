"""Personal notes, private to whoever wrote them

Revision ID: a1c4f7e92b60
Revises: c71d0e83a5b6
Create Date: 2026-09-17

Somewhere to put a thought. Not `documentnote`, which is a remark *about a
page* that everyone who can read the page can read; these belong to one person.

The privacy is structural rather than enforced by a rule somewhere. There is no
share table and no role column, so there is nothing to get wrong: the only way
to reach a note is `user_id`, and every query carries it.

`namespace_id` is SET NULL, and the choice matters. CASCADE would let somebody
deleting their own space quietly destroy other people's private notes filed in
it. RESTRICT would be worse: the delete would fail with "3 notes are in here",
which tells an administrator that somebody has notes they cannot see - an
existence oracle, from an action whose blast radius is supposed to be that
space's own pages. SET NULL degrades to "Unfiled", which is a state a person
can be shown.

`search_vector` is generated and persisted, so Postgres writes it at COMMIT.
That is what makes a note findable by keyword the instant it is saved, rather
than when the indexing worker gets to it - the vectors follow seconds later.
Nothing is dropped or rebuilt here: this is a new table, so the generated
column goes in at creation and no existing row is touched.

`max_notes` lands on `user` and `usergroup` as the account override and the
group tier of the limit resolver. Notes are counted separately from pages
because they are a different thing with a different volume - somebody may well
want fifty pages and five thousand notes.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c4f7e92b60"
down_revision: str | None = "c71d0e83a5b6"
branch_labels: str | None = None
depends_on: str | None = None

# Must match app.models.NOTE_SEARCH_VECTOR. A generated column cannot be
# altered in place, so a drift between the two is a table rewrite later.
NOTE_SEARCH_VECTOR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', left(coalesce(content_text, ''), 100000)), 'B')"
)


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("namespace_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False
        ),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column(
            "content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("color", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding_status", sa.String(length=32), nullable=False),
        sa.Column("embedding_version", sa.Integer(), nullable=True),
        sa.Column("embedding_error", sa.Text(), nullable=True),
        sa.Column("embedding_attempts", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(NOTE_SEARCH_VECTOR, persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["namespace_id"], ["namespace.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_user_updated", "note", ["user_id", "updated_at"])
    op.create_index("ix_note_user_archived", "note", ["user_id", "archived_at"])
    op.create_index("ix_note_user_namespace", "note", ["user_id", "namespace_id"])
    op.create_index("ix_note_embedding_status", "note", ["embedding_status"])
    op.create_index(
        "ix_note_search_vector", "note", ["search_vector"], postgresql_using="gin"
    )

    op.create_table(
        "notetag",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column(
            "name_folded", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.Column("color", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name_folded", name="uq_notetag_user_name"),
    )

    op.create_table(
        "notetaglink",
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["note.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["notetag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("note_id", "tag_id"),
    )

    # The account override and the group tier of the limit resolver. NULL at
    # either means "inherit", which is why both are nullable.
    op.add_column("user", sa.Column("max_notes", sa.Integer(), nullable=True))
    op.add_column("usergroup", sa.Column("max_notes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("usergroup", "max_notes")
    op.drop_column("user", "max_notes")
    op.drop_table("notetaglink")
    op.drop_table("notetag")
    op.drop_index("ix_note_search_vector", table_name="note")
    op.drop_index("ix_note_embedding_status", table_name="note")
    op.drop_index("ix_note_user_namespace", table_name="note")
    op.drop_index("ix_note_user_archived", table_name="note")
    op.drop_index("ix_note_user_updated", table_name="note")
    op.drop_table("note")
