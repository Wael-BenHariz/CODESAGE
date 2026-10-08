"""Mail senders (plan Step 11 / N4) — the seam that actually leaves the app.

Contracts covered here:

- **Factory**: ``MAIL_BACKEND=smtp`` builds an ``SmtpMailSender`` from the
  ``SMTP_*`` settings; anything else falls back to ``ConsoleMailSender``
  (the v0.3.0 default, which logs the invite link and never sends).
- **SMTP shape**: STARTTLS before AUTH, login only when a user is set,
  ``From``/``To``/``Subject`` carried through — ``SmtpMailSender`` is
  STARTTLS-only (port 587), there is no SMTP_SSL path for 465.
- **Delivery logging**: a send now leaves ``invitation_mail_sent`` behind,
  otherwise success is invisible (senders are quiet and the body never
  reaches an app log for a real transport).
- **Failure semantics**: a transport error is logged as
  ``invitation_mail_failed`` and swallowed — mail must never fail the
  invitation itself (the row is already committed).
- **No token leak**: the raw invite link travels only in the message body,
  never in any log line.
"""

import logging
from email.message import EmailMessage
from typing import ClassVar

import pytest

from app.services import mail

TOKEN = "raw-token-that-must-not-be-logged"
INVITE_URL = f"http://localhost:4200/invite/accept?token={TOKEN}"


# --- factory -----------------------------------------------------------------


def test_factory_defaults_to_console(monkeypatch):
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "console")
    assert isinstance(mail.get_mail_sender(), mail.ConsoleMailSender)


def test_factory_builds_smtp_sender_from_settings(monkeypatch):
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "smtp")
    monkeypatch.setattr(mail.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(mail.settings, "SMTP_PORT", 2525)
    monkeypatch.setattr(mail.settings, "SMTP_USER", "sender@example.com")
    monkeypatch.setattr(mail.settings, "SMTP_PASSWORD", "app-password")
    monkeypatch.setattr(mail.settings, "SMTP_FROM", "noreply@example.com")
    monkeypatch.setattr(mail.settings, "SMTP_TLS", True)

    sender = mail.get_mail_sender()

    assert isinstance(sender, mail.SmtpMailSender)
    assert sender._host == "smtp.example.com"
    assert sender._port == 2525
    assert sender._user == "sender@example.com"
    assert sender._password == "app-password"
    assert sender._sender == "noreply@example.com"
    assert sender._tls is True


def test_factory_falls_back_to_console_for_unknown_backend(monkeypatch):
    """The validator rejects unknown values at boot, but a value set after
    import must still not produce a sender that explodes."""
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "carrier-pigeon")
    assert isinstance(mail.get_mail_sender(), mail.ConsoleMailSender)


# --- console sender ----------------------------------------------------------


def test_console_sender_logs_body_but_sends_nothing(caplog):
    with caplog.at_level(logging.INFO):
        mail.ConsoleMailSender().send(to="a@b.c", subject="Hi", body="link here")

    assert "mail_console to=a@b.c" in caplog.text
    assert "link here" in caplog.text


# --- smtp sender -------------------------------------------------------------


class _FakeSMTP:
    """Records the SMTP conversation instead of talking to a server."""

    instances: ClassVar[list["_FakeSMTP"]] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        self.quit_called = False
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.message = message

    def quit(self):
        self.quit_called = True


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mail.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def _smtp_sender(**overrides) -> mail.SmtpMailSender:
    kwargs: dict = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "sender@example.com",
        "password": "app-password",
        "sender": "noreply@example.com",
        "tls": True,
    }
    kwargs.update(overrides)
    return mail.SmtpMailSender(**kwargs)


def test_smtp_sender_starttls_then_login_then_send(fake_smtp):
    _smtp_sender().send(to="to@example.com", subject="Subject", body="Body text")

    (conn,) = fake_smtp.instances
    assert (conn.host, conn.port) == ("smtp.example.com", 587)
    assert conn.starttls_called, "STARTTLS must happen before AUTH"
    assert conn.login_args == ("sender@example.com", "app-password")
    assert conn.message["To"] == "to@example.com"
    assert conn.message["From"] == "noreply@example.com"
    assert conn.message["Subject"] == "Subject"
    assert "Body text" in conn.message.get_content()


