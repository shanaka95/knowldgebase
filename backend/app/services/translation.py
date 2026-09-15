"""Reading a page in another language.

Nothing is translated ahead of time: a knowledge base of a thousand pages times
twenty-eight languages is twenty-eight thousand generations nobody asked for.
A translation happens when somebody picks a language, and is then kept, so the
second reader pays nothing.

It is kept against a *version*. An edited page is a different text, and showing
last week's German beside this week's English is a worse failure than a short
wait: an edit therefore simply leaves the new version with no translations yet.

The page never travels from the browser. The request names a language and a
page; the content is read here, from the database.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlmodel import Session, select

from app.core.config import settings
from app.core.content import html_to_text, sanitize_html
from app.models import DocumentTranslation, DocumentVersion, UsageFeature
from app.services import usage
from app.services.language import LANGUAGES, language_name
from app.services.llm import LLMClient, LLMTask

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You translate documents. You are given a fragment of an HTML document and a target language.

Rules:
- Translate the human-readable text into {language}. Translate nothing else.
- Keep the HTML exactly as it is: the same tags, in the same order, with the same attributes. Do not add, remove, merge or reorder elements.
- Leave code, identifiers, URLs, email addresses, file names and numbers as they are.
- Keep proper nouns as they are unless the target language has an established form for them.
- Translate every piece of text, including table cells and headings.
- Output only the translated HTML fragment. No explanation, no code fence, no commentary."""

TITLE_PROMPT = """You translate document titles into {language}.

Output only the translated title: no quotes, no explanation, nothing else. Leave identifiers, codes and numbers as they are."""


class TranslationError(RuntimeError):
    pass


def existing_translation(
    session: Session, document_id: uuid.UUID, version: int, language: str
) -> DocumentTranslation | None:
    return session.exec(
        select(DocumentTranslation).where(
            DocumentTranslation.document_id == document_id,
            DocumentTranslation.doc_version == version,
            DocumentTranslation.language == language,
        )
    ).first()


def translated_languages(
    session: Session, document_id: uuid.UUID, version: int
) -> list[str]:
    """Which languages this exact version already has, for the picker."""
    rows = session.exec(
        select(DocumentTranslation.language).where(
            DocumentTranslation.document_id == document_id,
            DocumentTranslation.doc_version == version,
        )
    ).all()
    return sorted(str(r) for r in rows)


# Splitting on the close of a top-level block keeps whole elements together, so
# no window ever begins or ends inside a tag.
_BLOCK_END = re.compile(
    r"(</(?:p|div|h1|h2|h3|h4|h5|h6|ul|ol|li|table|tr|blockquote|pre|section)>)",
    re.IGNORECASE,
)


def split_html(content_html: str, window: int | None = None) -> list[str]:
    """Cut a page into pieces a model can translate in one completion.

    A long page will not fit in one answer, and a model that runs out of room
    silently truncates the end of the document. The cut is made after a closing
    block tag so each piece is a whole set of elements.
    """
    window = window or settings.TRANSLATION_WINDOW_CHARS
    html = content_html or ""
    if len(html) <= window:
        return [html] if html.strip() else []

    parts = _BLOCK_END.split(html)
    # `split` with a capturing group alternates text and delimiter; glue each
    # delimiter back onto the text before it.
    blocks: list[str] = []
    for index in range(0, len(parts), 2):
        block = parts[index] + (parts[index + 1] if index + 1 < len(parts) else "")
        if block:
            blocks.append(block)

    windows: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) > window:
            windows.append(current)
            current = block
        else:
            current += block
    if current.strip():
        windows.append(current)
    return windows


def _clean(text: str) -> str:
    """Strip the wrapper a model adds even when told not to."""
    stripped = (text or "").strip()
    fenced = re.match(r"^```(?:html)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    return fenced.group(1).strip() if fenced else stripped


async def translate_html(llm: LLMClient, content_html: str, language_label: str) -> str:
    """The page in another language, still as HTML."""
    windows = split_html(content_html)
    if not windows:
        return ""
    system = SYSTEM_PROMPT.format(language=language_label)
    out: list[str] = []
    for window in windows:
        piece = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": window},
            ],
            max_tokens=settings.TRANSLATION_MAX_TOKENS,
            temperature=settings.TRANSLATION_TEMPERATURE,
        )
        out.append(_clean(piece))
    return "\n".join(part for part in out if part)


async def translate_title(llm: LLMClient, title: str, language_label: str) -> str:
    if not title.strip():
        return title
    translated = await llm.chat(
        [
            {"role": "system", "content": TITLE_PROMPT.format(language=language_label)},
            {"role": "user", "content": title.strip()},
        ],
        max_tokens=120,
        temperature=settings.TRANSLATION_TEMPERATURE,
    )
    cleaned = _clean(translated).strip().strip('"')
    return (cleaned or title)[:300]


async def translate_version(
    session: Session,
    version: DocumentVersion,
    language: str,
    *,
    requested_by: uuid.UUID | None = None,
) -> DocumentTranslation:
    """Translate one version into one language and keep the result.

    A second request for the same version and language returns what is already
    stored rather than paying for it twice.
    """
    code = language.strip().lower()
    label = language_name(code)
    if label is None:
        raise TranslationError(f"{language} is not one of the languages offered")

    stored = existing_translation(session, version.document_id, version.version, code)
    if stored is not None:
        return stored

    # One translation, however many windows a long page is cut into - and the
    # returned-from-storage case above never gets here, so a page translated
    # twice is counted once.
    async with usage.ameter(requested_by, UsageFeature.translation) as m:
        m.operation()
        llm = LLMClient(task=LLMTask.translation, meter=m)
        try:
            title = await translate_title(llm, version.title, label)
            html = await translate_html(llm, version.content_html, label)
        finally:
            await llm.close()

    # Through the same gate every saved page goes through: this HTML came from
    # a model, and nothing a model writes is trusted as markup.
    safe_html = sanitize_html(html)
    translation = DocumentTranslation(
        document_id=version.document_id,
        doc_version=version.version,
        language=code,
        title=title,
        content_html=safe_html,
        content_text=html_to_text(safe_html),
        model=llm.model,
        created_by=requested_by,
    )
    session.add(translation)
    session.commit()
    session.refresh(translation)
    logger.info(
        "translated document %s v%s into %s",
        str(version.document_id)[:8],
        version.version,
        code,
    )
    return translation


def language_options() -> list[tuple[str, str]]:
    """Everything on offer, alphabetically by name."""
    return sorted(LANGUAGES.items(), key=lambda pair: pair[1])
