from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.kb import (
    API,
    create_document,
    create_namespace,
    create_user_with_password,
    login,
)


def test_search_ranks_title_hits_and_respects_access(
    client: TestClient, db: Session
) -> None:
    owner, pw = create_user_with_password(db)
    other, _ = create_user_with_password(db)
    ns = create_namespace(db, owner)
    hidden_ns = create_namespace(db, other)
    title_hit = create_document(
        db,
        ns,
        owner,
        title="Kubernetes deployment guide",
        html="<p>Steps to roll out.</p>",
    )
    body_hit = create_document(
        db,
        ns,
        owner,
        title="Ops runbook",
        html="<p>We deploy services on kubernetes clusters nightly.</p>",
    )
    create_document(db, ns, owner, title="Unrelated", html="<p>Cooking pasta.</p>")
    create_document(
        db, hidden_ns, other, title="Secret kubernetes plans", html="<p>kubernetes</p>"
    )

    h = login(client, owner, pw)
    r = client.get(f"{API}/search/", headers=h, params={"q": "kubernetes"})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [d["document_id"] for d in body["data"]]
    assert ids[0] == str(title_hit.id)
    assert str(body_hit.id) in ids
    assert body["count"] == 2
    assert all(d["namespace_slug"] == ns.slug for d in body["data"])
    snippet = next(d for d in body["data"] if d["document_id"] == str(body_hit.id))[
        "snippet"
    ]
    assert "<mark>" in snippet

    # partial title match via ILIKE
    r = client.get(f"{API}/search/", headers=h, params={"q": "kuber"})
    assert str(title_hit.id) in [d["document_id"] for d in r.json()["data"]]

    # scoped to namespace
    r = client.get(
        f"{API}/search/",
        headers=h,
        params={"q": "kubernetes", "namespace_id": str(hidden_ns.id)},
    )
    assert r.json()["count"] == 0

    # validation
    assert client.get(f"{API}/search/", headers=h, params={"q": ""}).status_code == 422
    assert client.get(f"{API}/search/", headers=h).status_code == 422


def test_search_phrase_and_no_results(client: TestClient, db: Session) -> None:
    owner, pw = create_user_with_password(db)
    ns = create_namespace(db, owner)
    create_document(
        db, ns, owner, title="Notes", html="<p>the quick brown fox jumps</p>"
    )
    h = login(client, owner, pw)
    r = client.get(f"{API}/search/", headers=h, params={"q": '"brown fox"'})
    assert r.json()["count"] == 1
    r = client.get(f"{API}/search/", headers=h, params={"q": "zzzzqqqq"})
    assert r.json() == {"data": [], "count": 0}
