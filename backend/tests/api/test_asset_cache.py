"""What the origin says about caching a built asset — and about failing to serve one.

The header on a *hit* is uncontroversial: the filename is a content hash, so the
URL can never mean anything else. The header on a *miss* is the whole point of
these tests. `immutable` on a 404 is a year-long instruction not to ask again,
and chunk filenames survive a rebuild when their content does, so a single
failure cached during one deploy goes on breaking builds that did not exist yet.
That is how /search became permanently unloadable for one person while every one
of its chunks answered 200 to everybody else.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse, StreamingResponse

from app.main import FRONTEND_DIR, AssetCacheHeaders

IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def stub() -> TestClient:
    """An app that answers with whatever status a test asks for.

    Stubbed rather than driven through the real static files, because the point
    is the relationship between status and header, and a test that can only run
    where a frontend has been built is a test that quietly stops running.
    """
    app = FastAPI()

    @app.get("/assets/{name}")
    def asset(name: str, status: int = 200) -> PlainTextResponse:
        return PlainTextResponse(f"// {name}", status_code=status)

    @app.get("/api/v1/stream")
    def stream() -> StreamingResponse:
        def chunks():
            yield b"data: one\n\n"
            yield b"data: two\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    app.add_middleware(AssetCacheHeaders)
    return TestClient(app)


@pytest.mark.parametrize("status", [200, 206, 304])
def test_an_asset_that_was_served_is_cached_for_ever(
    stub: TestClient, status: int
) -> None:
    response = stub.get(f"/assets/index-abc123.js?status={status}")
    assert response.headers["cache-control"] == IMMUTABLE


@pytest.mark.parametrize("status", [404, 403, 500, 502, 503])
def test_a_failure_to_serve_one_is_never_cached(stub: TestClient, status: int) -> None:
    """The regression test for the bug this file exists for.

    A 404 from a deploy window, or a 502 from a container that has not finished
    starting, must not be remembered — least of all under `immutable`, which
    tells the browser not to revalidate even when somebody reloads.
    """
    response = stub.get(f"/assets/index-abc123.js?status={status}")
    assert response.headers["cache-control"] == "no-store"
    assert "immutable" not in response.headers["cache-control"]


def test_nothing_outside_assets_is_touched(stub: TestClient) -> None:
    """The API decides its own caching; this middleware has one job."""
    response = stub.get("/api/v1/stream")
    assert "cache-control" not in response.headers


def test_an_event_stream_arrives_intact(stub: TestClient) -> None:
    with stub.stream("GET", "/api/v1/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.read() == b"data: one\n\ndata: two\n\n"


@pytest.mark.anyio
async def test_a_request_it_does_not_care_about_is_not_wrapped_at_all() -> None:
    """The reason this is raw ASGI rather than `@app.middleware("http")`.

    `BaseHTTPMiddleware` wraps every response body, which is what interferes
    with the server-sent events an answer streams over. Asserting on chunk
    boundaries through the test client proves nothing - the transport coalesces
    them either way - so the claim is made where it is true: for anything that
    is not an asset, the application is handed the very `send` it would have had
    if this middleware were not installed.
    """
    seen: list[object] = []

    async def app(_scope, _receive, send) -> None:  # type: ignore[no-untyped-def]
        seen.append(send)

    async def send(message) -> None:  # type: ignore[no-untyped-def]
        pass

    async def receive():  # type: ignore[no-untyped-def]
        return {"type": "http.request"}

    middleware = AssetCacheHeaders(app)
    await middleware({"type": "http", "path": "/api/v1/ask"}, receive, send)
    assert seen == [send], "a non-asset request must pass through untouched"

    await middleware({"type": "http", "path": "/assets/x.js"}, receive, send)
    assert seen[1] is not send, "an asset request is the one that gets a header"


@pytest.mark.skipif(
    not (FRONTEND_DIR / "index.html").exists(), reason="no frontend build"
)
def test_the_real_application_agrees(client: TestClient) -> None:
    """End to end, against the files actually mounted."""
    built = next(iter(sorted((FRONTEND_DIR / "assets").glob("*.js"))), None)
    assert built is not None, "a build with no javascript is not a build"

    served = client.get(f"/assets/{Path(built).name}")
    assert served.status_code == 200
    assert served.headers["cache-control"] == IMMUTABLE

    missing = client.get("/assets/index-doesnotexist.js")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
