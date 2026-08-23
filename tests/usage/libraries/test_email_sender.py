from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, call, patch

from usage.libraries.email_sender import EmailSender
from usage.structures.settings import Settings


def helper_settings(
    smtp_host: str = "smtp.example.com",
    smtp_port: int = 587,
    smtp_username: str = "the-username",
    smtp_password: str = "the-password",
    smtp_sender: str = "sender@example.com",
) -> Settings:
    return Settings(
        database_url="postgresql://user:password@host:5432/db",
        encryption_key="the-key",
        dev_auth_links=False,
        cookie_secure=True,
        base_url="https://usage.example.com",
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        smtp_sender=smtp_sender,
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-haiku-4-5-20251001",
    )


def helper_instance(smtp_port: int = 587) -> EmailSender:
    return EmailSender(helper_settings(smtp_port=smtp_port))


def test___init__() -> None:
    tested = helper_instance()
    exp_host = "smtp.example.com"
    assert tested._host == exp_host
    exp_port = 587
    assert tested._port == exp_port
    exp_username = "the-username"
    assert tested._username == exp_username
    exp_password = "the-password"
    assert tested._password == exp_password
    exp_sender = "sender@example.com"
    assert tested._sender == exp_sender


def test_is_configured() -> None:
    tests = [
        (helper_settings(), True),
        (helper_settings(smtp_host=""), False),
        (helper_settings(smtp_username=""), False),
        (helper_settings(smtp_password=""), False),
        (helper_settings(smtp_sender=""), False),
        (helper_settings(smtp_host="", smtp_username="", smtp_password="", smtp_sender=""), False),
    ]
    for settings, expected in tests:
        tested = EmailSender(settings)
        result = tested.is_configured()
        assert result is expected, f"---> {settings}"


