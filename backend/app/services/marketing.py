"""The list, and what gets written to it.

Three jobs live here and nothing else does: deciding what to call somebody,
turning one authored message into one person's copy of it, and getting an
uploaded file into the table.

The first of those sounds trivial and is not. A list imported from another
product's sign-up form has a `name` column containing "asdf", "777", "P",
"Test Guy", somebody's email address, and three copies of a Turkish spam link.
"Hi asdf," is worse than no name at all, so the greeting is a judgement rather
than a substitution, and it is written down here where it can be tested.
"""

from __future__ import annotations

import csv
import io
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.models import (
    ContactImportResult,
    ContactSource,
    MarketingContact,
    ShareSkipped,
)
from app.services.sharing import normalise_email

# Words that are on this list because somebody typed them into a name field
# rather than a name. Lowercased at the point of comparison.
JUNK_NAMES = frozenset(
    {
        "test",
        "tests",
        "testing",
        "user",
        "users",
        "admin",
        "asdf",
        "qwerty",
        "none",
        "null",
        "na",
        "foo",
        "bar",
        "abc",
        "demo",
        "example",
        "unknown",
        "anonymous",
    }
)

FALLBACK_GREETING = "there"


def now() -> datetime:
    return datetime.now(UTC)


def new_unsubscribe_token() -> str:
    """Unguessable, and good for the life of the address.

    Stored in plaintext, like `Document.public_slug` and unlike an `AuthCode`.
    There is nothing to protect by hashing it: it buys exactly one thing, the
    right to stop being emailed, and it has to keep working years later and
    across every campaign, which single-use hashed codes do not.
    """
    return secrets.token_urlsafe(32)


def greeting_name(name: str) -> str:
    """The first name to greet somebody by, or "" when there is not one.

    Rejections, in the order they matter:

    * An address or a link in the name field is a mis-filled form or spam.
    * Anything that is not two to twenty letters: "777", "ts0246", "P".
    * A known placeholder: "test", "asdf", "admin".
    * A Latin-script word with no vowel, which is an abbreviation somebody
      types rather than a name they answer to: "PK", "xp", "Zh". The test is
      limited to ASCII because other scripts write vowels differently and
      applying it to them would refuse perfectly good names.

    Everything else is accepted as given, capitalised but not otherwise
    rewritten - `Александр`, `Paweł` and `Trần` are names.
    """
    raw = (name or "").strip()
    if not raw or "@" in raw or "http" in raw.lower():
        return ""
    first = raw.split()[0].strip(".,_-'\"")
    if not (2 <= len(first) <= 20) or not first.isalpha():
        return ""
    if first.lower() in JUNK_NAMES:
        return ""
    if first.isascii() and not re.search(r"[aeiou]", first.lower()):
        return ""
    return first[0].upper() + first[1:]


def greeting_for(contact: MarketingContact) -> str:
    """What to put after "Hi". Never empty, so the sentence always reads."""
    return greeting_name(contact.name) or FALLBACK_GREETING


# --- rendering ---------------------------------------------------------------
#
# The body is HTML an administrator wrote, so it goes in as markup by
# construction. The values substituted into it did not come from the
# administrator - they came from an uploaded file - so they are escaped first.

_PLACEHOLDER = re.compile(r"\{\{\s*(name|email|unsubscribe_url)\s*\}\}")


def render(template: str, *, values: dict[str, str]) -> str:
    """Fill the placeholders, leaving anything else alone.

    Deliberately not a template engine. Three names, no expressions, no loops:
    whatever is in that textarea is going to several hundred people, and the
    set of things it can do should be small enough to hold in your head.
    """
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), template)


