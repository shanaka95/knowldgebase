"""List endpoints must not get slower as a person accumulates content.

These are guard rails, not micro-benchmarks. The numbers are deliberately loose;
what they catch is the shape of the problem - a query per row - which is
invisible with three spaces and painful with forty.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session

from app.core.db import engine
from tests.utils.kb import (
    API,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)


@pytest.fixture
def sql_counter() -> Iterator[list[int]]:
    """Counts statements actually sent to Postgres during a request."""
    count = [0]

    def _count(*_: Any, **__: Any) -> None:
        count[0] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        yield count
    finally:
        event.remove(engine, "before_cursor_execute", _count)


def test_listing_spaces_costs_the_same_whether_you_have_two_or_twenty(
    client: TestClient, db: Session, sql_counter: list[int]
) -> None:
    """Serialising a space used to cost three queries, so a list cost 3N."""
    user, password = create_user_with_password(db)
    for i in range(2):
        create_namespace(db, user, f"Small {i}")
    db.commit()
    headers = login(client, user, password)

    sql_counter[0] = 0
    assert client.get(f"{API}/namespaces/", headers=headers).status_code == 200
    small = sql_counter[0]

    for i in range(18):
        create_namespace(db, user, f"Big {i}")
    db.commit()

    sql_counter[0] = 0
    r = client.get(f"{API}/namespaces/", headers=headers)
    assert r.status_code == 200
    assert r.json()["count"] >= 20
    big = sql_counter[0]

    assert big <= small + 2, (
        f"listing 20 spaces took {big} queries against {small} for 2: "
        "the cost is growing with the number of rows"
    )


def test_the_page_list_does_not_query_per_page(
    client: TestClient, db: Session, sql_counter: list[int]
) -> None:
    user, password = create_user_with_password(db)
    ns = create_namespace(db, user)
    for i in range(2):
        create_document(db, ns, user, title=f"Small {i}")
    db.commit()
    headers = login(client, user, password)
    params = {"namespace_id": str(ns.id)}

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/documents/", headers=headers, params=params).status_code
        == 200
    )
    small = sql_counter[0]

    for i in range(20):
        create_document(db, ns, user, title=f"Big {i}")
    db.commit()

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/documents/", headers=headers, params=params).status_code
        == 200
    )
    assert sql_counter[0] <= small + 2, (
        f"{sql_counter[0]} queries for 22 pages against {small} for 2"
    )


def test_the_space_tree_does_not_query_per_page(
    client: TestClient, db: Session, sql_counter: list[int]
) -> None:
    """The tree loads on every navigation, so it is the hottest read here."""
    user, password = create_user_with_password(db)
    ns = create_namespace(db, user)
    for i in range(2):
        create_document(db, ns, user, title=f"Small {i}")
    db.commit()
    headers = login(client, user, password)

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers).status_code == 200
    )
    small = sql_counter[0]

    for i in range(20):
        create_document(db, ns, user, title=f"Big {i}")
    db.commit()

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/namespaces/{ns.id}/tree", headers=headers).status_code == 200
    )
    assert sql_counter[0] <= small + 2, (
        f"{sql_counter[0]} queries for a 22-page tree against {small} for 2"
    )


def test_shared_with_me_does_not_query_per_item(
    client: TestClient, db: Session, sql_counter: list[int]
) -> None:
    from app.models import NamespaceRole
    from tests.utils.kb import add_member

    owner, _ = create_user_with_password(db)
    guest, password = create_user_with_password(db)
    for i in range(2):
        add_member(
            db, create_namespace(db, owner, f"Small {i}"), guest, NamespaceRole.viewer
        )
    db.commit()
    headers = login(client, guest, password)

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/documents/shared-with-me", headers=headers).status_code
        == 200
    )
    small = sql_counter[0]

    for i in range(18):
        add_member(
            db, create_namespace(db, owner, f"Big {i}"), guest, NamespaceRole.viewer
        )
    db.commit()

    sql_counter[0] = 0
    assert (
        client.get(f"{API}/documents/shared-with-me", headers=headers).status_code
        == 200
    )
    assert sql_counter[0] <= small + 2, (
        f"{sql_counter[0]} queries for 20 shared spaces against {small} for 2"
    )
