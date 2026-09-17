"""One collection, two kinds of thing, and the line that keeps them apart.

Notes live in the same Qdrant collection as pages, because splitting them would
double the connection handling, the health check and the cleanup kinds for no
ranking benefit. What separates them is a single payload field, and a single
`must_not` in the document filter.

These tests exist because that separation is invisible: if it breaks, nothing
errors. A document search simply starts returning somebody's private note, and
the only thing that would have caught it is this file.

The in-memory store gets the same treatment as the real one. It is what the
entire suite runs against, so a fake that is more permissive than Qdrant would
make every privacy test in the project pass without testing anything.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models import EmbeddingKind
from app.services.sparse import SparseVector
from app.services.vectors import (
    InMemoryVectorStore,
    Point,
    QdrantStore,
    build_payload,
)


def conditions(query_filter: Any) -> list[Any]:
    """The `must` clauses of a filter, or an empty list when there is none."""
    return list(getattr(query_filter, "must", None) or [])


def excludes_notes(query_filter: Any) -> bool:
    """True when this filter cannot match a point marked as a note."""
    for clause in conditions(query_filter):
        for excluded in getattr(clause, "must_not", None) or []:
            if getattr(excluded, "key", None) != "entity_type":
                continue
            match = getattr(excluded, "match", None)
            if getattr(match, "value", None) == "note":
                return True
    return False


# --- the payload -----------------------------------------------------------


def test_a_document_point_says_it_is_a_document() -> None:
    payload = build_payload(
        document_id=uuid.uuid4(),
        namespace_id=uuid.uuid4(),
        kind=EmbeddingKind.document,
        doc_version=1,
        title="Quarterly budget",
    )
    assert payload["entity_type"] == "document"


# --- the real store's filter ------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "namespace_ids", "document_ids"),
    [
        (None, None, None),  # the superuser case: unrestricted, but not of notes
        (str(EmbeddingKind.chunk), None, None),
        (None, ["1ce0a9de-0000-4000-8000-000000000001"], None),
        (None, None, ["1ce0a9de-0000-4000-8000-000000000002"]),
        (
            str(EmbeddingKind.summary),
            ["1ce0a9de-0000-4000-8000-000000000001"],
            ["1ce0a9de-0000-4000-8000-000000000002"],
        ),
    ],
)
def test_every_document_search_excludes_notes(
    kind: str | None,
    namespace_ids: list[str] | None,
    document_ids: list[str] | None,
) -> None:
    """Including the superuser case, which used to produce no filter at all.

    A superuser may read every page in the system. That has never meant they
    may read somebody's private note, and this is the combination where the
    exclusion is easiest to lose: before notes, `(None, None)` returned `None`
    and Qdrant was asked for everything.
    """
    store = QdrantStore.__new__(QdrantStore)  # no client needed to build a filter
    built = store._access_filter(kind, namespace_ids, document_ids)

    assert built is not None, "a document search must always carry a filter"
    assert excludes_notes(built)


def test_no_accessible_spaces_still_short_circuits() -> None:
    """An empty scope means "nothing", and must not become "everything".

    `_query` reads a `None` filter from a restricted call as "this person can
    reach nothing" and returns without querying. Adding a clause that is always
    present could have turned that into a filter object, which would have
    searched the whole corpus instead.
    """
    store = QdrantStore.__new__(QdrantStore)
    assert store._access_filter(None, [], []) is None


# --- the fake ---------------------------------------------------------------


def note_point(pid: str, *, owner: str) -> Point:
    """A point shaped the way the note indexer will write them."""
    return Point(
        id=pid,
        vector=[1.0, 0.0],
        payload={
            "entity_type": "note",
            "note_id": str(uuid.uuid4()),
            "owner_id": owner,
            "kind": str(EmbeddingKind.document),
            "doc_version": 1,
            "title": "Shopping",
        },
        sparse=SparseVector(indices=[1], values=[1.0]),
    )


def document_point(pid: str, *, legacy: bool = False) -> Point:
    payload = build_payload(
        document_id=uuid.uuid4(),
        namespace_id=uuid.uuid4(),
        kind=EmbeddingKind.document,
        doc_version=1,
        title="Quarterly budget",
    )
    if legacy:
        # A point written before notes existed. It carries no `entity_type`,
        # which is precisely the case the exclusion has to let through.
        payload.pop("entity_type")
    return Point(
        id=pid,
        vector=[1.0, 0.0],
        payload=payload,
        sparse=SparseVector(indices=[1], values=[1.0]),
    )


@pytest.mark.anyio
async def test_the_fake_hides_notes_from_a_document_search() -> None:
    store = InMemoryVectorStore()
    await store.upsert([document_point("doc"), note_point("note", owner="anyone")])

    dense = await store.search_dense([1.0, 0.0])
    sparse = await store.search_sparse(SparseVector(indices=[1], values=[1.0]))

    assert [hit.id for hit in dense] == ["doc"]
    assert [hit.id for hit in sparse] == ["doc"]


@pytest.mark.anyio
async def test_a_point_written_before_notes_existed_is_still_found() -> None:
    """The regression test for the rollout.

    The whole reason the filter is an exclusion rather than a positive match is
    so that the existing corpus keeps working untouched. If this fails, every
    page indexed before this change has quietly vanished from search.
    """
    store = InMemoryVectorStore()
    await store.upsert([document_point("legacy", legacy=True)])

    found = await store.search_dense([1.0, 0.0])

    assert [hit.id for hit in found] == ["legacy"]