def _to_text(html_body: str) -> str:
    """A readable plain-text part, derived from the HTML rather than authored.

    Asking somebody to write the message twice guarantees the two drift. A text
    part is worth having anyway: it noticeably improves deliverability, and it
    is the only part the development mailbox stores, so it is what the
    end-to-end test reads.
    """
    from app.core.content import html_to_text

    # A line break becomes a block, not a newline character. `html_to_text`
    # normalises whitespace within a block, so a bare "\n" is swallowed and a
    # signature comes out as one run-on line; a paragraph boundary survives.
    html_body = re.sub(r"<br\s*/?>", "</p><p>", html_body, flags=re.IGNORECASE)
    # Links carry the meaning in a marketing message, so an anchor becomes
    # "label (url)" rather than losing its destination entirely.
    with_links = re.sub(
        r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        lambda m: f"{m.group(2)} ({m.group(1)})",
        html_body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html_to_text(with_links).strip()


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    to: str
    subject: str
    html: str
    text: str
    unsubscribe_url: str


def render_for(
    contact: MarketingContact, *, subject: str, body_html: str
) -> RenderedMessage:
    """One person's copy of a campaign."""
    from app.services.email import marketing_shell
    from app.services.sharing import unsubscribe_url

    url = unsubscribe_url(contact.unsubscribe_token)
    values = {
        # Escaped: this came from a file somebody uploaded, not from the
        # administrator who wrote the markup around it.
        "name": _escape(greeting_for(contact)),
        "email": _escape(contact.email),
        "unsubscribe_url": url,
    }
    body = render(body_html, values=values)
    text_values = dict(values, name=greeting_for(contact), email=contact.email)
    return RenderedMessage(
        to=contact.email,
        subject=render(subject, values=text_values),
        html=marketing_shell(body, unsubscribe_url=url),
        text=(
            f"{_to_text(body)}\n\n"
            "---\n"
            "You are receiving this because you signed up for one of my "
            f"projects. To stop hearing from me: {url}\n"
            f"{str(settings.FRONTEND_HOST).rstrip('/')}/imprint"
        ),
        unsubscribe_url=url,
    )


def _escape(value: str) -> str:
    from app.services.email import _safe

    return _safe(value)


# --- the list ----------------------------------------------------------------


def ensure_contact(
    session: Session,
    *,
    email: str,
    name: str = "",
    source: ContactSource = ContactSource.manual,
    user_id: uuid.UUID | None = None,
) -> MarketingContact:
    """Put this address on the list, or leave it exactly as it is.

    Idempotent on purpose, because it is called from account creation: signing
    up twice, or signing up with an address that was imported months ago, must
    not create a second row and above all must not quietly resubscribe somebody
    who asked to be left alone.
    """
    address = normalise_email(email)
    existing = session.exec(
        select(MarketingContact).where(MarketingContact.email == address)
    ).first()
    if existing is not None:
        changed = False
        if user_id is not None and existing.user_id is None:
            existing.user_id = user_id
            changed = True
        if name and not existing.name:
            existing.name = name[:255]
            changed = True
        if changed:
            existing.updated_at = datetime.now(UTC)
            session.add(existing)
        return existing

    contact = MarketingContact(
        email=address,
        name=(name or "")[:255],
        source=source,
        unsubscribe_token=new_unsubscribe_token(),
        user_id=user_id,
    )
    session.add(contact)
    return contact


def unsubscribe(session: Session, token: str) -> bool:
    """Stop emailing whoever holds this token. True when the token is known.

    Unsubscribing twice succeeds. Somebody who clicks the link in two different
    messages has not made a mistake, and telling them the second one failed
    would be the worst possible moment to show an error.
    """
    contact = session.exec(
        select(MarketingContact).where(MarketingContact.unsubscribe_token == token)
    ).first()
    if contact is None:
        return False
    if contact.unsubscribed_at is None:
        contact.unsubscribed_at = datetime.now(UTC)
        contact.updated_at = contact.unsubscribed_at
        session.add(contact)
    return True


# Column names this understands, in order of preference. The first is the
# Cognito export's; the rest are what a spreadsheet exported by hand tends to
# call them.
EMAIL_COLUMNS = ("email", "email_address", "e_mail", "e_mail_address", "mail")
NAME_COLUMNS = ("name", "full_name", "fullname", "first_name", "given_name")


def _header(name: str) -> str:
    """One spelling for a column heading.

    A hand-made spreadsheet writes "Full Name" or "E-Mail Address" where an
    export writes "full_name". Folding the separators means the list of names
    below describes columns rather than enumerating punctuation.
    """
    return re.sub(r"[\s\-]+", "_", (name or "").strip().lower())


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    folded = {_header(k): (v or "") for k, v in row.items()}
    for candidate in candidates:
        if folded.get(candidate, "").strip():
            return folded[candidate].strip()
    return ""


def import_csv(session: Session, payload: bytes) -> ContactImportResult:
    """Read an uploaded file onto the list, and say what happened to every row.

    Reports rather than raises. One malformed address in six hundred is not a
    reason to reject the file, and an import that silently drops rows is one
    nobody can check afterwards.
    """
    from pydantic import TypeAdapter
    from pydantic.networks import EmailStr

    result = ContactImportResult()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return result

    validator = TypeAdapter(EmailStr)
    seen: set[str] = set()
    for row in reader:
        raw_email = _pick(row, EMAIL_COLUMNS)
        name = _pick(row, NAME_COLUMNS)
        if not raw_email:
            continue
        address = normalise_email(raw_email)
        if address in seen:
            result.skipped.append(
                ShareSkipped(email=address, reason="listed twice in this file")
            )
            continue
        seen.add(address)
        try:
            validator.validate_python(address)
        except ValidationError:
            result.skipped.append(
                ShareSkipped(email=raw_email[:320], reason="not a valid address")
            )
            continue

        before = session.exec(
            select(MarketingContact).where(MarketingContact.email == address)
        ).first()
        ensure_contact(
            session,
            email=address,
            name=name,
            source=ContactSource.imported,
        )
        if before is None:
            result.added += 1
        else:
            result.already_present += 1

    session.commit()
    return result


def counts(session: Session) -> tuple[int, int]:
    """How many addresses there are, and how many still want to hear from us."""
    total = session.exec(select(func.count()).select_from(MarketingContact)).one()
    subscribed = session.exec(
        select(func.count())
        .select_from(MarketingContact)
        .where(col(MarketingContact.unsubscribed_at).is_(None))
    ).one()
    return int(total), int(subscribed)


DEFAULT_SUBJECT = "Would you try something I built?"

# The message this feature exists to send. Seeded into the composer as a
# starting point rather than hard-coded into the sender: it is going to be
# rewritten, and the next campaign will be a different message entirely.
DEFAULT_BODY_HTML = """<p>Hi {{name}},</p>

<p>I built PlusGPT, and I am looking for a few people to try it and tell me where it falls over.</p>

<p>It takes documents you already have, a PDF, a scan, your own notes, and turns them into something you can ask. Every answer shows the passages it came from, so you can check it rather than trust it.</p>

<p>It is free to try, and about two minutes is enough to find out whether it is useful to you.</p>

<p><a href="https://plusgpt.io/signup">Try PlusGPT</a></p>

<p>If you do try it, hit reply and tell me the one thing that annoyed you most. I read every reply myself.</p>

<p>Shanaka<br>
<a href="https://plusgpt.io">plusgpt.io</a></p>"""