def test_smtp_sender_skips_login_without_user(fake_smtp):
    _smtp_sender(user="", password="").send(to="to@example.com", subject="S", body="B")

    (conn,) = fake_smtp.instances
    assert conn.login_args is None
    assert conn.message is not None


def test_smtp_sender_without_tls_does_not_starttls(fake_smtp):
    _smtp_sender(tls=False).send(to="to@example.com", subject="S", body="B")

    (conn,) = fake_smtp.instances
    assert conn.starttls_called is False
    assert conn.login_args == ("sender@example.com", "app-password")


def test_smtp_sender_surfaces_transport_errors(monkeypatch):
    """Raises so ``send_invitation_email`` can log it — swallowing here would
    make a broken relay indistinguishable from success."""

    class Boom:
        def __init__(self, *args, **kwargs):
            raise ConnectionRefusedError("relay down")

    monkeypatch.setattr(mail.smtplib, "SMTP", Boom)

    with pytest.raises(ConnectionRefusedError):
        _smtp_sender().send(to="to@example.com", subject="S", body="B")


# --- send_invitation_email ---------------------------------------------------


def test_success_is_logged_without_the_raw_token(caplog, fake_smtp, monkeypatch):
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "smtp")

    with caplog.at_level(logging.INFO):
        mail.send_invitation_email(
            to="invitee@example.com",
            org_name="Acme",
            role="REVIEWER",
            invite_url=INVITE_URL,
        )

    assert "invitation_mail_sent" in caplog.text
    assert "backend=smtp" in caplog.text
    assert "invitee@example.com" in caplog.text
    assert "Acme" in caplog.text
    assert "REVIEWER" in caplog.text
    # The raw token exists only in the message body, never in a log line.
    assert TOKEN not in caplog.text
    assert INVITE_URL not in caplog.text


def test_transport_failure_is_logged_and_swallowed(caplog, monkeypatch):
    """Mail failures never fail the invitation — the row is already committed."""

    class ExplodingSender:
        def send(self, *, to, subject, body):
            raise OSError("535 auth failed")

    monkeypatch.setattr(mail, "get_mail_sender", lambda: ExplodingSender())

    with caplog.at_level(logging.ERROR):
        mail.send_invitation_email(
            to="invitee@example.com",
            org_name="Acme",
            role="DEVELOPER",
            invite_url=INVITE_URL,
        )

    assert "invitation_mail_failed" in caplog.text
    assert "invitee@example.com" in caplog.text
    assert TOKEN not in caplog.text


def test_body_contains_role_org_link_and_ttl(caplog, fake_smtp, monkeypatch):
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "smtp")

    mail.send_invitation_email(
        to="invitee@example.com",
        org_name="Acme",
        role="REVIEWER",
        invite_url=INVITE_URL,
    )

    (conn,) = fake_smtp.instances
    body = conn.message.get_content()
    assert "Acme" in body
    assert "REVIEWER" in body
    assert INVITE_URL in body
    assert "7 days" in body
    assert conn.message["Subject"] == "You have been invited to join Acme on CodeSage"


def test_console_backend_still_logs_the_link_for_dev(caplog, monkeypatch):
    """The v0.3.0 default: the invite link is reachable in the pod log when
    no SMTP relay is configured (documented troubleshooting path)."""
    monkeypatch.setattr(mail.settings, "MAIL_BACKEND", "console")

    with caplog.at_level(logging.INFO):
        mail.send_invitation_email(
            to="invitee@example.com",
            org_name="Acme",
            role="DEVELOPER",
            invite_url=INVITE_URL,
        )

    assert "mail_console" in caplog.text
    assert TOKEN in caplog.text  # by design, console sender
    assert "invitation_mail_sent backend=console" in caplog.text
