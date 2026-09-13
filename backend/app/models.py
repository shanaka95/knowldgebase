import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import EmailStr
from sqlalchemy import (
    BigInteger,
    Column,
    Computed,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
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
    max_shares_per_document: int | None = Field(default=None, ge=0, le=10_000)
    max_members_per_space: int | None = Field(default=None, ge=0, le=10_000)


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
    # How many people one of this account's pages may be shared with, counting
    # invitations that have not been accepted yet. Per account rather than
    # global so it can follow a plan later without another migration.
    max_shares_per_document: int = Field(default=50)
    # The same idea for a whole space. Separate from the per-page limit because
    # they are different decisions: a space is a bigger thing to hand over.
    max_members_per_space: int = Field(default=50)

    namespaces: list[Namespace] = Relationship(
        back_populates="owner", cascade_delete=True
    )
    api_keys: list[ApiKey] = Relationship(back_populates="user", cascade_delete=True)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    email_verified_at: datetime | None = None
    max_shares_per_document: int = 50
    max_members_per_space: int = 50


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
    summary: str | None = Field(default=None, sa_type=Text)
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
                "setweight(to_tsvector('english', left(coalesce(content_text, ''), 500000)), 'B')",
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


class DocumentPublic(DocumentSummaryPublic):
    content_html: str
    content_text: str
    summary: str | None = None
    updated_by_user: UserRef | None = None
    created_by_user: UserRef | None = None
    source_attachment: AttachmentPublic | None = None


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


class RetrievalSourceReport(SQLModel):
    method: str
    target: str
    hits: int
    took_ms: float
    error: str | None = None


class RetrievalHit(SQLModel):
    document_id: uuid.UUID
    title: str
    doc_type: str | None = None
    namespace_id: uuid.UUID
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


class AskCitation(SQLModel):
    """One excerpt the model was given, numbered as it appears in the answer."""

    index: int
    document_id: uuid.UUID
    title: str
    namespace_id: uuid.UUID
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

    connections: list["ChannelConnection"] = Relationship(
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


class GoogleDrivePickedFile(SQLModel):
    file_id: str = Field(min_length=1, max_length=255)
    name: str = Field(default="", max_length=255)
    mime_type: str = Field(default="", max_length=127)


class GoogleDriveImportRequest(SQLModel):
    files: list[GoogleDrivePickedFile] = Field(min_length=1, max_length=25)
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    doc_type: str | None = Field(default=None, max_length=100)
    prompt: str | None = Field(default=None, max_length=2000)
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
