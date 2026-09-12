from datetime import UTC, datetime, timedelta

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import HttpUrl
from sqlmodel import Session

from app.core.config import settings
from app.main import app
from app.models import WorkerHeartbeat
from tests.utils.kb import API, create_user_with_password, login


def _reset_cache() -> None:
    if hasattr(app.state, "health_cache"):
        del app.state.health_cache


def test_health_degraded_without_worker_and_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_cache()
    # embedding and LLM may share one gateway URL; give them distinct hosts here
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", HttpUrl("http://embed.test/v1"))
    monkeypatch.setattr(settings, "LLM_BASE_URL", HttpUrl("http://llm.test/v1"))
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://embed.test/v1/models").mock(return_value=Response(503))
        mock.get("http://llm.test/v1/models").mock(
            return_value=Response(200, json={"data": []})
        )
        r = client.get(f"{API}/health/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    s = body["services"]
    assert s["db"]["ok"] is True
    assert s["qdrant"]["ok"] is True  # in-memory fake
    assert s["minio"]["ok"] is True
    assert s["embedding"]["ok"] is False
    assert s["llm"]["ok"] is True
    assert s["worker"]["ok"] is False


def test_health_ok_with_fresh_heartbeat(client: TestClient, db: Session) -> None:
    _reset_cache()
    db.add(
        WorkerHeartbeat(
            name="test:1",
            hostname="test",
            pid=1,
            heartbeat_at=datetime.now(UTC),
            concurrency=2,
            running_jobs=0,
        )
    )
    db.commit()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r".*/models$").mock(
            return_value=Response(200, json={"data": []})
        )
        r = client.get(f"{API}/health/")
    body = r.json()
    assert body["status"] == "ok", body
    assert body["services"]["worker"]["ok"] is True

    # stale heartbeat -> worker offline
    _reset_cache()
    hb = db.get(WorkerHeartbeat, "test:1")
    assert hb is not None
    hb.heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=settings.WORKER_OFFLINE_AFTER_SECONDS + 5
    )
    db.add(hb)
    db.commit()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r".*/models$").mock(
            return_value=Response(200, json={"data": []})
        )
        r = client.get(f"{API}/health/")
    assert r.json()["services"]["worker"]["ok"] is False


def test_workers_endpoint(client: TestClient, db: Session) -> None:
    user, pw = create_user_with_password(db)
    r = client.get(f"{API}/workers/", headers=login(client, user, pw))
    assert r.status_code == 200
    body = r.json()
    assert {"workers", "any_online", "queued_jobs", "running_jobs"} <= set(body)
    assert client.get(f"{API}/workers/").status_code == 401
