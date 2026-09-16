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
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse, StreamingResponse

from app.main import FRONTEND_DIR, AssetCacheHeaders, vary_without_origin
from app.main import app as main_app

IMMUTABLE = "public, max-age=31536000, immutable"
ALLOWED_ORIGIN = "https://plusgpt.io"


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


@pytest.fixture
def cors_stub() -> TestClient:
    """An asset served through the same middleware stack as the real app.

    The order is the point, so it is written the way `app.main` writes it: CORS
    first, this middleware last and therefore outermost. Reverse the two and the
    assertions below fail, which is the regression being pinned.
    """
    app = FastAPI()

    @app.get("/assets/{name}")
    def asset(name: str) -> PlainTextResponse:
        return PlainTextResponse(f"// {name}", headers={"vary": "Accept-Encoding"})

    @app.get("/api/v1/ping")
    def ping() -> PlainTextResponse:
        return PlainTextResponse("pong")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AssetCacheHeaders)
    return TestClient(app)


def test_an_asset_has_one_copy_whoever_asks(cors_stub: TestClient) -> None:
    """The bug this half of the middleware exists for.

    Browsers fetch the module graph in CORS mode, because Vite marks the entry
    `crossorigin`. While the origin answered `Vary: Origin`, that gave the CDN a
    second copy of every asset, reachable only with an `Origin` header - so a
    502 cached into it was invisible to curl, to uptime checks and to a purge by
    URL, and `/search` was 200 to everyone measuring and 502 to everyone
    browsing. One copy, or the checks are checking something nobody loads.
    """
    response = cors_stub.get(
        "/assets/collapsible-abc123.js", headers={"Origin": ALLOWED_ORIGIN}
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
    assert "origin" not in response.headers.get("vary", "").lower()


def test_the_rest_of_vary_survives(cors_stub: TestClient) -> None:
    """`Origin` is removed from the list, not the list from the response.

    `Accept-Encoding` is how the CDN keeps the gzip and brotli copies apart;
    dropping it would let it answer one with the other.
    """
    response = cors_stub.get(
        "/assets/collapsible-abc123.js", headers={"Origin": ALLOWED_ORIGIN}
    )
    assert response.headers["vary"] == "Accept-Encoding"


def test_the_api_still_gets_its_cors_headers(cors_stub: TestClient) -> None:
    """Only assets are same-origin by construction. The API is called across it."""
    response = cors_stub.get("/api/v1/ping", headers={"Origin": ALLOWED_ORIGIN})
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.parametrize(
    ("vary", "expected"),
    [
        (b"Origin", b""),
        (b"origin", b""),
        (b"Origin, Accept-Encoding", b"Accept-Encoding"),
        (b"Accept-Encoding, Origin", b"Accept-Encoding"),
        (b"Accept-Encoding", b"Accept-Encoding"),
        (b"Accept-Encoding,  Origin , Cookie", b"Accept-Encoding, Cookie"),
    ],
)
def test_vary_without_origin(vary: bytes, expected: bytes) -> None:
    assert vary_without_origin(vary) == expected


def test_the_real_app_puts_this_middleware_outside_cors() -> None:
    """Order is load-bearing and silent when wrong.

    Added before `CORSMiddleware` this runs *underneath* it: the headers would
    be stamped back on after the stripping, the second copy would come back, and
    every assertion above would still pass in isolation.
    """
    installed = [middleware.cls for middleware in main_app.user_middleware]
    assert installed.index(AssetCacheHeaders) < installed.index(CORSMiddleware), (
        "AssetCacheHeaders must be added last, so it is outermost"
    )
