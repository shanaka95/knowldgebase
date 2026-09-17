import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from slugify import slugify
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import (
    Document,
    EmbeddingJob,
    EmbeddingStatus,
    Folder,
    JobStatus,
    Namespace,
    Note,
    NoteEmbeddingJob,
    User,
    UserCreate,
    UserUpdate,
)

# ---------------------------------------------------------------------------
# Users (template)
# ---------------------------------------------------------------------------


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data: dict[str, Any] = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
        # An administrator resetting someone's password is usually responding to
        # a compromise, so the sessions that password opened have to end too.
        extra_data["session_epoch"] = db_user.session_epoch + 1
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def get_confirmed_user_by_email(*, session: Session, email: str) -> User | None:
    """The account that has *proved* it owns this address, if there is one.

    Anybody may register any address, so a row whose ``email_verified_at`` is
    unset says only that somebody typed it. Handing that account a share would
    give someone else's mail a page meant for the person who reads it, which is
    why sharing looks accounts up this way: access goes to a confirmed identity
    or to nobody, and an unconfirmed address takes the invitation path instead.
    """
    user = get_user_by_email(session=session, email=email)
    if user is None or user.email_verified_at is None:
        return None
    return user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------


def unique_namespace_slug(
    *, session: Session, name: str, exclude_id: uuid.UUID | None = None
) -> str:
    """A URL for a space, unique across the installation.

    Names are the user's own business - two people may both have a space
    called "Visa appointment" - but the URL has to identify one of them. The
    first to take a name gets the clean slug and everybody after gets a short
    random suffix.

    Random rather than counted: `visa-appointment-2` tells whoever lands on it
    that somebody else already has `visa-appointment`, and lets anyone walk
    `-2`, `-3`, `-4` to find out how many. A suffix carries no such meaning.
    """
    base = slugify(name, max_length=100) or "space"
    slug = base
    for _ in range(50):
        stmt = select(Namespace.id).where(Namespace.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Namespace.id != exclude_id)
        if session.exec(stmt).first() is None:
            return slug
        slug = f"{base}-{secrets.token_hex(2)}"
    # Fifty collisions on a random four-character suffix is not a name clash.
    return f"{base}-{uuid.uuid4().hex[:8]}"


# --- names within one space -------------------------------------------------
#
# A space, a folder and a page may all be called the same thing; what may not
# happen is two of the same kind side by side, exactly as in a file manager.
# "Invoices" inside "2025" and "Invoices" inside "2026" are two folders, and
# both are fine.


def _name_taken(
    session: Session,
    model: Any,
    field: Any,
    name: str,
    where: list[Any],
    exclude_id: uuid.UUID | None,
) -> bool:
    stmt = select(model.id).where(func.lower(field) == name.strip().lower(), *where)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return session.exec(stmt).first() is not None


