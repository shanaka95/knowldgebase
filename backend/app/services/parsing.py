"""Parse uploaded PDFs and images into HTML documents.

Primary parser is **MinerU2.5**, a document-parsing vision model served on the
host (see ``scripts/mineru-server.sh``). It runs a two-step extraction per page:
layout detection, then content recognition per region, returning typed blocks
(title / text / table / list / image / equation) with tables already as HTML.

When MinerU is unreachable and ``IMPORT_FALLBACK_TO_LLM`` is on, the general
multimodal LLM (Qwen3.5-9B) is asked to transcribe the page to Markdown instead.
It is noticeably weaker on tables and layout, so it is only a safety net.

Rendering PDF pages to images happens here (pypdfium2, Apache-licensed); the
models only ever see page images, which is what makes scans work.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.content import markdown_to_html, sanitize_html
from app.models import UsageKind
from app.services.model_client import (
    ModelServerError,
    auth_headers,
    make_http_client,
)
from app.services.usage import UsageMeter

logger = logging.getLogger(__name__)

ParserName = Literal["mineru", "llm"]

PDF_MIME = "application/pdf"
SUPPORTED_IMAGE_MIMES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
    }
)

DEFAULT_PROMPT = (
    "Transcribe this page faithfully. Preserve headings, paragraphs, lists and "
    "tables. Do not summarise, translate or add commentary."
)


@dataclass(slots=True)
class ParsedPage:
    index: int  # 0-based page number
    html: str
    blocks: int
    parser: ParserName


@dataclass(slots=True)
class ParsedDocument:
    html: str
    pages: list[ParsedPage]
    parser: ParserName

    @property
    def page_count(self) -> int:
        return len(self.pages)


class UnsupportedFileType(ValueError):
    pass


_LEADING_H1_RE = re.compile(r"^\s*<h1>(?P<text>.*?)</h1>", re.IGNORECASE | re.DOTALL)


def split_leading_heading(content_html: str) -> tuple[str | None, str]:
    """Peel off a leading ``<h1>`` and return ``(heading_text, rest)``.

    Parsed documents almost always open with their own title. Shown on a page
    that already displays a title, it reads as a duplicate - so the importer uses
    it as the page title instead of repeating it in the body.
    """
    match = _LEADING_H1_RE.match(content_html or "")
    if not match:
        return None, content_html
    heading = html.unescape(re.sub(r"<[^>]+>", "", match.group("text"))).strip()
    if not heading:
        return None, content_html
    return heading, content_html[match.end() :].lstrip()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def is_pdf(content_type: str, filename: str = "") -> bool:
    return content_type == PDF_MIME or filename.lower().endswith(".pdf")


def is_supported(content_type: str, filename: str = "") -> bool:
    return is_pdf(content_type, filename) or content_type in SUPPORTED_IMAGE_MIMES


def render_pages(
    data: bytes,
    content_type: str,
    *,
    filename: str = "",
    dpi: int | None = None,
    max_pages: int | None = None,
) -> list[Any]:
    """Return one RGB PIL image per page (a single image for image uploads)."""
    from PIL import Image

    dpi = dpi or settings.IMPORT_PAGE_DPI
    max_pages = max_pages or settings.IMPORT_MAX_PAGES

    if is_pdf(content_type, filename):
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        pdf = pdfium.PdfDocument(io.BytesIO(data))
        try:
            count = min(len(pdf), max_pages)
            return [
                pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
                for i in range(count)
            ]
        finally:
            pdf.close()

    if content_type in SUPPORTED_IMAGE_MIMES or content_type.startswith("image/"):
        return [Image.open(io.BytesIO(data)).convert("RGB")]

    raise UnsupportedFileType(f"Cannot import files of type {content_type!r}")


def image_to_data_url(image: Any, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    encoded = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/{fmt.lower()};base64,{encoded}"


# ---------------------------------------------------------------------------
# MinerU blocks -> HTML
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*([-*•‣◦·]|\d+[.)])\s+")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("­", "")).strip()


def blocks_to_html(blocks: list[dict[str, Any]]) -> str:
    """Convert MinerU's typed blocks into the HTML we store.

    MinerU marks every heading as ``title`` without a level, so the first title
    on the first page becomes ``<h1>`` and the rest ``<h2>`` - that matches how
    people write pages and keeps the table of contents useful.
    """
    parts: list[str] = []
    pending_list: list[str] = []
    seen_title = False

    def flush_list() -> None:
        nonlocal pending_list
        if pending_list:
            items = "".join(f"<li>{html.escape(i)}</li>" for i in pending_list)
            parts.append(f"<ul>{items}</ul>")
            pending_list = []

    for block in blocks:
        btype = str(block.get("type") or "text")
        content = block.get("content")
        if content is None:
            continue
        text = str(content)

        if btype == "table":
            flush_list()
            # MinerU already emits an HTML table; sanitising happens later.
            parts.append(text.strip())
            continue

        if btype in ("image", "figure"):
            continue  # the picture itself is not transcribed into the text

        if btype == "equation":
            flush_list()
            parts.append(f"<p><code>{html.escape(_clean_text(text))}</code></p>")
            continue

        cleaned = _clean_text(text)
        if not cleaned:
            continue

        if btype == "title":
            flush_list()
            tag = "h1" if not seen_title else "h2"
            seen_title = True
            parts.append(f"<{tag}>{html.escape(cleaned)}</{tag}>")
            continue

        # Bulleted lines arrive as separate "text" blocks; regroup them.
        if _BULLET_RE.match(cleaned):
            pending_list.append(_BULLET_RE.sub("", cleaned))
            continue

        flush_list()
        parts.append(f"<p>{html.escape(cleaned)}</p>")

    flush_list()
    return "".join(parts)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


class MinerUParser:
    """Calls MinerU2.5 through ``mineru-vl-utils``' OpenAI-compatible client."""

    def __init__(
        self,
        base_url: str = str(settings.MINERU_BASE_URL),
        model: str = settings.MINERU_MODEL,
        timeout: float = settings.MINERU_TIMEOUT_SECONDS,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = settings.MINERU_API_KEY if api_key is None else api_key
        self._client: Any | None = None
        self._resolved_model: str | None = model or None

    @property
    def client(self) -> Any:
        if self._client is None:
            from mineru_vl_utils import (  # type: ignore[import-untyped]
                MinerUClient,
            )

            self._client = MinerUClient(
                backend="http-client",
                server_url=f"{self.base_url}/chat/completions",
                model_name=self._resolved_model or self.model,
                http_timeout=int(self.timeout),
                max_concurrency=1,
                use_tqdm=False,
                skip_model_name_checking=True,
                server_headers=auth_headers(self.api_key) or None,
            )
        return self._client

    async def available(self) -> bool:
        """Probe the server and, when no model name is configured, discover it.

        Some servers (mlx-vlm) identify a model by its filesystem path, which is
        machine-specific. Asking the server what it serves keeps the config
        portable: leave ``[parser].model`` empty and this fills it in.
        """
        try:
            async with httpx.AsyncClient(
                timeout=5.0, headers=auth_headers(self.api_key)
            ) as c:
                r = await c.get(f"{self.base_url}/models")
            if r.status_code >= 400:
                return False
            if not self._resolved_model:
                served = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
                if not served:
                    return False
                self._resolved_model = str(served[0])
                self._client = None  # rebuild with the discovered name
                logger.info("Using parser model %s", self._resolved_model)
            return True
        except Exception:  # noqa: BLE001
            return False

    def parse_page(self, image: Any) -> tuple[str, int]:
        """Blocking; callers run this in a thread."""
        blocks = self.client.two_step_extract(image)
        return blocks_to_html(blocks), len(blocks)


class LLMPageParser:
    """Fallback: ask the general multimodal LLM to transcribe a page."""

    def __init__(
        self,
        base_url: str = str(settings.LLM_BASE_URL),
        model: str = settings.LLM_MODEL,
        timeout: float = settings.LLM_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def parse_page(
        self,
        image: Any,
        prompt: str | None = None,
        *,
        meter: UsageMeter | None = None,
    ) -> tuple[str, int]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or DEFAULT_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_to_data_url(image)},
                        },
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 4096,
        }
        if settings.LLM_DISABLE_THINKING:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        async with make_http_client(self.timeout, settings.LLM_API_KEY) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=body)
        if response.status_code >= 400:
            if meter is not None:
                meter.failure(UsageKind.chat, self.model)
            raise ModelServerError(
                f"llm page parse: HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        # One of these per page of a PDF, each carrying a page image. On a
        # deployment with IMPORT_PARSER=llm this is the largest thing the
        # product spends money on, so it is the one that most needs counting.
        if meter is not None:
            meter.record(UsageKind.chat, data, model=self.model)
        try:
            content = data["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelServerError("llm page parse: malformed response") from exc
        from app.services.llm import clean_completion

        markdown = clean_completion(str(content))
        return markdown_to_html(markdown), markdown.count("\n\n") + 1


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def parse_document(
    data: bytes,
    content_type: str,
    *,
    filename: str = "",
    prompt: str | None = None,
    mineru: MinerUParser | None = None,
    llm: LLMPageParser | None = None,
    on_page: Any = None,
    meter: UsageMeter | None = None,
) -> ParsedDocument:
    """Render the upload and parse every page, preferring MinerU.

    ``on_page(index, total)`` is awaited after each page so the caller can report
    progress and check for cancellation.
    """
    import asyncio

    images = render_pages(data, content_type, filename=filename)
    if not images:
        raise UnsupportedFileType("The file contains no pages")

    mineru = mineru or MinerUParser()
    if settings.IMPORT_PARSER == "llm":
        # No document-parsing model in this deployment: the chat model reads the
        # page images instead.
        use_mineru = False
    else:
        use_mineru = await mineru.available()
        if not use_mineru:
            if (
                settings.IMPORT_PARSER == "mineru"
                or not settings.IMPORT_FALLBACK_TO_LLM
            ):
                raise ModelServerError(
                    "MinerU is not reachable at "
                    f"{mineru.base_url} and the LLM fallback is disabled"
                )
            logger.warning(
                "MinerU unreachable at %s; falling back to %s",
                mineru.base_url,
                settings.LLM_MODEL,
            )
    llm = llm or LLMPageParser()
    parser: ParserName = "mineru" if use_mineru else "llm"

    pages: list[ParsedPage] = []
    for index, image in enumerate(images):
        if use_mineru:
            page_html, blocks = await asyncio.to_thread(mineru.parse_page, image)
        else:
            page_html, blocks = await llm.parse_page(image, prompt, meter=meter)
        pages.append(
            ParsedPage(index=index, html=page_html, blocks=blocks, parser=parser)
        )
        if on_page is not None:
            await on_page(index + 1, len(images))

    combined = sanitize_html("".join(p.html for p in pages))
    return ParsedDocument(html=combined, pages=pages, parser=parser)
