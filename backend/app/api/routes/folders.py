import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, col, select

from app.api.deps import AuthDep, SessionDep, WriteAuth
from app.api.serializers import role_for_documents, to_document_summary
from app.core.permissions import require_folder, require_namespace
from app.models import (
    CleanupKind,
    CleanupTask,
    Document,
    DocumentSummaryPublic,
    Folder,
    FolderCreate,
    FolderPublic,
    FolderUpdate,
    Message,
)

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderContents(FolderPublic):
    folders: list[FolderPublic] = []
    documents: list[DocumentSummaryPublic] = []
    path: list[FolderPublic] = []  # ancestors, root first


def folder_ancestors(session: Session, folder: Folder) -> list[Folder]:
    path: list[Folder] = []
    current = folder
    seen: set[uuid.UUID] = set()
    while current.parent_id is not None and current.parent_id not in seen:
        seen.add(current.parent_id)
        parent = session.get(Folder, current.parent_id)
        if parent is None:
            break
        path.append(parent)
        current = parent
    path.reverse()
    return path


def descendant_folder_ids(session: Session, folder_id: uuid.UUID) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = {folder_id}
    frontier = [folder_id]
    while frontier:
        children = session.exec(
            select(Folder.id).where(col(Folder.parent_id).in_(frontier))
        ).all()
        new = [c for c in children if c not in ids]
        ids.update(new)
        frontier = new
    return ids


def enqueue_folder_cleanup(session: Session, folder_id: uuid.UUID) -> None:
    ids = descendant_folder_ids(session, folder_id)
    docs = session.exec(
        select(Document.id, Document.namespace_id).where(
            col(Document.folder_id).in_(ids)
        )
    ).all()
    for doc_id, ns_id in docs:
        session.add(
            CleanupTask(
                kind=CleanupKind.qdrant_document,
                payload={"document_id": str(doc_id), "namespace_id": str(ns_id)},
            )
        )


@router.post("/", response_model=FolderPublic)
def create_folder(session: SessionDep, auth: WriteAuth, folder_in: FolderCreate) -> Any:
    namespace, _ = require_namespace(
        session, auth.user, folder_in.namespace_id, "editor"
    )
    if folder_in.parent_id is not None:
        parent = session.get(Folder, folder_in.parent_id)
        if parent is None or parent.namespace_id != namespace.id:
            raise HTTPException(
                status_code=400, detail="Parent folder not in this namespace"
            )
    folder = Folder(
        name=folder_in.name,
        namespace_id=namespace.id,
        parent_id=folder_in.parent_id,
        created_by=auth.user.id,
    )
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


@router.get("/{folder_id}", response_model=FolderContents)
def read_folder(session: SessionDep, auth: AuthDep, folder_id: uuid.UUID) -> Any:
    """A folder with its direct children (folders + documents) and ancestor path."""
    folder, namespace, _ = require_folder(session, auth.user, folder_id, "viewer")
    children = session.exec(
        select(Folder).where(Folder.parent_id == folder.id).order_by(col(Folder.name))
    ).all()
    documents = session.exec(
        select(Document)
        .where(Document.folder_id == folder.id)
        .order_by(col(Document.title))
    ).all()
    doc_role = role_for_documents(session, auth.user, namespace)
    return FolderContents(
        **FolderPublic.model_validate(folder).model_dump(),
        folders=[FolderPublic.model_validate(f) for f in children],
        documents=[to_document_summary(d, doc_role) for d in documents],
        path=[
            FolderPublic.model_validate(f) for f in folder_ancestors(session, folder)
        ],
    )


@router.patch("/{folder_id}", response_model=FolderPublic)
def update_folder(
    session: SessionDep, auth: WriteAuth, folder_id: uuid.UUID, folder_in: FolderUpdate
) -> Any:
    """Rename and/or move a folder (``parent_id`` or ``move_to_root``)."""
    folder, namespace, _ = require_folder(session, auth.user, folder_id, "editor")
    if folder_in.name is not None:
        folder.name = folder_in.name
    if folder_in.move_to_root:
        folder.parent_id = None
    elif folder_in.parent_id is not None and folder_in.parent_id != folder.parent_id:
        if folder_in.parent_id == folder.id:
            raise HTTPException(
                status_code=400, detail="A folder cannot be its own parent"
            )
        parent = session.get(Folder, folder_in.parent_id)
        if parent is None or parent.namespace_id != namespace.id:
            raise HTTPException(
                status_code=400, detail="Parent folder not in this namespace"
            )
        if parent.id in descendant_folder_ids(session, folder.id):
            raise HTTPException(
                status_code=400, detail="Cannot move a folder into its own subtree"
            )
        folder.parent_id = parent.id
    folder.updated_at = datetime.now(UTC)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


@router.delete("/{folder_id}")
def delete_folder(
    session: SessionDep, auth: WriteAuth, folder_id: uuid.UUID
) -> Message:
    """Delete a folder and everything below it."""
    folder, _, _ = require_folder(session, auth.user, folder_id, "editor")
    enqueue_folder_cleanup(session, folder.id)
    session.delete(folder)
    session.commit()
    return Message(message="Folder deleted successfully")