def folder_name_taken(
    session: Session,
    *,
    namespace_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    return _name_taken(
        session,
        Folder,
        Folder.name,
        name,
        [
            Folder.namespace_id == namespace_id,
            col(Folder.parent_id).is_(None)
            if parent_id is None
            else Folder.parent_id == parent_id,
        ],
        exclude_id,
    )


def document_title_taken(
    session: Session,
    *,
    namespace_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    title: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    return _name_taken(
        session,
        Document,
        Document.title,
        title,
        [
            Document.namespace_id == namespace_id,
            col(Document.folder_id).is_(None)
            if folder_id is None
            else Document.folder_id == folder_id,
        ],
        exclude_id,
    )


def available_document_title(
    session: Session,
    *,
    namespace_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    title: str,
) -> str:
    """A free title near the one asked for, by adding "(2)", "(3)"…

    For titles nobody typed: an import names pages after their own headings and
    eight scans of the same form are eight pages called "Invoice". Refusing the
    import over that would be absurd, so they become "Invoice", "Invoice (2)"
    and so on - which is what a file manager does with a duplicate name.

    A title a person did type is refused instead, so they can decide.
    """
    base = title.strip()[:300] or "Untitled"
    candidate = base
    for n in range(2, 200):
        if not document_title_taken(
            session,
            namespace_id=namespace_id,
            folder_id=folder_id,
            title=candidate,
        ):
            return candidate
        suffix = f" ({n})"
        candidate = f"{base[: 300 - len(suffix)]}{suffix}"
    return f"{base[:290]} ({uuid.uuid4().hex[:6]})"


# ---------------------------------------------------------------------------
# Embedding jobs (shared by the API and the worker)
# ---------------------------------------------------------------------------


def enqueue_embedding_job(
    *,
    session: Session,
    document: Document,
    force: bool = False,
    reset_attempts: bool = False,
) -> EmbeddingJob:
    """Schedule (re)generation of embeddings for ``document``'s current version.

    Semantics:
    * A still-queued job for the document is coalesced: it is retargeted at the
      latest version and its ``run_after`` is pushed out by the debounce window
      (autosave storms produce a single job).
    * A running job is asked to cancel (``cancel_requested``); the worker stops
      in-flight work and the new job takes over.
    * ``force`` skips the debounce (used by the manual "regenerate" action).

    Caller is responsible for ``session.commit()``.
    """
    now = datetime.now(UTC)
    debounce = timedelta(seconds=0 if force else settings.EMBEDDING_DEBOUNCE_SECONDS)

    active = session.exec(
        select(EmbeddingJob).where(
            EmbeddingJob.document_id == document.id,
            col(EmbeddingJob.status).in_([JobStatus.queued, JobStatus.running]),
        )
    ).all()

    coalesced: EmbeddingJob | None = None
    for job in active:
        if job.status == JobStatus.queued and not force and not job.cancel_requested:
            job.doc_version = document.version
            job.run_after = now + debounce
            coalesced = job
            session.add(job)
        else:
            job.cancel_requested = True
            if job.status == JobStatus.queued:
                job.status = JobStatus.superseded
                job.finished_at = now
            session.add(job)

    if coalesced is None:
        coalesced = EmbeddingJob(
            document_id=document.id,
            doc_version=document.version,
            status=JobStatus.queued,
            run_after=now + debounce,
            max_attempts=settings.EMBEDDING_MAX_ATTEMPTS,
        )
        session.add(coalesced)

    document.embedding_status = EmbeddingStatus.pending
    document.embedding_error = None
    if reset_attempts:
        document.embedding_attempts = 0
    session.add(document)
    return coalesced


def enqueue_note_embedding_job(
    *,
    session: Session,
    note: Note,
    force: bool = False,
    reset_attempts: bool = False,
) -> NoteEmbeddingJob:
    """Schedule indexing for ``note``'s current version.

    Same contract as `enqueue_embedding_job` - coalesce a queued job, supersede
    a running one - with a shorter debounce. A note is cheap to index (no LLM
    call at all, see app/worker/note_pipeline.py) and the product promises it
    turns up in search almost at once, so waiting ten seconds to batch edits
    would be paying a latency cost to save nothing.

    Caller is responsible for ``session.commit()``.
    """
    now = datetime.now(UTC)
    debounce = timedelta(
        seconds=0 if force else settings.NOTE_EMBEDDING_DEBOUNCE_SECONDS
    )

    active = session.exec(
        select(NoteEmbeddingJob).where(
            NoteEmbeddingJob.note_id == note.id,
            col(NoteEmbeddingJob.status).in_([JobStatus.queued, JobStatus.running]),
        )
    ).all()

    coalesced: NoteEmbeddingJob | None = None
    for job in active:
        if job.status == JobStatus.queued and not force and not job.cancel_requested:
            job.doc_version = note.version
            job.run_after = now + debounce
            coalesced = job
            session.add(job)
        else:
            job.cancel_requested = True
            if job.status == JobStatus.queued:
                job.status = JobStatus.superseded
                job.finished_at = now
            session.add(job)

    if coalesced is None:
        coalesced = NoteEmbeddingJob(
            note_id=note.id,
            doc_version=note.version,
            status=JobStatus.queued,
            run_after=now + debounce,
            max_attempts=settings.EMBEDDING_MAX_ATTEMPTS,
        )
        session.add(coalesced)

    note.embedding_status = EmbeddingStatus.pending
    note.embedding_error = None
    if reset_attempts:
        note.embedding_attempts = 0
    session.add(note)
    return coalesced


_MULTI_WS = re.compile(r"\s+")


def content_changed(
    old_title: str, old_text: str, new_title: str, new_text: str
) -> bool:
    """Only semantic changes (title or plain text) trigger a new version/embedding."""

    def norm(s: str) -> str:
        return _MULTI_WS.sub(" ", s or "").strip()

    return norm(old_title) != norm(new_title) or norm(old_text) != norm(new_text)
