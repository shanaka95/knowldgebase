"""Transactional email over AWS SES.

Three messages matter here, and all three are security-critical: confirm an
address, confirm a login, reset a password. Each one is the only thing standing
between a stranger and an account, so the rules are the same for all of them:

* **Never say whether an address exists.** The caller of "resend" or "forgot
  password" always gets the same answer. Only the mailbox owner learns anything.
* **Sending is best-effort at the call site, never at the security boundary.** A
  failed send must not create a valid session, and must not leave a code that
  someone could guess at leisure.
* **Codes are not logged in production.** With ``EMAIL_ENABLED=false`` - the
  default, which is how development and the test suite run - nothing is sent and
  the code is written to the log instead, so the flows can be exercised offline.

Both plain-text and HTML parts are sent: mail clients that refuse HTML still
show something useful, and a text part markedly improves deliverability.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """The message could not be handed to the provider."""


@dataclass(slots=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    async def send(self, message: Email) -> None: ...


class LoggingEmailSender:
    """Used when email is switched off. Records what would have been sent.

    Development and the test suite both run this way, so the verification and
    two-factor flows work end to end without a mail provider: read the code out
    of the log.
    """

    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, message: Email) -> None:
        self.sent.append(message)
        logger.info(
            "email (not sent, EMAIL_ENABLED=false) to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.text,
        )


class SesEmailSender:
    """AWS Simple Email Service.

    boto3 is synchronous, so each send runs in a worker thread rather than
    blocking the event loop for the duration of an API round trip.
    """

    def __init__(
        self,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.region = region or settings.AWS_REGION
        self.access_key = access_key or settings.AWS_ACCESS_KEY
        self.secret_key = secret_key or settings.AWS_ACCESS_SECRET
        self._client: Any = None

    def _build_client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "ses",
            region_name=self.region,
            aws_access_key_id=self.access_key or None,
            aws_secret_access_key=self.secret_key or None,
            config=Config(
                connect_timeout=settings.EMAIL_TIMEOUT_SECONDS,
                read_timeout=settings.EMAIL_TIMEOUT_SECONDS,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _send_sync(self, message: Email) -> None:
        source = settings.EMAIL_FROM
        if settings.EMAIL_FROM_NAME:
            source = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        self.client.send_email(
            Source=source,
            Destination={"ToAddresses": [message.to]},
            Message={
                "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": message.text, "Charset": "UTF-8"},
                    "Html": {"Data": message.html, "Charset": "UTF-8"},
                },
            },
        )

    async def send(self, message: Email) -> None:
        try:
            await asyncio.to_thread(self._send_sync, message)
        except Exception as exc:  # noqa: BLE001 - boto3 raises a wide family
            raise EmailError(f"SES refused the message: {exc}") from exc


_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """One sender for the process, so the SES client and its pool are reused."""
    global _sender
    if _sender is None:
        _sender = SesEmailSender() if settings.EMAIL_ENABLED else LoggingEmailSender()
    return _sender


def reset_email_sender() -> None:
    """Forget the cached sender. Tests use this after changing settings."""
    global _sender
    _sender = None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _shell(title: str, body_html: str) -> str:
    """One plain, table-free layout for every message.

    Deliberately simple markup: mail clients are a decade behind browsers, and a
    message that renders everywhere beats one that is pretty in two clients.
    """
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1c1e26;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;padding:32px;">
      <div style="font-size:20px;font-weight:600;letter-spacing:-0.01em;margin-bottom:4px;">{settings.APP_NAME}</div>
      <div style="font-size:13px;color:#6b7280;margin-bottom:24px;">{settings.APP_TAGLINE}</div>
      <h1 style="font-size:18px;font-weight:600;margin:0 0 12px;">{title}</h1>
      {body_html}
    </div>
    <div style="max-width:520px;margin:16px auto 0;font-size:12px;color:#9096a2;text-align:center;">
      Sent by {settings.APP_NAME}. If you did not expect this message you can ignore it.
    </div>
  </body>
</html>"""


def _button(url: str, label: str) -> str:
    return (
        f'<p style="margin:24px 0;"><a href="{url}" '
        'style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;'
        'padding:11px 20px;border-radius:8px;font-weight:600;font-size:14px;">'
        f"{label}</a></p>"
        f'<p style="font-size:12px;color:#6b7280;margin:0;">Or paste this into your browser:<br>'
        f'<span style="word-break:break-all;">{url}</span></p>'
    )


def _code_block(code: str) -> str:
    return (
        '<p style="margin:24px 0;font-size:30px;font-weight:700;letter-spacing:0.22em;'
        f'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">{code}</p>'
    )


def verification_email(to: str, url: str, hours: int) -> Email:
    return Email(
        to=to,
        subject=f"Confirm your {settings.APP_NAME} address",
        text=(
            f"Welcome to {settings.APP_NAME}.\n\n"
            f"Confirm this address to finish setting up your account:\n{url}\n\n"
            f"The link works for {hours} hours.\n\n"
            "If you did not create an account, ignore this message."
        ),
        html=_shell(
            "Confirm your email address",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            f"Confirm this address to finish setting up your {settings.APP_NAME} "
            "account.</p>"
            + _button(url, "Confirm my address")
            + f"<p style='font-size:12px;color:#6b7280;margin:16px 0 0;'>The link works for {hours} hours.</p>",
        ),
    )


