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

    namespaces: list[Namespace] = Relationship(
        back_populates="owner", cascade_delete=True
    )
    api_keys: list[ApiKey] = Relationship(back_populates="user", cascade_delete=True)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


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
    document_count: int = 0
    member_count: int = 0
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


class DocumentCreate(SQLModel):
    namespace_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    content_format: ContentFormat = ContentFormat.html


class DocumentUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = None
    content_format: ContentFormat = ContentFormat.html
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
    folder_id: uuid.UUID | None = None
    title: str
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


class NamespaceTree(SQLModel):
    namespace: NamespacePublic
    folders: list[FolderPublic]
    documents: list[DocumentSummaryPublic]


class SharedWithMe(SQLModel):
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
    prompt: str | None = None
    filename: str
    content_type: str
    size: int
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


class AskAnswer(SQLModel):
    question: str
    answer: str
    citations: list[AskCitation] = []
    searched: int = 0  # pages the hybrid search returned
    used: int = 0  # distinct pages that contributed an excerpt
    passages: int = 0  # excerpts sent to the model; a long page can give several
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
