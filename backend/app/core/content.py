"""Content normalisation: format conversion, HTML sanitisation, plain-text derivation.

``content_html`` is the canonical stored representation (what the Tiptap editor
loads and saves). ``content_text`` is always derived from it on the server so both
the API and the embedding worker agree on the plain text.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Literal

import nh3
from markdown_it import MarkdownIt
from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.models import ContentFormat

BlockKind = Literal[
    "heading", "paragraph", "list_item", "code", "table_row", "quote", "other"
]

# --- sanitiser allow-list (matches Tiptap StarterKit + Table + TaskList + Image + Panel)
ALLOWED_TAGS: set[str] = {
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "del",
    "code",
    "pre",
    "mark",
    "sub",
    "sup",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "colgroup",
    "col",
    "div",
    "span",
    "label",
    "input",
}
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"class"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "ol": {"start", "type"},
    "th": {"colspan", "rowspan", "colwidth"},
    "td": {"colspan", "rowspan", "colwidth"},
    "input": {"type", "checked", "disabled"},
    "p": {"style"},
    "h1": {"style"},
    "h2": {"style"},
    "h3": {"style"},
    "h4": {"style"},
    "h5": {"style"},
    "h6": {"style"},
}
_TEXT_ALIGN_RE = re.compile(
    r"^\s*text-align\s*:\s*(left|right|center|justify)\s*;?\s*$"
)


def _attribute_filter(element: str, attribute: str, value: str) -> str | None:
    if attribute == "style":
        m = _TEXT_ALIGN_RE.match(value)
        return f"text-align: {m.group(1)}" if m else None
    if element == "input" and attribute == "type" and value != "checkbox":
        return None
    return value


def sanitize_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    return nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        generic_attribute_prefixes={"data-"},
        attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


_md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def markdown_to_html(markdown: str) -> str:
    return str(_md.render(markdown or ""))


def text_to_html(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text)
    out = []
    for para in paragraphs:
        lines = [html_lib.escape(line) for line in para.split("\n")]
        out.append(f"<p>{'<br>'.join(lines)}</p>")
    return "".join(out)


# --- HTML -> blocks -> plain text ---------------------------------------------


@dataclass(slots=True)
class Block:
    kind: BlockKind
    text: str
    level: int | None = None  # heading level

    @property
    def is_heading(self) -> bool:
        return self.kind == "heading"


_WS_RE = re.compile(r"[ \t ]+")
_NL_RE = re.compile(r"\s*\n\s*")


def _clean_inline(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = _NL_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _node_text(node: LexborNode) -> str:
    # <br> should become a space, not glue two words together
    for br in node.css("br"):
        br.replace_with(" ")
    return _clean_inline(node.text(separator=" ", strip=False))


def html_to_blocks(content_html: str) -> list[Block]:
    """Flatten Tiptap-style HTML into a sequence of text blocks."""
    if not content_html or not content_html.strip():
        return []
    tree = LexborHTMLParser(content_html)
    body = tree.body
    if body is None:
        return []
    blocks: list[Block] = []
    _walk(body, blocks, depth=0)
    return [b for b in blocks if b.text]


def _walk(parent: LexborNode, blocks: list[Block], depth: int) -> None:
    for node in parent.iter(include_text=True):
        tag = node.tag
        if tag == "-text":
            txt = _clean_inline(node.text())
            if txt:
                blocks.append(Block("paragraph", txt))
            continue
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            txt = _node_text(node)
            if txt:
                blocks.append(Block("heading", txt, level=int(tag[1])))
        elif tag == "p":
            txt = _node_text(node)
            if txt:
                blocks.append(Block("paragraph", txt))
        elif tag in ("ul", "ol"):
            _walk_list(node, ordered=tag == "ol", depth=depth, blocks=blocks)
        elif tag == "pre":
            code = node.text(separator="", strip=False).strip("\n")
            if code.strip():
                blocks.append(Block("code", code))
        elif tag == "table":
            for tr in node.css("tr"):
                cells = [
                    _node_text(c)
                    for c in tr.iter(include_text=False)
                    if c.tag in ("td", "th")
                ]
                row = " | ".join(c for c in cells if c)
                if row:
                    blocks.append(Block("table_row", row))
        elif tag == "blockquote":
            inner: list[Block] = []
            _walk(node, inner, depth)
            for b in inner:
                blocks.append(Block("quote", b.text, b.level))
        elif tag in (
            "div",
            "section",
            "article",
            "main",
            "body",
            "html",
            "figure",
            "details",
            "summary",
        ):
            _walk(node, blocks, depth)
        elif tag in ("img", "hr", "br", "input", "label", "script", "style"):
            alt = node.attributes.get("alt") if tag == "img" else None
            if alt:
                blocks.append(Block("other", alt))
        else:
            # inline-ish container at block level (span, strong, a, ...)
            txt = _node_text(node)
            if txt:
                blocks.append(Block("paragraph", txt))


def _walk_list(
    node: LexborNode, ordered: bool, depth: int, blocks: list[Block]
) -> None:
    index = 0
    for li in node.iter(include_text=False):
        if li.tag != "li":
            continue
        index += 1
        parts: list[str] = []
        nested: list[LexborNode] = []
        for child in li.iter(include_text=True):
            if child.tag in ("ul", "ol"):
                nested.append(child)
            elif child.tag == "-text":
                parts.append(child.text())
            elif child.tag in ("input", "label") and not child.text().strip():
                continue
            else:
                parts.append(child.text(separator=" ", strip=False))
        own = _clean_inline(" ".join(parts))
        checked = None
        if li.attributes.get("data-type") == "taskItem":
            checked = li.attributes.get("data-checked") == "true"
        if checked is not None:
            prefix = "[x] " if checked else "[ ] "
        else:
            prefix = f"{index}. " if ordered else "- "
        if own:
            blocks.append(Block("list_item", ("  " * depth) + prefix + own))
        for n in nested:
            _walk_list(n, ordered=n.tag == "ol", depth=depth + 1, blocks=blocks)


def blocks_to_text(blocks: list[Block]) -> str:
    return "\n\n".join(b.text for b in blocks if b.text).strip()


def html_to_text(content_html: str) -> str:
    return blocks_to_text(html_to_blocks(content_html))


def normalize_content(content: str, fmt: ContentFormat) -> tuple[str, str]:
    """Convert ``content`` in ``fmt`` to (sanitized_html, plain_text)."""
    if fmt == ContentFormat.markdown:
        raw = markdown_to_html(content)
    elif fmt == ContentFormat.text:
        raw = text_to_html(content)
    else:
        raw = content or ""
    clean = sanitize_html(raw)
    return clean, html_to_text(clean)