def two_factor_email(to: str, code: str, minutes: int) -> Email:
    return Email(
        to=to,
        subject=f"{code} is your {settings.APP_NAME} sign-in code",
        text=(
            f"Your sign-in code is {code}.\n\n"
            f"It expires in {minutes} minutes and can be used once.\n\n"
            "If you did not try to sign in, change your password: someone else "
            "knows it."
        ),
        html=_shell(
            "Your sign-in code",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            "Enter this code to finish signing in.</p>"
            + _code_block(code)
            + f"<p style='font-size:12px;color:#6b7280;margin:0;'>It expires in {minutes} minutes and can be used once.</p>"
            "<p style='font-size:12px;color:#6b7280;margin:12px 0 0;'>"
            "If you did not try to sign in, change your password: someone else knows it.</p>",
        ),
    )


def password_reset_email(to: str, url: str, minutes: int) -> Email:
    return Email(
        to=to,
        subject=f"Reset your {settings.APP_NAME} password",
        text=(
            "Use this link to choose a new password:\n"
            f"{url}\n\n"
            f"It works once, for {minutes} minutes.\n\n"
            "If you did not ask for this, ignore the message. Your password has "
            "not changed."
        ),
        html=_shell(
            "Reset your password",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            "Choose a new password for your account.</p>"
            + _button(url, "Choose a new password")
            + f"<p style='font-size:12px;color:#6b7280;margin:16px 0 0;'>It works once, for {minutes} minutes. "
            "If you did not ask for this, your password has not changed.</p>",
        ),
    )


def _quote(note: str | None) -> str:
    """The sharer's own words, as text, never as markup.

    This is the one part of the message somebody else wrote, so it is escaped
    and set apart rather than dropped into the layout as HTML.
    """
    text = (note or "").strip()
    if not text:
        return ""
    safe = html.escape(text).replace("\n", "<br>")
    return (
        '<blockquote style="margin:20px 0;padding:12px 16px;border-left:3px solid '
        "#d8d9e0;background:#f7f7fa;border-radius:0 8px 8px 0;font-size:14px;"
        f'line-height:1.6;color:#1c1e26;">{safe}</blockquote>'
    )


def _quote_text(note: str | None) -> str:
    text = (note or "").strip()
    return f"\n\n\u201c{text}\u201d\n" if text else ""


def share_invitation_email(
    to: str,
    *,
    sharer: str,
    title: str,
    url: str,
    can_edit: bool,
    days: int,
    note: str | None = None,
) -> Email:
    """Sent to an address with no account yet, because someone shared a page.

    It names the person and the page, because a message that says only "you have
    been invited" is indistinguishable from spam and gets treated as such.
    """
    what = "view and edit" if can_edit else "read"
    return Email(
        to=to,
        subject=f"{sharer} shared “{title}” with you on {settings.APP_NAME}",
        text=(
            f"{sharer} shared a page with you on {settings.APP_NAME}: “{title}”."
            f"{_quote_text(note)}\n"
            f"Create an account with this address to {what} it:\n{url}\n\n"
            f"The invitation is good for {days} days. If you were not expecting "
            "it, you can ignore this message."
        ),
        html=_shell(
            f"{sharer} shared a page with you",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            f"<strong>{sharer}</strong> shared “{title}” with you on "
            f"{settings.APP_NAME}, {settings.APP_TAGLINE}.</p>"
            + _quote(note)
            + "<p style='font-size:14px;line-height:1.6;margin:12px 0 0;'>"
            f"Create an account with this address to {what} it. The page opens "
            "as soon as you have confirmed your address.</p>"
            + _button(url, f"Create an account and open “{title}”")
            + f"<p style='font-size:12px;color:#6b7280;margin:16px 0 0;'>The "
            f"invitation is good for {days} days. If you were not expecting it, "
            "ignore this message and nothing will happen.</p>",
        ),
    )


def share_notice_email(
    to: str,
    *,
    sharer: str,
    title: str,
    url: str,
    can_edit: bool,
    note: str | None = None,
) -> Email:
    """Sent to somebody who already has an account. Same facts, shorter path."""
    what = "edit" if can_edit else "read"
    return Email(
        to=to,
        subject=f"{sharer} shared “{title}” with you on {settings.APP_NAME}",
        text=(
            f"{sharer} shared a page with you: “{title}”."
            f"{_quote_text(note)}\n"
            f"You can {what} it here:\n{url}\n\n"
            f"It is also in “Shared with me” in {settings.APP_NAME}."
        ),
        html=_shell(
            f"{sharer} shared a page with you",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            f"<strong>{sharer}</strong> shared “{title}” with you. You can "
            f"{what} it.</p>"
            + _quote(note)
            + _button(url, "Open the page")
            + "<p style='font-size:12px;color:#6b7280;margin:16px 0 0;'>"
            "It is also waiting under “Shared with me”.</p>",
        ),
    )


def password_changed_email(to: str) -> Email:
    """Sent after the fact. The one message the account owner needs if it was not them."""
    return Email(
        to=to,
        subject=f"Your {settings.APP_NAME} password was changed",
        text=(
            "Your password has just been changed and every other session was "
            "signed out.\n\n"
            "If this was not you, reset your password immediately."
        ),
        html=_shell(
            "Your password was changed",
            "<p style='font-size:14px;line-height:1.6;margin:0;'>"
            "Your password has just been changed, and every other session was "
            "signed out.</p>"
            "<p style='font-size:14px;line-height:1.6;margin:12px 0 0;'>"
            "If this was not you, reset your password immediately.</p>",
        ),
    )
