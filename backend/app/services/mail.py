"""Pluggable invitation mail (plan Step 11 / N4).

``MailSender`` is the seam: ``ConsoleMailSender`` is the v0.3.0 default
(``MAIL_BACKEND=console`` — logs subject + body including the invite
link, never sends) and ``SmtpMailSender`` delivers for real when
``MAIL_BACKEND=smtp`` is configured. The SMTP settings exist in config
but are intentionally untested against a live server this release — the
console backend is the default and the only one exercised by tests.

The raw invitation token appears ONLY in the invite link handed to the
sender — it is never logged by application code outside a sender body.
"""

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class MailSender(Protocol):
    """Anything that can deliver a plain-text message."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        """Deliver (or log) one message. Raise to fail the caller."""
        ...


class ConsoleMailSender:
    """Dev default: log subject + body (invite link included), never send."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info(
            "mail_console to=%s subject=%s\n%s",
            to,
            subject,
            body,
        )


class SmtpMailSender:
    """Real delivery via SMTP (``MAIL_BACKEND=smtp`` + SMTP_* config)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        sender: str,
        tls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender = sender
        self._tls = tls

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            if self._tls:
                smtp.starttls()
            if self._user:
                smtp.login(self._user, self._password)
            smtp.send_message(message)


def get_mail_sender() -> MailSender:
    """Factory — config decides which sender the app talks to."""
    if settings.MAIL_BACKEND == "smtp":
        return SmtpMailSender(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            sender=settings.SMTP_FROM,
            tls=settings.SMTP_TLS,
        )
    return ConsoleMailSender()


def send_invitation_email(
    *,
    to: str,
    org_name: str,
    role: str,
    invite_url: str,
) -> None:
    """Deliver one invitation — the ONLY place the raw link leaves the app.

    Failures never fail the invitation itself: the row is already
    committed and the admin can copy the flow again; a delivery problem
    is logged, not raised.
    """
    subject = f"You have been invited to join {org_name} on CodeSage"
    body = (
        f"Hello,\n\n"
        f"You have been invited to join the organization {org_name!r} "
        f"as {role}.\n\n"
        f"Accept your invitation:\n{invite_url}\n\n"
        f"The link expires in 7 days.\n\n"
        f"— CodeSage\n"
    )
    try:
        get_mail_sender().send(to=to, subject=subject, body=body)
    except Exception:
        logger.exception("invitation_mail_failed to=%s org=%s", to, org_name)
        return
    # Success is otherwise invisible: senders are deliberately quiet and the
    # body never reaches an app log for a real transport (only the console
    # sender logs it). Grep target for "did the invite actually go out?" —
    # never includes the raw token.
    logger.info(
        "invitation_mail_sent backend=%s to=%s org=%s role=%s",
        settings.MAIL_BACKEND,
        to,
        org_name,
        role,
    )
