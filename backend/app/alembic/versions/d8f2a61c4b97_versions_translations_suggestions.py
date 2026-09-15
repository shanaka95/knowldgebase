"""Document versions, translations, originals and search suggestions

Revision ID: d8f2a61c4b97
Revises: c4e91a7b2d55
Create Date: 2026-09-15

Four things at once, because they share a shape: a page now has a history, a
translation belongs to one version of it, the files it was imported from are
all kept rather than only the first, and the search box has examples drawn from
the reader's own pages.

Existing pages get a version 1 row backfilled from their current content, so
the history is never empty; existing imports get their originals numbered.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "d8f2a61c4b97"
down_revision: str | None = "c4e91a7b2d55"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- the language a page is written in ---------------------------------
    op.add_column(
        "document",
        sa.Column(
            "language", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True
        ),
    )

    # --- every original, in the order it was uploaded ----------------------
    op.add_column(
        "attachment", sa.Column("source_order", sa.Integer(), nullable=True)
    )
    op.add_column(
        "attachment", sa.Column("source_version", sa.Integer(), nullable=True)
    )
    # Pages imported before this migration kept every upload as an attachment
    # but only ever showed the first. Number them by upload time so the rest
    # appear, and point them at version 1, which is what an import produces.
    op.execute(
        """
        UPDATE attachment AS a
        SET source_order = ordered.position - 1,
            source_version = 1
        FROM (
            SELECT att.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY att.document_id ORDER BY att.created_at, att.id
                   ) AS position
            FROM attachment AS att
            JOIN document AS d ON d.id = att.document_id
            WHERE d.source_attachment_id IS NOT NULL
        ) AS ordered
        WHERE a.id = ordered.id
        """
    )

    # --- version history ----------------------------------------------------
    op.create_table(
        "documentversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("doc_type", sqlmodel.sql.sqltypes.AutoString(length=60), nullable=True),
        sa.Column(
            "language", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_documentversion_doc_version"
        ),
    )
    op.create_index(
        "ix_documentversion_document", "documentversion", ["document_id", "version"]
    )
    # A page that existed before this table did still has a history: itself.
    # Recorded at its current version rather than at 1, so the number on screen
    # matches the number the page has been carrying all along.
    op.execute(
        """
        INSERT INTO documentversion (
            id, document_id, version, title, content_html, content_text,
            doc_type, language, created_by, created_at
        )
        SELECT gen_random_uuid(), d.id, d.version, d.title, d.content_html,
               d.content_text, d.doc_type, NULL, d.updated_by,
               COALESCE(d.updated_at, d.created_at, NOW())
        FROM document AS d
        """
    )

    # --- translations, one per page per version per language ----------------
    op.create_table(
        "documenttranslation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("doc_version", sa.Integer(), nullable=False),
        sa.Column("language", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=300), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "doc_version",
            "language",
            name="uq_documenttranslation_doc_version_lang",
        ),
    )
    op.create_index(
        "ix_documenttranslation_document",
        "documenttranslation",
        ["document_id", "doc_version"],
    )

    # --- example searches, drawn from the reader's own pages ----------------
    op.create_table(
        "searchsuggestion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("namespace_id", sa.Uuid(), nullable=True),
        sa.Column("question", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["namespace_id"], ["namespace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "document_id", name="uq_searchsuggestion_user_document"
        ),
    )
    op.create_index(
        "ix_searchsuggestion_user_created", "searchsuggestion", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_searchsuggestion_user_created", table_name="searchsuggestion")
    op.drop_table("searchsuggestion")
    op.drop_index("ix_documenttranslation_document", table_name="documenttranslation")
    op.drop_table("documenttranslation")
    op.drop_index("ix_documentversion_document", table_name="documentversion")
    op.drop_table("documentversion")
    op.drop_column("attachment", "source_version")
    op.drop_column("attachment", "source_order")
    op.drop_column("document", "language")
