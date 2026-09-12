"""PDF/image rendering and MinerU block -> HTML conversion."""

from __future__ import annotations

import io

import httpx
import pytest
import respx

from app.core.content import html_to_text, sanitize_html
from app.services.parsing import (
    MinerUParser,
    UnsupportedFileType,
    blocks_to_html,
    image_to_data_url,
    is_pdf,
    is_supported,
    render_pages,
)


def _png(size: tuple[int, int] = (30, 20)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (200, 210, 220)).save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------- typing


def test_recognises_supported_types() -> None:
    assert is_pdf("application/pdf")
    assert is_pdf("application/octet-stream", "report.PDF")
    assert is_supported("image/png")
    assert is_supported("image/jpeg", "scan.jpg")
    assert not is_supported("text/plain", "notes.txt")
    assert not is_supported("application/zip", "bundle.zip")


def test_unsupported_type_is_rejected_on_render() -> None:
    with pytest.raises(UnsupportedFileType):
        render_pages(b"not a document", "application/zip", filename="x.zip")


# ------------------------------------------------------------------ rendering


def test_renders_an_image_as_a_single_page() -> None:
    pages = render_pages(_png(), "image/png", filename="scan.png")
    assert len(pages) == 1
    assert pages[0].size == (30, 20)


def test_image_becomes_a_data_url() -> None:
    url = image_to_data_url(render_pages(_png(), "image/png")[0])
    assert url.startswith("data:image/png;base64,")


# ---------------------------------------------------------- blocks -> HTML


def test_blocks_become_structured_html() -> None:
    html = blocks_to_html(
        [
            {"type": "title", "content": "Quarterly Report"},
            {"type": "text", "content": "Availability reached 99.94%."},
            {"type": "title", "content": "Costs"},
            {
                "type": "table",
                "content": "<table><tr><td>Compute</td><td>57,500</td></tr></table>",
            },
            {"type": "text", "content": "- Move batch jobs to spot instances."},
            {"type": "text", "content": "• Right-size the staging cluster."},
            {"type": "equation", "content": "E = mc^2"},
        ]
    )
    # the first title is the page heading, later ones are sections
    assert html.count("<h1>") == 1
    assert "<h1>Quarterly Report</h1>" in html
    assert "<h2>Costs</h2>" in html
    # tables survive as tables, not as escaped text
    assert "<table>" in html and "&lt;table&gt;" not in html
    # consecutive bullet lines are regrouped into one list
    assert html.count("<ul>") == 1
    assert "<li>Move batch jobs to spot instances.</li>" in html
    assert "<li>Right-size the staging cluster.</li>" in html
    assert "<code>E = mc^2</code>" in html


def test_block_html_survives_the_sanitiser() -> None:
    html = sanitize_html(
        blocks_to_html(
            [
                {"type": "title", "content": "Invoice"},
                {
                    "type": "table",
                    "content": "<table><tr><th>Item</th><td>Widget</td></tr></table>",
                },
            ]
        )
    )
    assert "<h1>Invoice" in html
    assert "<th>Item</th>" in html
    assert "Widget" in html_to_text(html)


def test_block_text_is_escaped() -> None:
    html = blocks_to_html([{"type": "text", "content": "<script>alert(1)</script> ok"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_pictures_are_skipped_but_captions_survive() -> None:
    html = blocks_to_html(
        [
            {"type": "image", "content": "a photo of a server rack"},
            {"type": "text", "content": "Figure 1: the rack"},
        ]
    )
    assert "photo of a server rack" not in html
    assert "Figure 1" in html


def test_empty_and_missing_content_is_ignored() -> None:
    assert blocks_to_html([]) == ""
    assert blocks_to_html([{"type": "text", "content": None}]) == ""
    assert blocks_to_html([{"type": "text", "content": "   "}]) == ""


# -------------------------------------------------------------- availability


@pytest.mark.anyio
async def test_parser_reports_unavailable_when_the_server_is_down() -> None:
    parser = MinerUParser(base_url="http://parser.invalid/v1", model="m")
    with respx.mock:
        respx.get("http://parser.invalid/v1/models").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert await parser.available() is False


@pytest.mark.anyio
async def test_parser_discovers_the_model_name_when_not_configured() -> None:
    """mlx-vlm names a model by its path, which differs per machine."""
    parser = MinerUParser(base_url="http://parser.test/v1", model="")
    with respx.mock:
        respx.get("http://parser.test/v1/models").mock(
            return_value=httpx.Response(
                200, json={"object": "list", "data": [{"id": "/models/MinerU2.5"}]}
            )
        )
        assert await parser.available() is True
    assert parser._resolved_model == "/models/MinerU2.5"


@pytest.mark.anyio
async def test_configured_model_is_not_overridden_by_discovery() -> None:
    parser = MinerUParser(base_url="http://parser.test/v1", model="my-parser")
    with respx.mock:
        respx.get("http://parser.test/v1/models").mock(
            return_value=httpx.Response(
                200, json={"object": "list", "data": [{"id": "something-else"}]}
            )
        )
        assert await parser.available() is True
    assert parser._resolved_model == "my-parser"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_parser_backend_llm_never_calls_mineru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment without a MinerU server parses pages with the chat model."""
    from app.core.config import settings
    from app.services.parsing import parse_document

    monkeypatch.setattr(settings, "IMPORT_PARSER", "llm")

    class NeverAvailable(MinerUParser):
        def __init__(self) -> None:
            super().__init__(base_url="http://unused/v1", model="x")
            self.probed = False

        async def available(self) -> bool:
            self.probed = True
            return True  # even if it would work, "llm" must not use it

    class FakeLLM:
        def __init__(self) -> None:
            self.pages = 0

        async def parse_page(
            self, image: object, prompt: str | None = None
        ) -> tuple[str, int]:
            self.pages += 1
            return "<p>transcribed by the chat model</p>", 1

    mineru, llm = NeverAvailable(), FakeLLM()
    parsed = await parse_document(
        _png(),
        "image/png",
        filename="scan.png",
        mineru=mineru,
        llm=llm,  # type: ignore[arg-type]
    )

    assert parsed.parser == "llm"
    assert llm.pages == 1
    assert not mineru.probed, "the parser endpoint is not even contacted"
    assert "transcribed by the chat model" in parsed.html


@pytest.mark.anyio
async def test_parser_backend_mineru_refuses_to_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asking for MinerU explicitly must not silently degrade to the chat model."""
    from app.core.config import settings
    from app.services.model_client import ModelServerError
    from app.services.parsing import parse_document

    monkeypatch.setattr(settings, "IMPORT_PARSER", "mineru")

    class Down(MinerUParser):
        async def available(self) -> bool:
            return False

    with pytest.raises(ModelServerError):
        await parse_document(
            _png(),
            "image/png",
            filename="scan.png",
            mineru=Down(base_url="http://down/v1", model="m"),
        )