@patch("usage.libraries.email_sender.logging")
@patch("usage.libraries.email_sender.EmailMessage")
@patch("usage.libraries.email_sender.smtplib")
def test_send(mock_smtplib: MagicMock, mock_email_message: MagicMock, mock_logging: MagicMock) -> None:
    mock_message = MagicMock()
    mock_smtp = MagicMock()
    mock_logger = MagicMock()

    def reset_mocks() -> None:
        mock_smtplib.reset_mock()
        mock_email_message.reset_mock()
        mock_logging.reset_mock()
        mock_message.reset_mock()
        mock_smtp.reset_mock()
        mock_logger.reset_mock()

    exp_message_calls = [
        call.__setitem__("From", "Usage <sender@example.com>"),
        call.__setitem__("To", "to@edgy.world"),
        call.__setitem__("Subject", "The subject"),
        call.__setitem__("Reply-To", "usage@edgy.world"),
        call.__setitem__("List-Unsubscribe", "<mailto:usage@edgy.world?subject=unsubscribe>"),
        call.set_content("line one\nline two\n\n—\nUsage · usage@edgy.world"),
    ]

    # not configured
    tested = EmailSender(helper_settings(smtp_host=""))
    result = tested.send("to@example.com", "The subject", ["line one", "line two"])
    assert result is False
    assert mock_smtplib.mock_calls == []
    assert mock_email_message.mock_calls == []
    assert mock_logging.mock_calls == []
    assert mock_message.mock_calls == []
    assert mock_smtp.mock_calls == []
    assert mock_logger.mock_calls == []
    reset_mocks()

    # a reserved test domain never reaches the relay
    mock_logging.getLogger.side_effect = [mock_logger]
    tested = helper_instance()
    result = tested.send("to@example.com", "The subject", ["line one", "line two"])
    assert result is False
    assert mock_smtplib.mock_calls == []
    assert mock_email_message.mock_calls == []
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert mock_message.mock_calls == []
    assert mock_smtp.mock_calls == []
    assert mock_logger.mock_calls == [call.info("[EMAIL] suppressed test recipient %s", "to@example.com")]
    reset_mocks()

    # port 587 uses SMTP with STARTTLS
    mock_email_message.side_effect = [mock_message]
    mock_smtplib.SMTP.side_effect = [mock_smtp]
    mock_smtp.__enter__.side_effect = [mock_smtp]
    mock_smtp.__exit__.side_effect = [False]
    tested = helper_instance(smtp_port=587)
    result = tested.send("to@edgy.world", "The subject", ["line one", "line two"])
    assert result is True
    exp_calls = [call.SMTP("smtp.example.com", 587, timeout=20)]
    assert mock_smtplib.mock_calls == exp_calls
    exp_calls = [call()]
    assert mock_email_message.mock_calls == exp_calls
    assert mock_logging.mock_calls == []
    assert mock_message.mock_calls == exp_message_calls
    exp_calls = [
        call.__enter__(),
        call.starttls(),
        call.login("the-username", "the-password"),
        call.send_message(mock_message),
        call.__exit__(None, None, None),
    ]
    assert mock_smtp.mock_calls == exp_calls
    assert mock_logger.mock_calls == []
    reset_mocks()

    # port 465 uses SMTP_SSL without STARTTLS
    mock_email_message.side_effect = [mock_message]
    mock_smtplib.SMTP_SSL.side_effect = [mock_smtp]
    mock_smtp.__enter__.side_effect = [mock_smtp]
    mock_smtp.__exit__.side_effect = [False]
    tested = helper_instance(smtp_port=465)
    result = tested.send("to@edgy.world", "The subject", ["line one", "line two"])
    assert result is True
    exp_calls = [call.SMTP_SSL("smtp.example.com", 465, timeout=20)]
    assert mock_smtplib.mock_calls == exp_calls
    exp_calls = [call()]
    assert mock_email_message.mock_calls == exp_calls
    assert mock_logging.mock_calls == []
    assert mock_message.mock_calls == exp_message_calls
    exp_calls = [
        call.__enter__(),
        call.login("the-username", "the-password"),
        call.send_message(mock_message),
        call.__exit__(None, None, None),
    ]
    assert mock_smtp.mock_calls == exp_calls
    assert mock_logger.mock_calls == []
    reset_mocks()

    # SMTP failure is logged and returns False
    error = smtplib.SMTPException("connection lost")
    mock_smtplib.SMTPException = smtplib.SMTPException
    mock_email_message.side_effect = [mock_message]
    mock_smtplib.SMTP.side_effect = [mock_smtp]
    mock_smtp.__enter__.side_effect = [mock_smtp]
    mock_smtp.__exit__.side_effect = [False]
    mock_smtp.login.side_effect = error
    mock_logging.getLogger.side_effect = [mock_logger]
    tested = helper_instance(smtp_port=587)
    result = tested.send("to@edgy.world", "The subject", ["line one", "line two"])
    assert result is False
    exp_calls = [call.SMTP("smtp.example.com", 587, timeout=20)]
    assert mock_smtplib.mock_calls == exp_calls
    exp_calls = [call()]
    assert mock_email_message.mock_calls == exp_calls
    exp_calls = [call.getLogger("usage")]
    assert mock_logging.mock_calls == exp_calls
    assert mock_message.mock_calls == exp_message_calls
    exp_calls = [
        call.__enter__(),
        call.starttls(),
        call.login("the-username", "the-password"),
        call.__exit__(smtplib.SMTPException, error, error.__traceback__),
    ]
    assert mock_smtp.mock_calls == exp_calls
    exp_calls = [call.warning("[EMAIL] send failed to %s: %s", "to@edgy.world", error)]
    assert mock_logger.mock_calls == exp_calls
    reset_mocks()


def test__is_test_recipient() -> None:
    tested = helper_instance()
    tests = [
        ("to@example.com", True),
        ("to@sub.example.com", True),
        ("to@example.org", True),
        ("to@example.net", True),
        ("to@usage.test", True),
        ("to@usage.invalid", True),
        ("to@usage.example", True),
        ("to@localhost.localhost", True),
        (" To@Example.COM ", True),
        ("to@edgy.world", False),
        ("to@gmail.com", False),
        ("to@latest.net", False),
    ]
    for recipient, expected in tests:
        result = tested._is_test_recipient(recipient)
        assert result is expected, f"---> {recipient}"
