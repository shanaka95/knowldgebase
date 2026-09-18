"""What to call somebody, and what to do with a file full of strangers.

The greeting is the part worth testing properly. A list exported from another
product's sign-up form has a name column containing "asdf", "777", "P", an
email address and a spam link, and "Hi asdf," is worse than no name at all.
Every case below was taken from the real file.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.models import ContactSource, MarketingContact
from app.services import marketing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Names, including scripts an ASCII-only test would have refused.
        ("Gagan S", "Gagan"),
        ("Prashant Somani", "Prashant"),
        ("Paweł Franczak", "Paweł"),
        ("Александр Беляев", "Александр"),
        ("Trần Nam Anh", "Trần"),
        ("Benoît Quévat", "Benoît"),
        ("amanda mussio", "Amanda"),
        # Not names.
        ("asdf", ""),
        ("test", ""),
        ("Test Guy", ""),
        ("admin8386", ""),
        ("777", ""),
        ("1015394025", ""),
        ("P", ""),
        ("ts0246", ""),
        # An abbreviation, not something anybody answers to.
        ("PK", ""),
        ("xp", ""),
        ("M Zh", ""),
        # A mis-filled form, and outright spam.
        ("konor77225@ellbit.com", ""),
        ("✨80.000 Lira Seni Bekliyor https://bit.ly/48EQLiO ✨", ""),
        ("", ""),
    ],
)
def test_who_we_are_willing_to_greet_by_name(raw: str, expected: str) -> None:
    assert marketing.greeting_name(raw) == expected


def test_the_greeting_always_reads() -> None:
    """Whatever the list says, "Hi {x}," has to be a sentence."""
    junk = MarketingContact(email="a@b.co", name="asdf", unsubscribe_token="t")
    assert marketing.greeting_for(junk) == "there"


# --- rendering ---------------------------------------------------------------


def contact(**overrides) -> MarketingContact:  # type: ignore[no-untyped-def]
    base = {
        "email": "gagan@example.com",
        "name": "Gagan S",
        "unsubscribe_token": "tok-123",
    }
    base.update(overrides)
    return MarketingContact(**base)  # type: ignore[arg-type]


def test_a_rendered_message_has_no_placeholders_left_in_it() -> None:
    rendered = marketing.render_for(
        contact(),
        subject=marketing.DEFAULT_SUBJECT,
        body_html=marketing.DEFAULT_BODY_HTML,
    )
    assert "{{" not in rendered.html
    assert "{{" not in rendered.text
    assert "Hi Gagan," in rendered.text


def test_the_unsubscribe_link_is_in_both_parts() -> None:
    """The text part especially: it is what a plain-text client shows, and it
    is the only part the development mailbox stores."""
    rendered = marketing.render_for(
        contact(), subject="Hello", body_html="<p>Hi {{name}}</p>"
    )
    assert rendered.unsubscribe_url.endswith("/unsubscribe/tok-123")
    assert rendered.unsubscribe_url in rendered.html
    assert rendered.unsubscribe_url in rendered.text


def test_a_name_out_of_a_file_cannot_carry_markup() -> None:
    """The body is markup the administrator wrote. The name is not.

    Nobody is going to type a script tag into a sign-up form on purpose, which
    is exactly why this is worth a test rather than a comment.
    """
    rendered = marketing.render_for(
        contact(name="<script>alert(1)</script>Bob"),
        subject="Hello",
        body_html="<p>Hi {{name}}</p>",
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html or "there" in rendered.html


def test_a_link_keeps_its_destination_in_the_text_part() -> None:
    rendered = marketing.render_for(
        contact(),
        subject="s",
        body_html='<p><a href="https://plusgpt.io/x">Try</a></p>',
    )
    assert "Try (https://plusgpt.io/x)" in rendered.text


# --- the list ----------------------------------------------------------------


def test_adding_the_same_address_twice_adds_one_row(db: Session) -> None:
    marketing.ensure_contact(db, email="Dup@Example.com ", name="Sam")
    db.commit()
    marketing.ensure_contact(db, email="dup@example.com", name="Sam")
    db.commit()
    rows = db.exec(
        select(MarketingContact).where(MarketingContact.email == "dup@example.com")
    ).all()
    assert len(rows) == 1
    # Normalised on the way in, so the second spelling is the same person.
    assert rows[0].email == "dup@example.com"
    db.delete(rows[0])
    db.commit()


def test_signing_up_does_not_resubscribe_somebody_who_left(db: Session) -> None:
    """The one that matters. An unsubscribe has to outlast everything."""
    contact_row = marketing.ensure_contact(db, email="gone@example.com")
    db.commit()
    marketing.unsubscribe(db, contact_row.unsubscribe_token)
    db.commit()

    marketing.ensure_contact(db, email="gone@example.com", source=ContactSource.signup)
    db.commit()
    db.refresh(contact_row)
    assert contact_row.unsubscribed_at is not None

    db.delete(contact_row)
    db.commit()


def test_unsubscribing_twice_is_still_a_success(db: Session) -> None:
    row = marketing.ensure_contact(db, email="twice@example.com")
    db.commit()
    assert marketing.unsubscribe(db, row.unsubscribe_token) is True
    db.commit()
    first = row.unsubscribed_at
    assert marketing.unsubscribe(db, row.unsubscribe_token) is True
    db.commit()
    # And it does not move the date, which is the one somebody would be asked
    # to produce if the send were ever disputed.
    assert row.unsubscribed_at == first
    db.delete(row)
    db.commit()


def test_an_unknown_token_unsubscribes_nothing(db: Session) -> None:
    assert marketing.unsubscribe(db, "not-a-real-token") is False


CSV = b"""username,name,email,email_verified
1,Gagan S,gagan@example.com,true
2,asdf,,true
3,Sam,SAM@Example.com,true
4,Dup,sam@example.com,true
5,Broken,not-an-address,true
"""


def test_an_import_reports_every_row_it_could_not_use(db: Session) -> None:
    result = marketing.import_csv(db, CSV)
    assert result.added == 2  # gagan and sam; the empty address is not a row
    reasons = {s.reason for s in result.skipped}
    assert "listed twice in this file" in reasons
    assert "not a valid address" in reasons

    # And a second run adds nothing.
    again = marketing.import_csv(db, CSV)
    assert again.added == 0
    assert again.already_present == 2

    for row in db.exec(
        select(MarketingContact).where(
            MarketingContact.email.in_(["gagan@example.com", "sam@example.com"])  # type: ignore[attr-defined]
        )
    ).all():
        db.delete(row)
    db.commit()


def test_a_plain_two_column_file_works_too(db: Session) -> None:
    """The Cognito export is one shape. A spreadsheet is another."""
    result = marketing.import_csv(db, b"Email,Full Name\nplain@example.com,Jo\n")
    assert result.added == 1
    row = db.exec(
        select(MarketingContact).where(MarketingContact.email == "plain@example.com")
    ).one()
    assert row.name == "Jo"
    db.delete(row)
    db.commit()


def test_the_footer_speaks_for_the_company_not_for_a_person() -> None:
    """Both halves of it, because the HTML and the text carry it separately.

    It is also deliberately vague about *which* product: the list spans more
    than one, and naming the wrong one is worse than naming none.
    """
    rendered = marketing.render_for(
        contact(), subject="s", body_html="<p>Hi {{name}}</p>"
    )
    for part in (rendered.html, rendered.text):
        assert "one of our products" in part
        assert "my projects" not in part
        assert " I will not email" not in part


def test_the_default_message_is_the_one_we_meant_to_send() -> None:
    """Three things a careless edit would quietly drop.

    The logo has to be a PNG at an absolute URL, because Gmail and Outlook
    render no SVG and resolve no relative path; the greeting has to be a
    placeholder rather than a name somebody pasted in; and there has to be
    somewhere to click.
    """
    body = marketing.DEFAULT_BODY_HTML
    assert "https://plusgpt.io/icon-192.png" in body
    assert "{{name}}" in body
    assert "https://plusgpt.io/signup" in body
    assert "<style" not in body, "mail clients strip stylesheets"
