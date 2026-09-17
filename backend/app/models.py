import re
import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any

from pydantic import EmailStr, field_validator
from sqlalchemy import (
    BigInteger,
    Column,
    Computed,
    Date,
    DateTime,
    Index,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def _tz_datetime(**kwargs: Any) -> Any:
    return Field(sa_type=DateTime(timezone=True), **kwargs)  # type: ignore


# ---------------------------------------------------------------------------
# Enums (stored as VARCHAR(32) to keep migrations simple)
# ---------------------------------------------------------------------------


class NamespaceRole(StrEnum):
    viewer = "viewer"
    editor = "editor"
    admin = "admin"


class ShareRole(StrEnum):
    viewer = "viewer"
    editor = "editor"


class ContentFormat(StrEnum):
    html = "html"
    markdown = "markdown"
    text = "text"


class EmbeddingStatus(StrEnum):
    pending = "pending"
    chunking = "chunking"
    summarizing = "summarizing"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    superseded = "superseded"


class JobStage(StrEnum):
    claimed = "claimed"
    loading = "loading"
    chunking = "chunking"
    summarizing = "summarizing"
    embedding = "embedding"
    writing = "writing"
    done = "done"


class ChunkingMethod(StrEnum):
    none_short = "none_short"
    llm_single_topic = "llm_single_topic"
    llm = "llm"
    llm_windowed = "llm_windowed"
    fallback_headings = "fallback_headings"
    fallback_paragraphs = "fallback_paragraphs"


class EmbeddingKind(StrEnum):
    document = "document"
    summary = "summary"
    chunk = "chunk"


class AuthCodePurpose(StrEnum):
    """What a one-time secret is for. One table, three very different lifetimes."""

    verify_email = "verify_email"
    two_factor = "two_factor"
    password_reset = "password_reset"


class ApiKeyScope(StrEnum):
    read = "read"
    write = "write"


class ImportStatus(StrEnum):
    queued = "queued"
    rendering = "rendering"
    parsing = "parsing"
    creating = "creating"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class ImportParser(StrEnum):
    mineru = "mineru"
    llm = "llm"


class CleanupKind(StrEnum):
    qdrant_document = "qdrant_document"
    minio_object = "minio_object"
    # One note's points. Enqueued on a real delete, never on an archive: an
    # archived note has to stay findable.
    qdrant_note = "qdrant_note"
    # Everything a departing account left behind. `Note.user_id` is CASCADE, so
    # the rows go with the account and there is nothing left to walk - which is
    # exactly why the vectors have to be swept by owner instead.
    qdrant_notes_of_owner = "qdrant_notes_of_owner"


ROLE_RANK: dict[str, int] = {
    NamespaceRole.viewer: 1,
    NamespaceRole.editor: 2,
    NamespaceRole.admin: 3,
}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    # Sent as null to clear an override and go back to inheriting. `crud
    # .update_user` uses `exclude_unset=True`, so "absent" and "null" stay
    # different things: leave alone, versus reset to inherit.
    max_pages: int | None = Field(default=None, ge=0, le=1_000_000)
    max_notes: int | None = Field(default=None, ge=0, le=1_000_000)
    max_shares_per_document: int | None = Field(default=None, ge=0, le=10_000)
    max_members_per_space: int | None = Field(default=None, ge=0, le=10_000)
    monthly_credits: int | None = Field(default=None, ge=0, le=10_000_000)
    group_id: uuid.UUID | None = Field(default=None)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    # Until this is set the account exists but cannot sign in. It is the only
    # evidence that whoever registered controls the address.
    email_verified_at: datetime | None = _tz_datetime(default=None)
    # Stamped into every access token. Raising it invalidates every token issued
    # before now, which is what makes "sign out everywhere" real after a
    # password change rather than a hopeful message in the interface.
    session_epoch: int = Field(default=0)
    # Set while an account is refusing password attempts after too many failures.
    locked_until: datetime | None = _tz_datetime(default=None)
    failed_logins: int = Field(default=0)
    last_failed_login_at: datetime | None = _tz_datetime(default=None)
    # Which group's settings apply to this account. NULL means the default
    # group - deliberately, because users are created in four places and one of
    # them builds ``User(...)`` by hand. Making "no group" mean "the defaults"
    # is what stops any of those paths producing an account outside the system.
    group_id: uuid.UUID | None = Field(
        default=None, foreign_key="usergroup.id", ondelete="SET NULL", index=True
    )

    # Per-account overrides. NULL on any of these means "inherit" - from the
    # group, then from the default group, then from the built-in constant. They
    # are never served raw: `serializers.to_user_public` emits the *resolved*
    # number, so a reader sees a figure and never where it came from.
    #
    # Zero is a real answer here ("this account may not create pages"), so every
    # test is `is not None`, never truthiness.
    max_pages: int | None = Field(default=None)
    # Notes are counted apart from pages: different thing, different volume.
    # Somebody may well want fifty pages and five thousand notes.
    max_notes: int | None = Field(default=None)
    # How many people one of this account's pages may be shared with, counting
    # invitations that have not been accepted yet.
    max_shares_per_document: int | None = Field(default=None)
    # The same idea for a whole space. Separate from the per-page limit because
    # they are different decisions: a space is a bigger thing to hand over.
    max_members_per_space: int | None = Field(default=None)
    # Model work per calendar month, in credits. See app/services/credits.py.
    monthly_credits: int | None = Field(default=None)

    namespaces: list[Namespace] = Relationship(
        back_populates="owner", cascade_delete=True
    )
    api_keys: list[ApiKey] = Relationship(back_populates="user", cascade_delete=True)


class UserPublic(UserBase):
    """An account as its owner sees it.

    The limits here are **resolved** values, not the columns: whether a number
    came from this account, its group or the defaults is not representable in
    this shape, which is what keeps groups invisible to the people in them.
    Build it with `serializers.to_user_public`, never `model_validate`.
    """

    id: uuid.UUID
    created_at: datetime | None = None
    email_verified_at: datetime | None = None
    max_pages: int = 100
    pages_used: int = 0
    max_notes: int = 1000
    notes_used: int = 0
    max_shares_per_document: int = 50
    max_members_per_space: int = 50
    monthly_credits: int = 1000


# ---------------------------------------------------------------------------
# Account groups and limits (administrators only)
# ---------------------------------------------------------------------------
#
# A group is an administrative device for giving a class of people the same
# settings. People in one are never told so: nothing below appears on any
# schema a non-administrator can fetch, and `UserPublic` above carries resolved
# numbers with no trace of where they came from. Keep it that way - the failure
# mode to guard against is somebody making `UserPublic` inherit from a shape
# that grows a group field later.


class UserGroup(SQLModel, table=True):
    """Settings shared by a class of accounts.

    Every limit is nullable, and NULL means "inherit". A group that sets
    nothing falls through to the default group, which is the floor for
    everyone rather than only for the unassigned - so raising a number on the
    default group lifts exactly the people who were never given one.
    """

    __table_args__ = (
        # At most one row may claim to be the default. This cannot enforce *at
        # least* one, which is why `quota.ensure_default_group` re-seeds it at
        # every boot rather than trusting the row to still be there.
        Index(
            "uq_usergroup_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # A stable handle the code can name. The default group's is reserved, so
    # resolution never has to scan for a boolean.
    slug: str = Field(unique=True, index=True, max_length=120)
    name: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = Field(default=False)
    # Refuses deletion. The default group is part of how limits resolve, not
    # content somebody happens to have made.
    is_system: bool = Field(default=False)

    max_pages: int | None = Field(default=None)
    max_notes: int | None = Field(default=None)
    max_shares_per_document: int | None = Field(default=None)
    max_members_per_space: int | None = Field(default=None)
    monthly_credits: int | None = Field(default=None)

    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class UserGroupCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    max_pages: int | None = Field(default=None, ge=0, le=1_000_000)
    max_notes: int | None = Field(default=None, ge=0, le=1_000_000)
    max_shares_per_document: int | None = Field(default=None, ge=0, le=10_000)
    max_members_per_space: int | None = Field(default=None, ge=0, le=10_000)
    monthly_credits: int | None = Field(default=None, ge=0, le=10_000_000)


class UserGroupUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    max_pages: int | None = Field(default=None, ge=0, le=1_000_000)
    max_notes: int | None = Field(default=None, ge=0, le=1_000_000)
    max_shares_per_document: int | None = Field(default=None, ge=0, le=10_000)
    max_members_per_space: int | None = Field(default=None, ge=0, le=10_000)
    monthly_credits: int | None = Field(default=None, ge=0, le=10_000_000)


class UserGroupPublic(SQLModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    is_default: bool = False
    is_system: bool = False
    member_count: int = 0
    # What this group sets. None means it inherits from the defaults; the
    # resolved figure a member would actually get is `effective_*`.
    max_pages: int | None = None
    max_notes: int | None = None
    max_shares_per_document: int | None = None
    max_members_per_space: int | None = None
    monthly_credits: int | None = None
    effective_max_pages: int = 0
    effective_max_notes: int = 0
    effective_max_shares_per_document: int = 0
    effective_max_members_per_space: int = 0
    effective_monthly_credits: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserGroupsPublic(SQLModel):
    data: list[UserGroupPublic]
    count: int


class GroupRef(SQLModel):
    id: uuid.UUID
    name: str
    is_default: bool = False


class ResolvedLimit(SQLModel):
    """One limit, and the whole chain that produced it.

    The admin screen has to be able to answer "why is this 250?" without a
    second request, so the tier in force and the values it beat travel together.
    """

    key: str
    label: str
    value: int
    # "user", "group", "default_group" or "system"
    source: str
    source_label: str | None = None
    override: int | None = None
    group_value: int | None = None
    default_value: int = 0


class AdminUserPublic(UserBase):
    """An account as an administrator sees it.

    Field-compatible with `UserPublic` on purpose, so the components typed
    against that keep working when the table is fed from here.
    """

    id: uuid.UUID
    created_at: datetime | None = None
    email_verified_at: datetime | None = None
    max_pages: int = 100
    pages_used: int = 0
    max_notes: int = 1000
    notes_used: int = 0
    max_shares_per_document: int = 50
    max_members_per_space: int = 50
    monthly_credits: int = 1000
    group: GroupRef | None = None
    limits: list[ResolvedLimit] = []
    # This month's credit position, so the table can show it without a request
    # per row. `credits_total` is the allowance plus any live grants.
    credits_total: float = 0
    credits_used: float = 0
    credits_remaining: float = 0


class AdminUsersPublic(SQLModel):
    data: list[AdminUserPublic]
    count: int


class UserAssignment(SQLModel):
    """Where an account sits, and what it overrides.

    `overrides` is a complete map, not a patch: a key that is absent is an
    override that is not set. That turns "blank means inherit" into what an
    empty form field naturally produces, instead of a three-way distinction
    between absent, null and a number.
    """

    group_id: uuid.UUID | None = None
    overrides: dict[str, int] = {}


class GroupMembers(SQLModel):
    """Accounts to move into a group. Assignment is exclusive - one group each."""

    user_ids: list[uuid.UUID] = []


class LimitDefinition(SQLModel):
    """One administrable setting, described well enough to draw a form from."""

    key: str
    label: str
    description: str
    default: int
    minimum: int = 0
    maximum: int = 1_000_000
    unit: str = ""


class LimitDefinitionsPublic(SQLModel):
    data: list[LimitDefinition]


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class UserRef(SQLModel):
    """Compact user reference embedded in other resources."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None


# ---------------------------------------------------------------------------
# Namespaces (spaces)
# ---------------------------------------------------------------------------


class NamespaceBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    icon: str = Field(default="folder", max_length=40)
    color: str = Field(default="indigo", max_length=20)


class NamespaceCreate(NamespaceBase):
    pass


class NamespaceUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class Namespace(NamespaceBase, table=True):
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_namespace_owner_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=120)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    owner: User | None = Relationship(back_populates="namespaces")
    members: list[NamespaceMember] = Relationship(
        back_populates="namespace", cascade_delete=True
    )
    folders: list[Folder] = Relationship(
        back_populates="namespace", cascade_delete=True
    )
    documents: list[Document] = Relationship(
        back_populates="namespace", cascade_delete=True
    )
    attachments: list[Attachment] = Relationship(
        back_populates="namespace", cascade_delete=True
    )


class NamespacePublic(NamespaceBase):
    id: uuid.UUID
    slug: str
    owner_id: uuid.UUID
    owner: UserRef | None = None
    my_role: NamespaceRole | None = None
    # True when this space belongs to somebody else and was shared with you.
    # Derived here so the interface does not have to know who you are to say so.
    shared_with_you: bool = False
    document_count: int = 0
    # None when the caller only holds shares on individual pages: they are
    # not a member, so the size of the membership is not theirs to know.
    member_count: int | None = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NamespacesPublic(SQLModel):
    data: list[NamespacePublic]
    count: int


class NamespaceMemberBase(SQLModel):
    role: NamespaceRole = NamespaceRole.viewer


class NamespaceMemberCreate(NamespaceMemberBase):
    email: EmailStr


class NamespaceMemberUpdate(SQLModel):
    role: NamespaceRole


class NamespaceMember(NamespaceMemberBase, table=True):
    __table_args__ = (
        UniqueConstraint("namespace_id", "user_id", name="uq_namespace_member"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    namespace_id: uuid.UUID = Field(
        foreign_key="namespace.id", nullable=False, ondelete="CASCADE", index=True
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    role: NamespaceRole = Field(
        default=NamespaceRole.viewer,
        sa_type=String(32),  # type: ignore
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    namespace: Namespace | None = Relationship(back_populates="members")


class NamespaceMemberPublic(SQLModel):
    id: uuid.UUID
    namespace_id: uuid.UUID
    user: UserRef
    role: NamespaceRole
    is_owner: bool = False
    created_at: datetime | None = None


class NamespaceMembersPublic(SQLModel):
    data: list[NamespaceMemberPublic]
    count: int


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


class FolderBase(SQLModel):
    name: str = Field(min_length=1, max_length=200)


class FolderCreate(FolderBase):
    namespace_id: uuid.UUID
    parent_id: uuid.UUID | None = None


class FolderUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    # explicit flag so `parent_id: null` can mean "move to root"
    move_to_root: bool = False


class Folder(FolderBase, table=True):
    __table_args__ = (Index("ix_folder_namespace_parent", "namespace_id", "parent_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    namespace_id: uuid.UUID = Field(
        foreign_key="namespace.id", nullable=False, ondelete="CASCADE"
    )
    parent_id: uuid.UUID | None = Field(
        default=None, foreign_key="folder.id", ondelete="CASCADE"
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    namespace: Namespace | None = Relationship(back_populates="folders")
    documents: list[Document] = Relationship(back_populates="folder")


class FolderPublic(FolderBase):
    id: uuid.UUID
    namespace_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FoldersPublic(SQLModel):
    data: list[FolderPublic]
    count: int


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


# Offered in the interface as a starting point. Not a closed set: a type is
# whatever the person filing the page calls it, and a knowledge base that
# refuses "Tax assessment" because it was not on a list is a worse one.
COMMON_DOCUMENT_TYPES: tuple[str, ...] = (
    "Document",
    "Letter",
    "Email",
    "Note",
    "Report",
    "Contract",
    "Invoice",
    "Receipt",
    "Statement",
    "Policy",
    "Guide",
    "Meeting notes",
    "Specification",
    "Form",
    "Certificate",
)

DOCUMENT_TYPE_MAX = 60

# Long enough for a paragraph of context, short enough that a note stays a
# note: anything longer belongs in the page itself.
NOTE_MAX = 4000


def clean_document_type(value: str | None) -> str | None:
    """Normalise a type so the same thing is not stored three ways.

    Whitespace collapsed and the first letter capitalised, so "  invoice " and
    "Invoice" end up as one entry in the list people pick from. The rest of the
    casing is left alone: "PDF export" and "VAT return" should not become "Pdf
    export" and "Vat return".
    """
    text = " ".join((value or "").split())[:DOCUMENT_TYPE_MAX]
    if not text:
        return None
    return text[0].upper() + text[1:]


class DocumentCreate(SQLModel):
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    content_format: ContentFormat = ContentFormat.html
    doc_type: str | None = Field(default=None, max_length=DOCUMENT_TYPE_MAX)
    # Something to say about the page that is not the page. Accepted here so an
    # agent writing through the API can leave it in one call rather than two.
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class DocumentUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = None
    content_format: ContentFormat = ContentFormat.html
    # Sent as an empty string to clear it; left out entirely to leave it alone.
    doc_type: str | None = Field(default=None, max_length=DOCUMENT_TYPE_MAX)
    # optimistic locking: reject the update if the stored version differs
    expected_version: int | None = None


class DocumentMove(SQLModel):
    namespace_id: uuid.UUID | None = None
    folder_id: uuid.UUID | None = None


class Document(SQLModel, table=True):
    __table_args__ = (
        Index("ix_document_namespace_folder", "namespace_id", "folder_id"),
        Index("ix_document_embedding_status", "embedding_status"),
        Index("ix_document_updated_at", "updated_at"),
        Index("ix_document_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    namespace_id: uuid.UUID = Field(
        foreign_key="namespace.id", nullable=False, ondelete="CASCADE"
    )
    folder_id: uuid.UUID | None = Field(
        default=None, foreign_key="folder.id", ondelete="CASCADE"
    )
    title: str = Field(min_length=1, max_length=300)
    # What kind of thing this is - a letter, an invoice, a runbook. Free text
    # with suggestions rather than an enum, so nobody has to file a request to
    # add a category.
    doc_type: str | None = Field(default=None, max_length=DOCUMENT_TYPE_MAX, index=True)
    # Set while the page is readable by anyone holding its link. A random slug
    # rather than the page id, so that turning sharing off and on again breaks
    # the old link instead of silently re-publishing to whoever kept it.
    public_slug: str | None = Field(
        default=None, unique=True, index=True, max_length=32
    )
    public_shared_at: datetime | None = _tz_datetime(default=None)
    public_shared_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    content_html: str = Field(default="", sa_type=Text)
    content_text: str = Field(default="", sa_type=Text)
    # Every note anybody has added to this page, run together. Denormalised
    # from `documentnote` so the generated search vector can read it: a
    # generated column may only reference its own row, and a note nobody can
    # find by searching for it is a note nobody will read again.
    notes_text: str = Field(default="", sa_type=Text)
    summary: str | None = Field(default=None, sa_type=Text)
    # What language the page is written in, detected when its text changes.
    # Stored rather than detected on the way out: the translation picker needs
    # it on every page load, and the answer never changes between edits.
    language: str | None = Field(default=None, max_length=8)
    version: int = 1
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    updated_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    # embedding pipeline state (denormalized for fast listing)
    embedding_status: EmbeddingStatus = Field(
        default=EmbeddingStatus.pending,
        sa_type=String(32),  # type: ignore
    )
    embedding_version: int | None = None
    embedding_error: str | None = Field(default=None, sa_type=Text)
    embedding_attempts: int = 0
    chunk_count: int = 0
    chunking_method: str | None = Field(default=None, max_length=32)
    embedding_updated_at: datetime | None = _tz_datetime(default=None)

    # Set when the page was created by importing a PDF or image: the original
    # upload is kept as an attachment so it can be opened at any time.
    source_attachment_id: uuid.UUID | None = Field(
        default=None, foreign_key="attachment.id", ondelete="SET NULL"
    )

    search_vector: Any = Field(
        default=None,
        sa_column=Column(
            TSVECTOR,
            Computed(
                "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('english', left(coalesce(content_text, ''), 500000)), 'B') || "
                "setweight(to_tsvector('english', left(coalesce(notes_text, ''), 100000)), 'B')",
                persisted=True,
            ),
            nullable=True,
        ),
    )

    namespace: Namespace | None = Relationship(back_populates="documents")
    folder: Folder | None = Relationship(back_populates="documents")
    shares: list[DocumentShare] = Relationship(
        back_populates="document", cascade_delete=True
    )
    chunks: list[DocumentChunk] = Relationship(
        back_populates="document", cascade_delete=True
    )
    jobs: list[EmbeddingJob] = Relationship(
        back_populates="document", cascade_delete=True
    )


class DocumentSummaryPublic(SQLModel):
    """Document metadata without content (lists, trees, search)."""

    id: uuid.UUID
    namespace_id: uuid.UUID
    namespace_slug: str | None = None
    # The space this page lives in, by name. A page shared on its own shows the
    # space it came from without granting any access to it.
    namespace_name: str | None = None
    folder_id: uuid.UUID | None = None
    title: str
    doc_type: str | None = None
    # Present only while the page is shared by link, so the interface can show
    # that it is public without a second request.
    public_slug: str | None = None
    version: int
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    embedding_status: EmbeddingStatus
    embedding_version: int | None = None
    embedding_error: str | None = None
    embedding_attempts: int = 0
    chunk_count: int = 0
    chunking_method: str | None = None
    embedding_updated_at: datetime | None = None
    is_stale: bool = False
    my_role: ShareRole | None = None
    source_attachment_id: uuid.UUID | None = None
    note_count: int = 0


class DocumentPublic(DocumentSummaryPublic):
    content_html: str
    content_text: str
    summary: str | None = None
    # The language the page is written in, so the translation picker opens on
    # the right entry without asking.
    language: str | None = None
    updated_by_user: UserRef | None = None
    created_by_user: UserRef | None = None
    # The first original, kept for callers written before a page could have
    # several. New code should read `source_attachments`.
    source_attachment: AttachmentPublic | None = None
    # Every file the page was imported from, in the order they were uploaded.
    source_attachments: list[AttachmentPublic] = []


class DocumentsPublic(SQLModel):
    data: list[DocumentSummaryPublic]
    count: int


class DocumentTypeCount(SQLModel):
    name: str
    # How many of your own pages already carry it. Zero for a suggestion nobody
    # has used yet, which is how the interface sorts the familiar to the top.
    count: int = 0


class DocumentTypesPublic(SQLModel):
    data: list[DocumentTypeCount]
    count: int


class NamespaceTree(SQLModel):
    namespace: NamespacePublic
    folders: list[FolderPublic]
    documents: list[DocumentSummaryPublic]


class SharedWithMe(SQLModel):
    """What other people have given this account access to.

    Two different things, kept apart on purpose. A *space* shared with you
    covers everything in it, now and later. A *page* shared with you is one
    page, and the space around it stays invisible. Anyone deciding what they can
    safely edit needs to know which of the two they are looking at.
    """

    namespaces: list[NamespacePublic]
    documents: list[DocumentSummaryPublic]


# ---------------------------------------------------------------------------
# Document shares
# ---------------------------------------------------------------------------


class DocumentShareCreate(SQLModel):
    email: EmailStr
    role: ShareRole = ShareRole.viewer


class DocumentShareUpdate(SQLModel):
    role: ShareRole


class ShareInvitation(SQLModel, table=True):
    """A page shared with an address that has no account yet.

    Sharing should not depend on whether the other person has signed up already.
    An invitation records the intent; it turns into a real share the moment that
    address is *confirmed* on an account, which is the first point at which we
    know the person reading the email is the person who owns it.

    The token in the emailed link is stored only as a hash, like every other
    one-time secret here, and it grants nothing on its own: it identifies which
    page to open afterwards, while access comes from confirming the address.
    """

    __table_args__ = (
        Index("ix_shareinvitation_email", "email"),
        Index("ix_shareinvitation_document", "document_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Exactly one of these is set. A page and a space are different grants but
    # the same promise, and giving them one redemption path means an address
    # confirmed once collects everything waiting for it.
    document_id: uuid.UUID | None = Field(
        default=None, foreign_key="document.id", ondelete="CASCADE", index=True
    )
    namespace_id: uuid.UUID | None = Field(
        default=None, foreign_key="namespace.id", ondelete="CASCADE", index=True
    )
    # Stored lowercased: addresses are matched, not displayed, and a person who
    # was invited as "Sam@Example.com" signs up as "sam@example.com".
    email: str = Field(max_length=255)
    # A page invitation carries a ShareRole (viewer/editor); a space invitation
    # carries a NamespaceRole (viewer/editor/admin). Stored as text, read back
    # according to which id is set.
    role: str = Field(default="viewer", sa_type=String(32))  # type: ignore
    invited_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    token_hash: str = Field(index=True, max_length=64)
    expires_at: datetime = _tz_datetime(nullable=False)
    accepted_at: datetime | None = _tz_datetime(default=None)
    accepted_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class ShareInvitationPublic(SQLModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    created_at: datetime | None = None
    # "page" or "space", so one list can show both without guessing.
    target: str = "page"


class InvitationPreview(SQLModel):
    """What the landing page shows somebody who followed an invitation link.

    Deliberately thin. Whoever holds the link already knows what they were sent;
    they should not learn anything else about the account that sent it.
    """

    email: str
    # "page" or "space".
    target: str = "page"
    document_id: uuid.UUID | None = None
    namespace_id: uuid.UUID | None = None
    # The page's title, or the space's name.
    document_title: str
    shared_by: str  # a name, or the address if no name was set
    role: str
    expires_at: datetime
    already_accepted: bool = False


class ShareSkipped(SQLModel):
    email: str
    reason: str


class SpaceShareEmails(SQLModel):
    """Share a whole space with several addresses at once.

    The same shape as sharing a page, deliberately: the two are the same act at
    different scales, and an interface that treats them differently makes people
    learn two things instead of one.
    """

    emails: list[EmailStr] = Field(min_length=1, max_length=50)
    role: NamespaceRole = NamespaceRole.viewer
    message: str | None = Field(default=None, max_length=1000)


class SpaceShareResult(SQLModel):
    shared: list[NamespaceMemberPublic] = []
    invited: list[ShareInvitationPublic] = []
    skipped: list[ShareSkipped] = []
    members: int = 0
    max_members: int = 0


class ShareEmails(SQLModel):
    """Share one page with several addresses at once.

    Batched because the interface asks for several and has to report back which
    were known and which will be invited - which it cannot do one call at a time
    without inventing its own error handling.
    """

    emails: list[EmailStr] = Field(min_length=1, max_length=50)
    role: ShareRole = ShareRole.viewer
    # Goes into the email, in the sharer's own words. Optional, and plain text:
    # it is quoted into a message sent on their behalf, so it must not be able
    # to carry markup into somebody else's mail client.
    message: str | None = Field(default=None, max_length=1000)


class ShareResult(SQLModel):
    shared: list[DocumentSharePublic] = []
    invited: list[ShareInvitationPublic] = []
    skipped: list[ShareSkipped] = []
    # Where this page stands against the owner's limit, so the interface can
    # show it before someone runs into it.
    recipients: int = 0
    max_recipients: int = 0


class PublicDocument(SQLModel):
    """A page as it looks to somebody who only has the link.

    Nothing here identifies anything else in the knowledge base. No folder, no
    space id, no author id, no version history - because the link was shared,
    not the account behind it.
    """

    id: uuid.UUID
    slug: str
    title: str
    doc_type: str | None = None
    content_html: str
    updated_at: datetime | None = None
    shared_by: str | None = None


class PublicLink(SQLModel):
    slug: str
    url: str
    shared_at: datetime | None = None


class UserLookup(SQLModel):
    """Whether one exact address has an account here.

    Exact matches only, never prefixes: the interface wants to confirm the
    address someone typed, and a prefix search would turn this into a way to
    read the user list.
    """

    email: str
    exists: bool
    user: UserRef | None = None


class DocumentClone(SQLModel):
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)


class DocumentShare(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_document_share"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE", index=True
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    role: ShareRole = Field(default=ShareRole.viewer, sa_type=String(32))  # type: ignore
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    document: Document | None = Relationship(back_populates="shares")


class DocumentSharePublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user: UserRef
    role: ShareRole
    created_at: datetime | None = None


class DocumentSharesPublic(SQLModel):
    data: list[DocumentSharePublic]
    count: int


# ---------------------------------------------------------------------------
# Chunks + embedding jobs
# ---------------------------------------------------------------------------


class DocumentChunk(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "document_id", "doc_version", "chunk_index", name="uq_document_chunk"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE", index=True
    )
    doc_version: int
    chunk_index: int
    title: str = Field(default="", max_length=300)
    text: str = Field(sa_type=Text)
    char_count: int = 0
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    document: Document | None = Relationship(back_populates="chunks")


class DocumentChunkPublic(SQLModel):
    chunk_index: int
    title: str
    text: str
    char_count: int
    doc_version: int


class EmbeddingJob(SQLModel, table=True):
    __table_args__ = (
        Index("ix_embeddingjob_status_run_after", "status", "run_after"),
        Index("ix_embeddingjob_document_created", "document_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE"
    )
    doc_version: int
    status: JobStatus = Field(default=JobStatus.queued, sa_type=String(32))  # type: ignore
    stage: JobStage | None = Field(default=None, sa_type=String(32))  # type: ignore
    progress: int = 0
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime = _tz_datetime(default_factory=get_datetime_utc)
    cancel_requested: bool = False
    locked_by: str | None = Field(default=None, max_length=200)
    locked_at: datetime | None = _tz_datetime(default=None)
    heartbeat_at: datetime | None = _tz_datetime(default=None)
    started_at: datetime | None = _tz_datetime(default=None)
    finished_at: datetime | None = _tz_datetime(default=None)
    error: str | None = Field(default=None, sa_type=Text)
    chunking_method: str | None = Field(default=None, max_length=32)
    chunk_count: int | None = None
    stats: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    document: Document | None = Relationship(back_populates="jobs")


class EmbeddingJobPublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    doc_version: int
    status: JobStatus
    stage: JobStage | None = None
    progress: int = 0
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime
    cancel_requested: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    chunking_method: str | None = None
    chunk_count: int | None = None
    stats: dict[str, Any] | None = None
    created_at: datetime | None = None


class DocumentEmbeddingsPublic(SQLModel):
    document_id: uuid.UUID
    version: int
    embedding_version: int | None = None
    is_stale: bool
    embedding_status: EmbeddingStatus
    embedding_error: str | None = None
    embedding_attempts: int = 0
    chunk_count: int = 0
    chunking_method: str | None = None
    embedding_updated_at: datetime | None = None
    summary: str | None = None
    current_job: EmbeddingJobPublic | None = None
    jobs: list[EmbeddingJobPublic] = []
    chunks: list[DocumentChunkPublic] = []
    kinds: list[str] = [
        EmbeddingKind.document,
        EmbeddingKind.summary,
        EmbeddingKind.chunk,
    ]


class EmbeddingSummary(SQLModel):
    """Counts of accessible documents by embedding state (dashboard)."""

    total: int = 0
    pending: int = 0
    in_progress: int = 0
    ready: int = 0
    stale: int = 0
    failed: int = 0
    queued_jobs: int = 0
    running_jobs: int = 0


class WorkerHeartbeat(SQLModel, table=True):
    name: str = Field(primary_key=True, max_length=200)
    hostname: str = Field(max_length=200)
    pid: int
    started_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    heartbeat_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    concurrency: int = 1
    running_jobs: int = 0


class WorkerPublic(SQLModel):
    name: str
    hostname: str
    pid: int
    started_at: datetime
    heartbeat_at: datetime
    concurrency: int
    running_jobs: int
    online: bool


class WorkersPublic(SQLModel):
    workers: list[WorkerPublic]
    any_online: bool
    queued_jobs: int
    running_jobs: int


class CleanupTask(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: CleanupKind = Field(sa_type=String(32))  # type: ignore
    payload: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)
    attempts: int = 0
    run_after: datetime = _tz_datetime(default_factory=get_datetime_utc)
    error: str | None = Field(default=None, sa_type=Text)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


class Attachment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    namespace_id: uuid.UUID = Field(
        foreign_key="namespace.id", nullable=False, ondelete="CASCADE", index=True
    )
    document_id: uuid.UUID | None = Field(
        default=None, foreign_key="document.id", ondelete="SET NULL", index=True
    )
    uploader_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=127)
    size: int = Field(sa_type=BigInteger)
    object_key: str = Field(unique=True, max_length=512)
    # Set on the files a page was imported from, numbered in the order they
    # were uploaded - which is the order they read in. Null on everything else,
    # above all the images pasted into the editor, which are not originals and
    # must not be offered as them.
    source_order: int | None = Field(default=None)
    # The page version this file produced. An import creates version 1, and
    # later edits move the page on without changing what was uploaded, so this
    # is what lets the page say which version the original corresponds to.
    source_version: int | None = Field(default=None)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    namespace: Namespace | None = Relationship(back_populates="attachments")


class AttachmentPublic(SQLModel):
    id: uuid.UUID
    namespace_id: uuid.UUID
    document_id: uuid.UUID | None = None
    uploader_id: uuid.UUID | None = None
    filename: str
    content_type: str
    size: int
    download_url: str
    source_order: int | None = None
    source_version: int | None = None
    created_at: datetime | None = None


class AttachmentsPublic(SQLModel):
    data: list[AttachmentPublic]
    count: int


# ---------------------------------------------------------------------------
# Document imports (PDF / image -> document)
# ---------------------------------------------------------------------------


class ImportJobCreate(SQLModel):
    """Form fields accepted alongside the uploaded file."""

    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=300)
    prompt: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class ImportFile(SQLModel, table=True):
    """One uploaded file belonging to an import.

    An import used to be one file, and most still are - those keep using the
    job's own ``object_key`` and have no rows here. Rows appear when several
    files are being combined into a single page, where order matters and each
    original has to stay downloadable afterwards.
    """

    __table_args__ = (Index("ix_importfile_job_position", "job_id", "position"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(
        foreign_key="importjob.id", nullable=False, ondelete="CASCADE"
    )
    # The order the person chose, which is the order they read in.
    position: int = Field(default=0)
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=127)
    size: int = Field(default=0, sa_type=BigInteger)
    object_key: str = Field(max_length=512)


class ImportJob(SQLModel, table=True):
    __table_args__ = (
        Index("ix_importjob_status_created", "status", "created_at"),
        Index("ix_importjob_namespace", "namespace_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    namespace_id: uuid.UUID = Field(
        foreign_key="namespace.id", nullable=False, ondelete="CASCADE"
    )
    folder_id: uuid.UUID | None = Field(
        default=None, foreign_key="folder.id", ondelete="SET NULL"
    )
    document_id: uuid.UUID | None = Field(
        default=None, foreign_key="document.id", ondelete="SET NULL"
    )
    attachment_id: uuid.UUID | None = Field(
        default=None, foreign_key="attachment.id", ondelete="SET NULL"
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )

    title: str | None = Field(default=None, max_length=300)
    # One type for everything in this upload: someone filing a batch of scans is
    # filing one kind of thing.
    doc_type: str | None = Field(default=None, max_length=DOCUMENT_TYPE_MAX)
    prompt: str | None = Field(default=None, sa_type=Text)
    # What the person uploading wanted to say about the file. Becomes the
    # page's first note once the page exists.
    note: str | None = Field(default=None, sa_type=Text)
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=127)
    size: int = Field(sa_type=BigInteger)
    object_key: str = Field(unique=True, max_length=512)

    status: ImportStatus = Field(default=ImportStatus.queued, sa_type=String(32))  # type: ignore
    parser: ImportParser | None = Field(default=None, sa_type=String(32))  # type: ignore
    pages_total: int = 0
    pages_done: int = 0
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime = _tz_datetime(default_factory=get_datetime_utc)
    cancel_requested: bool = False
    locked_by: str | None = Field(default=None, max_length=200)
    locked_at: datetime | None = _tz_datetime(default=None)
    heartbeat_at: datetime | None = _tz_datetime(default=None)
    started_at: datetime | None = _tz_datetime(default=None)
    finished_at: datetime | None = _tz_datetime(default=None)
    error: str | None = Field(default=None, sa_type=Text)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class ImportJobPublic(SQLModel):
    id: uuid.UUID
    namespace_id: uuid.UUID
    namespace_slug: str | None = None
    folder_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    attachment_id: uuid.UUID | None = None
    title: str | None = None
    doc_type: str | None = None
    prompt: str | None = None
    filename: str
    content_type: str
    size: int
    # More than one when several uploads are being combined into a single page.
    # `filename` then reads as a summary, and these are the parts in order.
    file_count: int = 1
    filenames: list[str] = []
    status: ImportStatus
    parser: ImportParser | None = None
    pages_total: int = 0
    pages_done: int = 0
    attempts: int = 0
    max_attempts: int = 3
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class ImportJobsPublic(SQLModel):
    data: list[ImportJobPublic]
    count: int


# ---------------------------------------------------------------------------
# Retrieval (hybrid search)
# ---------------------------------------------------------------------------


class RetrievalSourceHit(SQLModel):
    """Why one source matched a document."""

    method: str  # bm25 | vector
    target: str  # document | summary | chunk
    rank: int
    score: float
    contribution: float
    chunk_index: int | None = None
    chunk_title: str | None = None
    entity: str = "document"


class RetrievalSourceReport(SQLModel):
    method: str
    target: str
    hits: int
    took_ms: float
    error: str | None = None
    # Which corpus this source searched, so the explain panel can say "three
    # sources found nothing in your notes" rather than leaving it a mystery.
    entity: str = "document"


class SearchEntity(StrEnum):
    """Which corpus a hit came from.

    Defaulted to `document` everywhere it appears, so a client generated before
    notes existed can never be handed one and mis-link it to /documents.
    """

    document = "document"
    note = "note"


class RetrievalHit(SQLModel):
    # The id of whatever matched: a page, or a note.
    document_id: uuid.UUID
    entity_type: SearchEntity = SearchEntity.document
    # Notes only. An archived note still turns up in search and the reader
    # needs to be told why it is not in their list.
    archived: bool = False
    title: str
    doc_type: str | None = None
    # Null for an unfiled note. A page always has a space; a note is
    # allowed not to, and that is a real state rather than an error.
    namespace_id: uuid.UUID | None = None
    namespace_slug: str
    namespace_name: str
    folder_id: uuid.UUID | None = None
    score: float
    snippet: str
    summary: str | None = None
    updated_at: datetime | None = None
    embedding_status: EmbeddingStatus
    matched_chunk_index: int | None = None
    matched_chunk_title: str | None = None
    sources: list[RetrievalSourceHit] = []


class RetrievalResults(SQLModel):
    data: list[RetrievalHit]
    count: int
    query: str
    query_tokens: list[str] = []
    used_bm25: bool
    used_vector: bool
    used_rerank: bool = False
    targets: list[str] = []
    rrf_k: int
    sources: list[RetrievalSourceReport] = []
    took_ms: float = 0.0


# ---------------------------------------------------------------------------
# Ask (retrieval-augmented answers)
# ---------------------------------------------------------------------------


class AskRequest(SQLModel):
    q: str = Field(min_length=1, max_length=1000)
    namespace_id: uuid.UUID | None = None
    top_k: int | None = Field(default=None, ge=1, le=25)
    # Pin one page: the answer is written from that page alone, with no search
    # and no reranking. See `ask.py:_pinned_passages`.
    document_id: uuid.UUID | None = None
    # Continue an existing thread. Absent, a new one is started.
    conversation_id: uuid.UUID | None = None
    # Your own notes, alongside the pages. Off by default on the wire so a
    # client, key or agent written before notes existed cannot start reading
    # them without saying so; the interface sends true.
    include_notes: bool = False


class AskCitation(SQLModel):
    """One excerpt the model was given, numbered as it appears in the answer."""

    index: int
    document_id: uuid.UUID
    entity_type: SearchEntity = SearchEntity.document
    title: str
    # Null for an unfiled note. A page always has a space; a note is
    # allowed not to, and that is a real state rather than an error.
    namespace_id: uuid.UUID | None = None
    namespace_slug: str
    namespace_name: str
    folder_id: uuid.UUID | None = None
    text: str
    chunk_index: int | None = None
    chunk_title: str | None = None
    score: float = 0.0
    cited: bool = False
    updated_at: datetime | None = None


class AskContext(SQLModel):
    """What an answer would be written from, handed over instead of an answer.

    Every caller that reaches this over MCP is itself a model: it has to phrase
    a reply to somebody either way. Writing an answer here and having that
    caller rewrite it costs a second generation and loses a little of the
    source each time, so this returns the same pages the answer would have been
    written from and lets the caller write once, from the originals.
    """

    question: str
    # AskCitation, because it is the same thing: one page the answer is
    # grounded in, carrying the text and where it came from. Nothing cites it
    # yet, so `cited` is false throughout.
    documents: list[AskCitation] = []
    searched: int = 0
    used: int = 0
    passages: int = 0
    reranked: bool = False
    truncated: bool = False
    retrieval_ms: float = 0.0
    took_ms: float = 0.0


class AskAnswer(SQLModel):
    question: str
    answer: str
    conversation_id: uuid.UUID | None = None
    citations: list[AskCitation] = []
    searched: int = 0  # pages the hybrid search returned
    used: int = 0  # distinct pages that contributed an excerpt
    passages: int = 0  # excerpts sent to the model; a long page can give several
    reranked: bool = False  # whether a cross-encoder chose the pages that were read
    truncated: bool = False
    model: str = ""
    retrieval_ms: float = 0.0
    took_ms: float = 0.0


# ---------------------------------------------------------------------------
# Ask conversations
# ---------------------------------------------------------------------------


class AskRole(StrEnum):
    user = "user"
    assistant = "assistant"


class AskConversation(SQLModel, table=True):
    """One thread of questions and answers, owned by the person who asked.

    Threads are private: there is no sharing model here, so every query is
    scoped by ``user_id`` and nothing else can reach one.
    """

    __table_args__ = (
        # The history rail asks exactly one question - "my threads, newest
        # first" - and this index answers it without touching the table.
        Index("ix_askconversation_user_updated", "user_id", "updated_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    title: str = Field(max_length=120)
    # The space the thread was asked in, remembered so reopening it restores
    # the scope. Null means every space the asker can read.
    namespace_id: uuid.UUID | None = Field(
        default=None, foreign_key="namespace.id", ondelete="SET NULL"
    )
    # Set when the thread is pinned to a single page. If that page is deleted
    # the thread survives as an ordinary one rather than vanishing with it.
    document_id: uuid.UUID | None = Field(
        default=None, foreign_key="document.id", ondelete="SET NULL"
    )
    message_count: int = 0
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class AskMessage(SQLModel, table=True):
    __table_args__ = (
        Index("ix_askmessage_conversation_seq", "conversation_id", "seq"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: uuid.UUID = Field(
        foreign_key="askconversation.id", nullable=False, ondelete="CASCADE"
    )
    seq: int  # 1-based position in the thread; user and assistant share the run
    role: AskRole = Field(sa_type=String(16))  # type: ignore
    content: str = Field(sa_type=Text)
    # Assistant turns only: the sources that answer was written from, each
    # carrying a short preview rather than the whole page. Storing the full
    # excerpt would put hundreds of kilobytes per turn in the row and make
    # reopening a thread slower than asking the question again.
    citations: list[dict[str, Any]] | None = Field(default=None, sa_type=JSONB)
    # searched / used / passages / truncated / model / took_ms
    stats: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class AskMessagePublic(SQLModel):
    id: uuid.UUID
    seq: int
    role: AskRole
    content: str
    citations: list[AskCitation] = []
    stats: dict[str, Any] | None = None
    created_at: datetime


class AskConversationPublic(SQLModel):
    """A row in the history rail: enough to label it, nothing more."""

    id: uuid.UUID
    title: str
    namespace_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    document_title: str | None = None
    namespace_slug: str | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class AskConversationsPublic(SQLModel):
    data: list[AskConversationPublic]
    count: int


class AskConversationDetail(AskConversationPublic):
    messages: list[AskMessagePublic] = []


class AskConversationUpdate(SQLModel):
    title: str = Field(min_length=1, max_length=120)


# ---------------------------------------------------------------------------
# Document versions and translations
# ---------------------------------------------------------------------------


class DocumentVersion(SQLModel, table=True):
    """A page as it stood at one version number.

    The current version is stored here as well as on the document. The
    duplication buys a history table that is complete on its own - "show me
    version 4" is one row either way, and nothing has to special-case the
    newest one.
    """

    __table_args__ = (
        UniqueConstraint(
            "document_id", "version", name="uq_documentversion_doc_version"
        ),
        Index("ix_documentversion_document", "document_id", "version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE"
    )
    version: int
    title: str = Field(max_length=300)
    content_html: str = Field(default="", sa_type=Text)
    content_text: str = Field(default="", sa_type=Text)
    doc_type: str | None = Field(default=None, max_length=DOCUMENT_TYPE_MAX)
    language: str | None = Field(default=None, max_length=8)
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class DocumentVersionSummary(SQLModel):
    """A row in the version picker: enough to choose one, not its content."""

    version: int
    title: str
    doc_type: str | None = None
    language: str | None = None
    char_count: int = 0
    is_current: bool = False
    # The originals uploaded at this version, if this is the version an import
    # produced. This is how a page says which version the file it came from is.
    source_filenames: list[str] = []
    created_by_user: UserRef | None = None
    created_at: datetime


class DocumentVersionPublic(DocumentVersionSummary):
    content_html: str = ""
    content_text: str = ""


class DocumentVersionsPublic(SQLModel):
    data: list[DocumentVersionSummary]
    count: int


class DocumentTranslation(SQLModel, table=True):
    """One page, one version, one language.

    Tied to the version rather than the page: an edited page is a different
    text, and showing last week's German next to this week's English would be
    worse than translating again. Editing therefore leaves the translations of
    earlier versions in place and simply has none of its own yet.
    """

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "doc_version",
            "language",
            name="uq_documenttranslation_doc_version_lang",
        ),
        Index("ix_documenttranslation_document", "document_id", "doc_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE"
    )
    doc_version: int
    language: str = Field(max_length=8)
    title: str = Field(max_length=300)
    content_html: str = Field(default="", sa_type=Text)
    content_text: str = Field(default="", sa_type=Text)
    # Which model wrote it, so a bad translation can be traced to one.
    model: str | None = Field(default=None, max_length=120)
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class TranslationRequest(SQLModel):
    language: str = Field(min_length=2, max_length=8)


class LanguageOption(SQLModel):
    code: str
    name: str


class TranslationPublic(SQLModel):
    document_id: uuid.UUID
    doc_version: int
    language: str
    language_name: str
    title: str
    content_html: str
    content_text: str
    model: str | None = None
    created_at: datetime


class SearchSuggestion(SQLModel, table=True):
    """An example search, written from one of this person's own pages.

    Generic examples ("error 407 vpn token") teach the mechanics of search and
    nothing about what is actually in here. A question drawn from a page the
    reader has uploaded does both, and it is the difference between an empty
    search box that explains itself and one that does not.

    Private by construction: rows belong to a user, every read is scoped by
    ``user_id``, and a suggestion is only ever written for the person who
    created the page it came from.
    """

    __table_args__ = (
        UniqueConstraint(
            "user_id", "document_id", name="uq_searchsuggestion_user_document"
        ),
        Index("ix_searchsuggestion_user_created", "user_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    # Kept so the suggestion dies with the page it describes, and so one page
    # never contributes two.
    document_id: uuid.UUID | None = Field(
        default=None, foreign_key="document.id", ondelete="CASCADE"
    )
    namespace_id: uuid.UUID | None = Field(
        default=None, foreign_key="namespace.id", ondelete="CASCADE"
    )
    question: str = Field(max_length=200)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class SearchSuggestionPublic(SQLModel):
    question: str
    document_id: uuid.UUID | None = None


class SearchSuggestionsPublic(SQLModel):
    data: list[SearchSuggestionPublic]
    count: int


class DocumentLanguages(SQLModel):
    """What the language picker on a page needs to draw itself."""

    document_id: uuid.UUID
    version: int
    # The language the page itself is written in, as detected.
    source_language: str | None = None
    source_language_name: str | None = None
    # Languages already translated for *this* version, so they open instantly.
    available: list[str] = []
    # Everything on offer.
    options: list[LanguageOption] = []


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


class ApiKeyCreate(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    scope: ApiKeyScope = ApiKeyScope.read
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyUpdate(SQLModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKey(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=100)
    key_prefix: str = Field(max_length=16)
    key_hash: str = Field(unique=True, index=True, max_length=64)
    scope: ApiKeyScope = Field(default=ApiKeyScope.read, sa_type=String(32))  # type: ignore
    last_used_at: datetime | None = _tz_datetime(default=None)
    expires_at: datetime | None = _tz_datetime(default=None)
    revoked_at: datetime | None = _tz_datetime(default=None)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    user: User | None = Relationship(back_populates="api_keys")


class AuthCode(SQLModel, table=True):
    """A one-time secret sent to an address, stored only as a hash.

    The same shape serves all three flows, because the security properties they
    need are identical: single use, short life, a guessing budget, and no way to
    read the secret back out of the database. What differs is only the shape of
    the secret - six digits a person types for two-factor, a long random token
    inside a link for the two email flows - and how long it lives.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    purpose: AuthCodePurpose = Field(sa_type=String(32))  # type: ignore
    code_hash: str = Field(index=True, max_length=64)
    # The address it was sent to, which is not always the account's current one:
    # a verification sent before an email change must not confirm the new one.
    sent_to: str = Field(max_length=255)
    expires_at: datetime = _tz_datetime(nullable=False)
    consumed_at: datetime | None = _tz_datetime(default=None)
    attempts: int = Field(default=0)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class ApiKeyPublic(SQLModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scope: ApiKeyScope
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


class ApiKeyCreated(ApiKeyPublic):
    key: str


class ApiKeysPublic(SQLModel):
    data: list[ApiKeyPublic]
    count: int


# ---------------------------------------------------------------------------
# Search + health
# ---------------------------------------------------------------------------


class SearchResult(SQLModel):
    document_id: uuid.UUID
    title: str
    doc_type: str | None = None
    namespace_id: uuid.UUID
    namespace_slug: str
    namespace_name: str
    folder_id: uuid.UUID | None = None
    snippet: str
    rank: float
    updated_at: datetime | None = None
    embedding_status: EmbeddingStatus


class SearchResults(SQLModel):
    data: list[SearchResult]
    count: int


class ServiceHealth(SQLModel):
    ok: bool
    latency_ms: float | None = None
    detail: str | None = None


class HealthReport(SQLModel):
    status: str  # "ok" | "degraded"
    services: dict[str, ServiceHealth]
    checked_at: datetime


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None
    # Present only on tokens that are not sessions, such as the short-lived
    # challenge issued between a correct password and its emailed code.
    typ: str | None = None
    # Session epoch the token was minted under. A token whose epoch is behind
    # the account's has been revoked, which is how a password change signs out
    # every other device.
    sev: int | None = None


class TokenMessage(Message):
    """A message plus a replacement session, for actions that revoke the old one."""

    access_token: str
    token_type: str = "bearer"


class LoginChallenge(SQLModel):
    """What a correct password buys: the right to be asked for a code.

    No part of this is a credential. It names the pending login and says where
    the code went, with the address masked so a borrowed screen does not give
    away the whole mailbox.
    """

    challenge_token: str
    expires_at: datetime
    sent_to: str  # masked, e.g. "s••••••5@gmail.com"
    code_length: int
    # False when the code could not be emailed. The login cannot continue, and
    # saying so beats leaving someone waiting for a message that will not come.
    delivered: bool = True


class TwoFactorVerify(SQLModel):
    challenge_token: str
    code: str = Field(min_length=4, max_length=12)


class TwoFactorResend(SQLModel):
    challenge_token: str


class EmailVerificationRequest(SQLModel):
    email: EmailStr = Field(max_length=255)


class EmailVerificationConfirm(SQLModel):
    token: str = Field(min_length=16, max_length=256)


class PasswordRecoveryRequest(SQLModel):
    email: EmailStr = Field(max_length=255)


class NewPassword(SQLModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Agents and channels
#
# An *agent* is a conversational assistant a user talks to from a messaging
# channel. Each one is backed by its own Hermes profile - its own home
# directory, conversation store and knowledge-base credential - because that is
# the isolation unit Hermes is built around. Two users' agents share a process
# but never a profile.
#
# A *channel connection* binds a platform identity (a phone number, a Telegram
# user id) to one agent. Everyone messages the same bot, so an inbound identity
# is a claim rather than a credential: a connection only exists once the person
# has proved they hold both the channel account and the PlusGPT account, by
# sending a one-time code issued in the dashboard.
# ---------------------------------------------------------------------------


class ChannelType(StrEnum):
    whatsapp = "whatsapp"
    telegram = "telegram"
    slack = "slack"
    discord = "discord"


class WhatsAppTransport(StrEnum):
    """Which WhatsApp backend the deployment talks to.

    ``cloud_api`` is Meta's official Business API: webhook ingress, priced per
    conversation, safe to run at scale. ``bridge`` pairs an ordinary WhatsApp
    account over WhatsApp Web through a Node sidecar - free and instant, but
    unofficial, so a ban takes every user's agent down at once.
    """

    cloud_api = "cloud_api"
    bridge = "bridge"


class AgentStatus(StrEnum):
    provisioning = "provisioning"
    ready = "ready"
    failed = "failed"
    disabled = "disabled"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class AgentBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    # Appended to the agent's persona file. The agent already knows it is a
    # knowledge-base assistant; this is for "call me Sam", "answer in German".
    persona: str | None = Field(default=None, max_length=4000)


class AgentCreate(AgentBase):
    pass


class AgentUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    persona: str | None = Field(default=None, max_length=4000)


class Agent(AgentBase, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_agent_user_name"),
        Index("ix_agent_shard", "shard_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # The Hermes profile directory name. Derived from the id rather than the
    # user's chosen name: renaming an agent must not move its conversation store.
    profile_name: str = Field(unique=True, index=True, max_length=64)
    # Which gateway container serves it. Pinned at creation, because the profile
    # directory lives on that shard's volume.
    shard_id: int = Field(default=0)
    status: AgentStatus = Field(default=AgentStatus.provisioning, sa_type=String(32))  # type: ignore
    status_detail: str | None = Field(default=None, max_length=500)
    # The knowledge-base key this agent authenticates to the MCP server with.
    # Kept as a reference so deleting the agent can revoke it.
    api_key_id: uuid.UUID | None = Field(
        default=None, foreign_key="apikey.id", ondelete="SET NULL"
    )
    # Bearer token this agent presents to the LLM proxy. Hashed, like every
    # other credential here, and revoked by clearing it.
    llm_token_hash: str | None = Field(default=None, index=True, max_length=64)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    connections: list[ChannelConnection] = Relationship(
        back_populates="agent", cascade_delete=True
    )


class ChannelConnectionPublic(SQLModel):
    id: uuid.UUID
    channel_type: ChannelType
    # Masked for display: a phone number is personal data and the dashboard
    # only needs enough of it to be recognisable.
    identity_hint: str
    display_name: str | None
    created_at: datetime | None


class AgentPublic(AgentBase):
    id: uuid.UUID
    status: AgentStatus
    status_detail: str | None
    created_at: datetime | None
    connections: list[ChannelConnectionPublic]


class AgentsPublic(SQLModel):
    data: list[AgentPublic]
    count: int


# ---------------------------------------------------------------------------
# Channel connections
# ---------------------------------------------------------------------------


class ChannelConnection(SQLModel, table=True):
    __table_args__ = (
        # One identity, one agent. The database enforces the product rule that a
        # channel account can only be connected once, so a race between two
        # redemptions cannot bind the same phone number to two people.
        UniqueConstraint(
            "channel_type", "platform_identity", name="uq_channel_identity"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(
        foreign_key="agent.id", nullable=False, ondelete="CASCADE", index=True
    )
    channel_type: ChannelType = Field(sa_type=String(32))  # type: ignore
    # The platform's own id for this person: a phone number for WhatsApp, a
    # numeric chat id for Telegram. Matched verbatim against inbound events.
    platform_identity: str = Field(max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)
    last_seen_at: datetime | None = _tz_datetime(default=None)

    agent: Agent | None = Relationship(back_populates="connections")


# ---------------------------------------------------------------------------
# Link codes
# ---------------------------------------------------------------------------


class ChannelLinkCode(SQLModel, table=True):
    """A one-time code proving the sender of a message owns a PlusGPT account.

    Stored hashed, like every other one-time secret here: a database leak must
    not hand someone else's channel to an attacker. Single use and short lived,
    because the plaintext travels through a messaging app.
    """

    __table_args__ = (Index("ix_channellinkcode_agent", "agent_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(
        foreign_key="agent.id", nullable=False, ondelete="CASCADE"
    )
    channel_type: ChannelType = Field(sa_type=String(32))  # type: ignore
    code_hash: str = Field(unique=True, index=True, max_length=64)
    expires_at: datetime = _tz_datetime(nullable=False)
    used_at: datetime | None = _tz_datetime(default=None)
    created_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class ChannelLinkCodeCreate(SQLModel):
    channel_type: ChannelType


class ChannelLinkCodePublic(SQLModel):
    """The plaintext code, returned once at issue time and never stored."""

    code: str
    channel_type: ChannelType
    expires_at: datetime
    # A tap-through that pre-fills the code in the messaging app, where the
    # platform supports one.
    deep_link: str | None = None
    instructions: str


# ---------------------------------------------------------------------------
# Admin channel configuration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------


class DataSourceType(StrEnum):
    google_drive = "google_drive"


class DataSourceConfig(SQLModel, table=True):
    """Deployment-wide setup for one data source, managed by an administrator.

    The same shape as ChannelConfig, and for the same reason: the client secret
    goes in encrypted and never comes back out, so the API can say a source is
    configured without being a way to read the credentials back.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_type: DataSourceType = Field(unique=True, index=True, sa_type=String(32))  # type: ignore
    enabled: bool = Field(default=False)
    credentials_encrypted: str | None = Field(default=None, sa_type=Text)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class DataSourceConnection(SQLModel, table=True):
    """One person's standing authorisation for one source.

    The refresh token is the whole of the grant - it is what lets the server
    reach Google as this user tomorrow - so it is encrypted at rest like any
    other credential, and never returned by the API. Deleting the row is what
    "disconnect" means locally; the token is revoked at Google as well, because
    a grant nobody can see is still a grant.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    source_type: DataSourceType = Field(index=True, sa_type=String(32))  # type: ignore
    # Whose account it is, so the card can say which Google this is.
    account_email: str | None = Field(default=None, max_length=320)
    credentials_encrypted: str | None = Field(default=None, sa_type=Text)
    # What the user actually granted, which is not always what was asked for.
    scopes: str = Field(default="", sa_type=Text)
    connected_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)

    __table_args__ = (
        UniqueConstraint("user_id", "source_type", name="uq_datasource_user_source"),
    )


class DataSourceConfigUpdate(SQLModel):
    enabled: bool | None = None
    # Write-only. Absent leaves the stored credentials untouched, so an admin
    # can switch a source off without re-entering the secret.
    credentials: dict[str, str] | None = None


class DataSourceConfigPublic(SQLModel):
    source_type: DataSourceType
    enabled: bool
    configured: bool
    required_fields: list[str]
    present_fields: list[str]
    # The URI that has to be registered with the provider. Shown to the admin
    # so it is copied rather than retyped, which is how redirect_uri_mismatch
    # happens.
    redirect_uri: str
    updated_at: datetime | None


class DataSourceConfigsPublic(SQLModel):
    data: list[DataSourceConfigPublic]


class DataSourcePublic(SQLModel):
    """What one source looks like to the person who might connect it."""

    source_type: DataSourceType
    available: bool  # an admin has configured and enabled it
    connected: bool
    account_email: str | None = None
    connected_at: datetime | None = None


class DataSourcesPublic(SQLModel):
    data: list[DataSourcePublic]


class GoogleDrivePickerConfig(SQLModel):
    """What the browser needs to open Google's own file picker.

    The access token is short-lived and scoped to `drive.file`, which grants
    nothing until the person picks something. The API key is public by design -
    it is restricted by HTTP referrer at Google - and the client secret is not
    here, because the browser never needs it.
    """

    client_id: str
    api_key: str
    access_token: str
    expires_in: int


# What a Google Drive file id may contain.
DRIVE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class GoogleDrivePickedFile(SQLModel):
    file_id: str = Field(min_length=1, max_length=255)
    name: str = Field(default="", max_length=255)
    mime_type: str = Field(default="", max_length=127)

    @field_validator("file_id")
    @classmethod
    def _is_a_drive_id(cls, value: str) -> str:
        """Constrain the id, because it is interpolated into a URL.

        `httpx` resolves `..` against the base, so an unconstrained id lets a
        crafted pick steer the request to any other googleapis.com endpoint -
        carrying the account's live OAuth token with it.

        A validator rather than `Field(regex=...)`: SQLModel accepts that
        keyword and silently drops it, which is worse than no constraint at all
        because it reads like one.
        """
        if not DRIVE_FILE_ID.match(value):
            raise ValueError("That is not a Google Drive file id")
        return value


class GoogleDriveImportRequest(SQLModel):
    files: list[GoogleDrivePickedFile] = Field(min_length=1, max_length=25)
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    doc_type: str | None = Field(default=None, max_length=100)
    prompt: str | None = Field(default=None, max_length=2000)
    # Kept as the first note on every page this import creates, the same as an
    # ordinary upload.
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    combine: bool = False


class ChannelConfig(SQLModel, table=True):
    """Deployment-wide setup for one channel, managed by an administrator.

    Credentials are encrypted at rest and never leave the server: the API
    returns only whether a value is set. A channel a user sees offered on their
    agent is one an admin has both configured and enabled.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    channel_type: ChannelType = Field(unique=True, index=True, sa_type=String(32))  # type: ignore
    enabled: bool = Field(default=False)
    # WhatsApp only; ignored by the other channels.
    transport: WhatsAppTransport | None = Field(default=None, sa_type=String(32))  # type: ignore
    credentials_encrypted: str | None = Field(default=None, sa_type=Text)
    # Shown to users on the connect card, e.g. the bot's @handle or number.
    public_handle: str | None = Field(default=None, max_length=255)
    updated_at: datetime | None = _tz_datetime(default_factory=get_datetime_utc)


class ChannelConfigUpdate(SQLModel):
    enabled: bool | None = None
    transport: WhatsAppTransport | None = None
    public_handle: str | None = Field(default=None, max_length=255)
    # Write-only. Absent leaves the stored credentials untouched, so an admin
    # can toggle a channel without re-entering secrets.
    credentials: dict[str, str] | None = None


class ChannelConfigPublic(SQLModel):
    channel_type: ChannelType
    enabled: bool
    transport: WhatsAppTransport | None
    public_handle: str | None
    configured: bool
    # Which credential fields this channel needs, so the admin form is driven
    # by the server rather than duplicated in the frontend.
    required_fields: list[str]
    present_fields: list[str]
    updated_at: datetime | None


class ChannelConfigsPublic(SQLModel):
    data: list[ChannelConfigPublic]


class AvailableChannel(SQLModel):
    """A channel a user may connect, as offered on the agent page."""

    channel_type: ChannelType
    public_handle: str | None
    connected: bool


class AvailableChannelsPublic(SQLModel):
    data: list[AvailableChannel]


class WhatsAppPairingPublic(SQLModel):
    """How pairing the local WhatsApp bridge is going.

    ``state`` is whatever the shard last reported: ``idle`` before anything has
    been asked of it, ``starting`` while the bridge boots, ``qr`` when there is
    a code to scan, ``connected`` once a phone has scanned it, ``paired`` when a
    session already exists, ``unavailable`` when the gateway is not running, and
    ``error`` with a reason.
    """

    state: str
    detail: str | None = None
    account: str | None = None
    # The QR rendered server-side, so the dashboard needs no encoder of its own.
    qr_svg: str | None = None
    updated_at: float | None = None


# ---------------------------------------------------------------------------
# Usage metering
#
# Every call to a model provider is billed, and the questions asked of that
# spend are always the same three: whose, which day, which model. So that is
# the shape of the row - there is no event log underneath this and no rollup
# job on top of it. Calls are accumulated in memory for the length of one
# request or job and folded in with a single UPSERT that adds to the counters,
# which is atomic per row and therefore safe under any amount of concurrency.
#
# `cost_nanos` is an integer because these are money: a year of summing floats
# drifts, and the provider hands us a figure per call anyway, so there is no
# price table here to fall out of date.
# ---------------------------------------------------------------------------


class UsageFeature(StrEnum):
    """What the person was doing when the call happened."""

    ask = "ask"
    search = "search"
    # Turning a file into a page: one vision call per page of a PDF, and on a
    # hosted deployment the largest thing the product spends money on.
    import_ = "import"
    # Making a page searchable: chunking, summarising, embedding. Separate from
    # `import` because every page is indexed and only some are imported.
    indexing = "indexing"
    translation = "translation"
    suggestions = "suggestions"
    agent = "agent"


class UsageKind(StrEnum):
    """What kind of call it was.

    ``feature`` is not a model call at all: it is one row per thing a person
    did, so "1,208 searches" stays true even when the query was served from the
    embedding cache and cost nothing.
    """

    feature = "feature"
    chat = "chat"
    embedding = "embedding"
    rerank = "rerank"


class UsageDaily(SQLModel, table=True):
    """One account's usage of one model, for one feature, on one day."""

    __table_args__ = (
        # The UPSERT target. Everything else about this table follows from it.
        UniqueConstraint(
            "day", "user_id", "feature", "kind", "model", name="uq_usagedaily_bucket"
        ),
        # "my usage over this range" - the only question the user's own
        # dashboard asks.
        Index("ix_usagedaily_user_day", "user_id", "day"),
        # "everyone's usage over this range" - the admin one. Per-group
        # roll-ups join `user.group_id`, which is already indexed.
        Index("ix_usagedaily_day", "day"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # UTC. Stored rather than derived with date_trunc, which keeps the index a
    # plain b-tree like every other index here.
    day: date = Field(sa_type=Date, nullable=False)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    feature: UsageFeature = Field(sa_type=String(20))  # type: ignore
    kind: UsageKind = Field(sa_type=String(12))  # type: ignore
    # The model that actually answered, which is not the one we asked for when
    # the provider re-routed across the fallback list. Empty on `feature` rows:
    # it is part of the unique key, and NULLs would be distinct there.
    model: str = Field(default="", max_length=160)

    # On a `feature` row: operations the person performed. On a model row:
    # upstream HTTP calls actually made. More than the operation count means
    # retries and fallbacks; fewer means something was served from a cache.
    requests: int = Field(default=0)
    # Calls that raised. A failed call returns no usage block and costs nothing.
    failures: int = Field(default=0)

    input_tokens: int = Field(default=0, sa_type=BigInteger)
    output_tokens: int = Field(default=0, sa_type=BigInteger)
    reasoning_tokens: int = Field(default=0, sa_type=BigInteger)
    cached_tokens: int = Field(default=0, sa_type=BigInteger)
    cache_write_tokens: int = Field(default=0, sa_type=BigInteger)
    # Rerank bills per search unit, not per token.
    search_units: int = Field(default=0, sa_type=BigInteger)
    # US dollars x 1e9. Self-hosted servers report no cost, and 0 is the right
    # answer there.
    cost_nanos: int = Field(default=0, sa_type=BigInteger)

    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


# --- Usage as it is reported ------------------------------------------------
#
# Two families, and the split is the point. `UsageTotals` has no cost field at
# all, so no later edit can leak spend into a reply somebody reads about their
# own account - the same discipline groups get, where privacy is enforced by
# the shape of the response model rather than by remembering.


class UsageTotals(SQLModel):
    """What was done and what it took, with no mention of money.

    Every field is required rather than defaulted. A default here would make
    each one optional in the generated schema, and a client would then have to
    defend against a count that is never actually absent.
    """

    requests: int
    failures: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    search_units: int


class AdminUsageTotals(UsageTotals):
    """The same, for somebody entitled to see the bill.

    Nanos rather than dollars, matching storage exactly: one call can cost
    5.12e-06, and rounding that to whole micros loses two per cent of it.
    """

    cost_nanos: int


class UsagePoint(SQLModel):
    """One row of a breakdown: a day, a feature, a model, or an account."""

    key: str
    label: str | None = None
    totals: UsageTotals


class AdminUsagePoint(SQLModel):
    key: str
    label: str | None = None
    # Set on by-user rows, so a spend table can be read by group without a
    # second request.
    group: GroupRef | None = None
    totals: AdminUsageTotals


class UsageRange(SQLModel):
    """The days a reply covers. UTC, and the interface says so."""

    frm: date
    to: date
    days: int


class MyUsage(SQLModel):
    """One account's own usage. Cost is unrepresentable here."""

    range: UsageRange
    totals: UsageTotals
    by_feature: list[UsagePoint]
    by_day: list[UsagePoint]
    by_model: list[UsagePoint]


class AdminUsageSummary(SQLModel):
    range: UsageRange
    totals: AdminUsageTotals
    by_feature: list[AdminUsagePoint]
    by_day: list[AdminUsagePoint]


class AdminUsageBreakdown(SQLModel):
    range: UsageRange
    # "user", "model", "group" or "feature"
    by: str
    totals: AdminUsageTotals
    data: list[AdminUsagePoint]
    count: int


# ---------------------------------------------------------------------------
# Notes on a page
#
# What somebody wanted to say about a document that is not in the document: why
# it was uploaded, what to watch out for, what it supersedes. A scan of an
# invoice cannot tell you it was already disputed.
#
# Notes are their own rows rather than text appended to the page, because they
# have an author and a time and they are somebody's addition rather than the
# document's content - a scan should still read as the scan. But they are
# indexed with the page and read with it, because a note nobody can find by
# searching for it is a note nobody will read again.
# ---------------------------------------------------------------------------


class DocumentNote(SQLModel, table=True):
    """One thing a person added to a page."""

    __table_args__ = (
        # "the notes on this page, oldest first" - the only question asked.
        Index("ix_documentnote_document_created", "document_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id", nullable=False, ondelete="CASCADE"
    )
    body: str = Field(sa_type=Text)
    # Kept when the account goes: the note is part of the page's history, and
    # deleting somebody should not silently edit what a page says.
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class DocumentNoteCreate(SQLModel):
    body: str = Field(min_length=1, max_length=NOTE_MAX)


class DocumentNoteUpdate(SQLModel):
    body: str = Field(min_length=1, max_length=NOTE_MAX)


class DocumentNotePublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    body: str
    created_by: uuid.UUID | None = None
    author: UserRef | None = None
    created_at: datetime
    updated_at: datetime
    # Whether the reader may change this one. Editing is the author's, deleting
    # is the author's or anybody who could edit the page.
    can_edit: bool = False
    can_delete: bool = False


class DocumentNotesPublic(SQLModel):
    data: list[DocumentNotePublic]
    count: int


# ---------------------------------------------------------------------------
# Credits
#
# What an account may spend on model work. The allowance resolves through the
# same four tiers every other limit does; a grant is an administrator topping
# somebody up by hand. See app/services/credits.py for the arithmetic and, more
# importantly, for why a grant has an end date.
# ---------------------------------------------------------------------------


class CreditGrant(SQLModel, table=True):
    """Credits an administrator gave one account, on top of its allowance."""

    __table_args__ = (
        # "what is this account holding right now" - asked on every balance
        # check, which is every metered operation.
        Index("ix_creditgrant_user_expires", "user_id", "expires_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    # Milli-credits, like everything else here: a thousandth of a credit is one
    # token, which is the smallest thing anybody spends.
    amount_milli: int
    reason: str = Field(default="", max_length=300)
    granted_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    # When it stops counting. Never NULL: a grant that never expires is not a
    # one-off top-up, it is a permanent raise, and the right way to give one of
    # those is the account's own `monthly_credits` override.
    expires_at: datetime = _tz_datetime()
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class CreditGrantCreate(SQLModel):
    credits: int = Field(gt=0, le=10_000_000)
    reason: str = Field(default="", max_length=300)
    # Days the grant stays spendable. Left out, it lasts to the end of the
    # month it was given in, which is when the allowance renews anyway.
    days: int | None = Field(default=None, ge=1, le=365)


class CreditGrantPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    credits: float
    reason: str
    granted_by: uuid.UUID | None = None
    expires_at: datetime
    created_at: datetime
    expired: bool = False


class CreditGrantsPublic(SQLModel):
    data: list[CreditGrantPublic]
    count: int


class CreditBalance(SQLModel):
    """What an account has left this month, and what it spent getting there."""

    # The calendar month this describes, as YYYY-MM, and when it renews.
    period: str
    renews_at: datetime
    # The monthly allowance, resolved through user → group → default → constant.
    allowance: float
    # Still-live one-off grants, which do not survive their expiry date.
    granted: float
    used: float
    remaining: float
    # What the spend went on, so "where did my credits go" has an answer.
    used_on_answers: float
    used_on_search: float
    used_on_indexing: float
    used_on_other: float


# ---------------------------------------------------------------------------
# Notes
#
# Somebody's own notes: short, private, written fast. Not to be confused with
# DocumentNote above, which is a remark *about a page* and is read by everyone
# who can read that page. These belong to one person and to nobody else.
#
# A note lives in a space, because that is how this product organises what a
# thing is about, but the space grants nobody any access to it. There is no
# share table here and there is no helper in core/permissions.py, both on
# purpose: every query carries `Note.user_id == user.id`, and a superuser is
# not an exception. "An administrator can read your notes" is a different
# product from this one. AskConversation makes the same promise the same way.
#
# One table holds all three kinds. A generated tsvector may only reference its
# own row, so a table per kind would mean a search vector, a lexical source and
# a hydration branch per kind; instead each kind derives the same `content_text`
# column, and adding a fourth kind is one function.
# ---------------------------------------------------------------------------

NOTE_TITLE_MAX = 300
NOTE_TAG_MAX = 50

# Kept beside the model because the migration must repeat it exactly: a
# generated column cannot be altered in place, only dropped and rebuilt, so a
# drift between these two is a rebuild nobody asked for.
NOTE_SEARCH_VECTOR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', left(coalesce(content_text, ''), 100000)), 'B')"
)


class NoteKind(StrEnum):
    text = "text"
    checklist = "checklist"
    drawing = "drawing"


class Note(SQLModel, table=True):
    """One note, belonging to the person who wrote it."""

    __table_args__ = (
        # "my notes, newest first" - the list, and the only question it asks.
        Index("ix_note_user_updated", "user_id", "updated_at"),
        # The same list again, split by whether it has been put away.
        Index("ix_note_user_archived", "user_id", "archived_at"),
        Index("ix_note_user_namespace", "user_id", "namespace_id"),
        Index("ix_note_embedding_status", "embedding_status"),
        Index("ix_note_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    # Where the note is filed. SET NULL rather than CASCADE: deleting a space
    # is an act on that space's pages, and it must not reach into other
    # people's private notes. RESTRICT would be worse still - the delete would
    # fail with "3 notes are in here", which tells an administrator that
    # somebody has private notes and is the exact leak this model exists to
    # prevent. Null reads as "Unfiled", which is a state the interface can show.
    namespace_id: uuid.UUID | None = Field(
        default=None, foreign_key="namespace.id", ondelete="SET NULL"
    )
    kind: NoteKind = Field(default=NoteKind.text, sa_type=String(16))  # type: ignore
    title: str = Field(default="", max_length=NOTE_TITLE_MAX)
    # kind=text and kind=checklist: the editor's HTML, a checklist being a
    # document whose body is one task list. kind=drawing: empty.
    content_html: str = Field(default="", sa_type=Text)
    # kind=drawing: the strokes, so the sketch can be reopened and edited.
    content_json: Any | None = Field(default=None, sa_type=JSONB)
    # Whatever the kind above amounts to in words, derived on write by
    # services/user_notes.py. The search vector and the indexer read this and
    # nothing else, which is what keeps one pipeline for three kinds.
    content_text: str = Field(default="", sa_type=Text)
    color: str | None = Field(default=None, max_length=20)
    # Timestamps rather than flags. Same storage, and they answer "when", which
    # orders the pinned group and dates the archive without a second column.
    pinned_at: datetime | None = _tz_datetime(default=None)
    archived_at: datetime | None = _tz_datetime(default=None)
    version: int = 1
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)

    # Indexing state, mirroring Document's block so the two read alike.
    embedding_status: EmbeddingStatus = Field(
        default=EmbeddingStatus.pending,
        sa_type=String(32),  # type: ignore
    )
    embedding_version: int | None = None
    embedding_error: str | None = Field(default=None, sa_type=Text)
    embedding_attempts: int = 0
    chunk_count: int = 0
    embedding_updated_at: datetime | None = _tz_datetime(default=None)

    # Written by Postgres on COMMIT, which is what makes a note findable by
    # keyword the instant it is saved rather than when the worker gets to it.
    search_vector: Any = Field(
        default=None,
        sa_column=Column(
            TSVECTOR,
            Computed(NOTE_SEARCH_VECTOR, persisted=True),
            nullable=True,
        ),
    )


class NoteTag(SQLModel, table=True):
    """A label somebody made up, and may put on any number of their notes."""

    __table_args__ = (
        # Per person, not global: one person's vocabulary must not appear in
        # another's autocomplete. Folded, so nobody ends up with Work and work.
        UniqueConstraint("user_id", "name_folded", name="uq_notetag_user_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    name: str = Field(max_length=NOTE_TAG_MAX)
    name_folded: str = Field(max_length=NOTE_TAG_MAX)
    # Colour belongs to the tag rather than to the note, so a colour has a name
    # attached to it. A colour on its own is a label nobody can remember.
    color: str | None = Field(default=None, max_length=20)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class NoteTagLink(SQLModel, table=True):
    note_id: uuid.UUID = Field(
        foreign_key="note.id", primary_key=True, ondelete="CASCADE"
    )
    tag_id: uuid.UUID = Field(
        foreign_key="notetag.id", primary_key=True, ondelete="CASCADE"
    )


class NoteTagPublic(SQLModel):
    id: uuid.UUID
    name: str
    color: str | None = None


class NoteTagCreate(SQLModel):
    name: str = Field(min_length=1, max_length=NOTE_TAG_MAX)
    color: str | None = Field(default=None, max_length=20)


class NoteTagUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=NOTE_TAG_MAX)
    color: str | None = Field(default=None, max_length=20)


class NoteTagsPublic(SQLModel):
    data: list[NoteTagPublic]
    count: int


class NoteCreate(SQLModel):
    namespace_id: uuid.UUID | None = None
    kind: NoteKind = NoteKind.text
    title: str = Field(default="", max_length=NOTE_TITLE_MAX)
    content: str = ""
    content_format: ContentFormat = ContentFormat.html
    content_json: Any | None = None
    color: str | None = Field(default=None, max_length=20)
    tag_ids: list[uuid.UUID] | None = None


class NoteUpdate(SQLModel):
    title: str | None = Field(default=None, max_length=NOTE_TITLE_MAX)
    content: str | None = None
    content_format: ContentFormat = ContentFormat.html
    content_json: Any | None = None
    # Sent as an empty string to clear it; left out entirely to leave it alone.
    color: str | None = Field(default=None, max_length=20)
    tag_ids: list[uuid.UUID] | None = None
    # Optimistic locking, the same contract documents use, so the editor's
    # autosave can tell "somebody else changed this" from "the save failed".
    expected_version: int | None = None


class NoteMove(SQLModel):
    """Refile a note. Null means unfiled, which is a real destination."""

    namespace_id: uuid.UUID | None = None


class NoteSummaryPublic(SQLModel):
    """A note as the list and the search results show it: no body."""

    id: uuid.UUID
    namespace_id: uuid.UUID | None = None
    namespace_name: str | None = None
    kind: NoteKind
    title: str
    # Plain text, short. The board renders this rather than mounting an editor
    # per card, which also keeps server HTML out of the card entirely.
    preview: str
    color: str | None = None
    pinned: bool
    archived: bool
    # Only meaningful for kind=checklist; 0/0 otherwise.
    checklist_done: int = 0
    checklist_total: int = 0
    tags: list[NoteTagPublic] = []
    version: int
    created_at: datetime
    updated_at: datetime
    embedding_status: EmbeddingStatus
    chunk_count: int = 0


class NotePublic(NoteSummaryPublic):
    content_html: str
    content_json: Any | None = None
    content_text: str


class NotesPublic(SQLModel):
    data: list[NoteSummaryPublic]
    count: int


class NoteChunk(SQLModel, table=True):
    """A slice of a long note, so a passage can be found rather than the whole.

    Its own table rather than a nullable column on `documentchunk`: the FK is
    what makes a deleted note take its chunks with it, and a polymorphic id
    cannot have one.
    """

    __table_args__ = (
        UniqueConstraint("note_id", "doc_version", "chunk_index", name="uq_note_chunk"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    note_id: uuid.UUID = Field(
        foreign_key="note.id", nullable=False, ondelete="CASCADE", index=True
    )
    doc_version: int
    chunk_index: int
    title: str = Field(default="", max_length=NOTE_TITLE_MAX)
    text: str = Field(sa_type=Text)
    char_count: int = 0
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class NoteEmbeddingJob(SQLModel, table=True):
    """One indexing run for one note.

    A parallel table to `embeddingjob` rather than a nullable `note_id` on it.
    Eight functions in the worker load a Document from `job.document_id` and
    compare versions; making that column optional puts a branch in every one of
    them, on the hottest table in the system, where a missed branch fails
    silently - a note stuck mid-stage, or the wrong entity marked failed.
    Document indexing is the product and notes are new, so the blast radius is
    kept at zero. `ImportJob` is the same decision made for the same reason.

    No `chunking_method`: a note is never chunked by the LLM. See
    app/worker/note_pipeline.py for why that matters.
    """

    __table_args__ = (
        Index("ix_noteembeddingjob_status_run_after", "status", "run_after"),
        Index("ix_noteembeddingjob_note_created", "note_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    note_id: uuid.UUID = Field(
        foreign_key="note.id", nullable=False, ondelete="CASCADE"
    )
    doc_version: int
    status: JobStatus = Field(default=JobStatus.queued, sa_type=String(32))  # type: ignore
    stage: JobStage | None = Field(default=None, sa_type=String(32))  # type: ignore
    progress: int = 0
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime = _tz_datetime(default_factory=get_datetime_utc)
    cancel_requested: bool = False
    locked_by: str | None = Field(default=None, max_length=200)
    locked_at: datetime | None = _tz_datetime(default=None)
    heartbeat_at: datetime | None = _tz_datetime(default=None)
    started_at: datetime | None = _tz_datetime(default=None)
    finished_at: datetime | None = _tz_datetime(default=None)
    error: str | None = Field(default=None, sa_type=Text)
    chunk_count: int | None = None
    stats: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


# ---------------------------------------------------------------------------
# Reminders
#
# A note that comes back to you. Stored as a wall clock and a zone rather than
# an instant, because "every day at nine" means nine o'clock in March and nine
# o'clock in July, and an instant does not.
# ---------------------------------------------------------------------------


class ReminderRecurrence(StrEnum):
    none = "none"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class ReminderEnds(StrEnum):
    never = "never"
    on_date = "on_date"
    after = "after"


class ReminderStatus(StrEnum):
    active = "active"
    # The note was archived, or the account cannot receive mail. Kept rather
    # than deleted so the interface can say why nothing is arriving.
    paused = "paused"
    done = "done"
    cancelled = "cancelled"


class NoteReminder(SQLModel, table=True):
    __table_args__ = (
        # The claim query and nothing else. Partial, so the scan only ever
        # touches rows that could actually fire.
        Index(
            "ix_notereminder_due",
            "next_run_at",
            postgresql_where=text("status = 'active'"),
        ),
        # One per note. Two reminders on one note is a feature nobody asked for
        # and a second way to send the same mail twice.
        UniqueConstraint("note_id", name="uq_notereminder_note"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    note_id: uuid.UUID = Field(
        foreign_key="note.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )

    # The wall clock somebody chose, and the zone they chose it in. Snapshotted
    # rather than read from the profile at send time: a reminder set as "9am in
    # Berlin" must not move because its owner later opened the app in Singapore.
    local_time: time = Field(sa_type=Time)
    timezone: str = Field(max_length=64)
    # The local date of the first occurrence. Every later one is derived from
    # this and never from the previous one, which is what stops a monthly
    # reminder on the 31st collapsing to the 28th for ever after February.
    anchor_date: date = Field(sa_type=Date)

    recurrence: ReminderRecurrence = Field(
        default=ReminderRecurrence.none,
        sa_type=String(12),  # type: ignore
    )
    ends: ReminderEnds = Field(default=ReminderEnds.never, sa_type=String(12))  # type: ignore
    ends_on: date | None = Field(default=None, sa_type=Date)
    ends_after: int | None = None

    # The instant, in UTC, that the wall clock above names. Shown to the reader,
    # so it is never used as a lease - see `locked_until`.
    next_run_at: datetime = _tz_datetime(nullable=False)
    next_local_date: date = Field(sa_type=Date)
    # The lease. `cleanuptask` leases by pushing its `run_after` forward, which
    # works because that column means only "when to try next". This one is on
    # screen, and moving it during a send would make the interface lie.
    locked_until: datetime | None = _tz_datetime(default=None)

    status: ReminderStatus = Field(
        default=ReminderStatus.active,
        sa_type=String(12),  # type: ignore
    )
    sent_count: int = 0
    attempts: int = 0
    last_sent_at: datetime | None = _tz_datetime(default=None)
    last_error: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    updated_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class NoteReminderDelivery(SQLModel, table=True):
    """One row per occurrence that was claimed. The unique key is the guard.

    Email cannot be made atomic with a commit, so this picks a side: the row is
    written and committed *before* the send. A crash in between loses that
    occurrence, which is observable as `sent_at IS NULL`. The other way round
    would risk sending twice, and a duplicate reminder costs the trust of every
    later one.
    """

    __table_args__ = (
        UniqueConstraint(
            "reminder_id", "occurrence_at", name="uq_reminderdelivery_occurrence"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    reminder_id: uuid.UUID = Field(
        foreign_key="notereminder.id", nullable=False, ondelete="CASCADE"
    )
    # The instant this is the delivery *of*, not when it was sent.
    occurrence_at: datetime = _tz_datetime(nullable=False)
    # Occurrences that went by while nothing was running, folded into this one.
    skipped: int = 0
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)
    sent_at: datetime | None = _tz_datetime(default=None)
    error: str | None = Field(default=None, sa_type=Text)


class CapturedEmailRow(SQLModel, table=True):
    """Mail the logging sender kept, visible across processes.

    `LoggingEmailSender` keeps messages in a list belonging to one process, and
    the worker is not the process the dev mailbox endpoint runs in. Nothing has
    ever emailed from the worker before, so this has never mattered; a reminder
    is the first thing that does, and without this a test polling the mailbox
    would poll an empty one for ever.

    Written only in development, and inert everywhere else.
    """

    __table_args__ = (
        Index("ix_capturedemailrow_to_created", "to_email", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    to_email: str = Field(max_length=320)
    subject: str = Field(max_length=500)
    text: str = Field(sa_type=Text)
    created_at: datetime = _tz_datetime(default_factory=get_datetime_utc)


class NoteReminderUpsert(SQLModel):
    """Set or replace a note's reminder."""

    # A naive local wall clock, deliberately. An instant plus a zone is
    # ambiguous about which clock reading was meant, and that ambiguity is
    # exactly what breaks across a daylight-saving boundary.
    at: datetime
    timezone: str = Field(max_length=64)
    recurrence: ReminderRecurrence = ReminderRecurrence.none
    ends: ReminderEnds = ReminderEnds.never
    ends_on: date | None = None
    ends_after: int | None = Field(default=None, ge=1, le=500)


class NoteReminderPublic(SQLModel):
    id: uuid.UUID
    note_id: uuid.UUID
    next_run_at: datetime
    local_time: time
    timezone: str
    recurrence: ReminderRecurrence
    ends: ReminderEnds
    ends_on: date | None = None
    ends_after: int | None = None
    status: ReminderStatus
    sent_count: int
    last_sent_at: datetime | None = None
    # Why a paused reminder is paused, so the interface can explain itself.
    last_error: str | None = None
