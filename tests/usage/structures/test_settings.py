from __future__ import annotations

from tests.conftest import is_namedtuple
from usage.structures.settings import Settings


def test_class() -> None:
    tested = Settings
    fields = [
        "database_url",
        "encryption_key",
        "dev_auth_links",
        "cookie_secure",
        "base_url",
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_sender",
        "anthropic_api_key",
        "anthropic_model",
    ]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tested = Settings(
        database_url="postgresql://localhost/usage",
        encryption_key="the-key",
        dev_auth_links=True,
        cookie_secure=False,
        base_url="https://usage.example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="secret",
        smtp_sender="noreply@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-opus-5",
    )
    result = tested.to_dict()
    expected = {
        "database_url": "postgresql://localhost/usage",
        "encryption_key": "the-key",
        "dev_auth_links": True,
        "cookie_secure": False,
        "base_url": "https://usage.example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "mailer",
        "smtp_password": "secret",
        "smtp_sender": "noreply@example.com",
        "anthropic_api_key": "the-anthropic-key",
        "anthropic_model": "claude-opus-5",
    }
    assert result == expected


def test_from_dict() -> None:
    tested = Settings
    tests: list[tuple[dict[str, object], Settings]] = [
        (
            {
                "database_url": "postgresql://localhost/usage",
                "encryption_key": "the-key",
                "dev_auth_links": True,
                "cookie_secure": True,
                "base_url": "https://usage.example.com",
                "smtp_host": "smtp.example.com",
                "smtp_port": "587",
                "smtp_username": "mailer",
                "smtp_password": "secret",
                "smtp_sender": "noreply@example.com",
                "anthropic_api_key": "the-anthropic-key",
                "anthropic_model": "claude-opus-5",
            },
            Settings(
                database_url="postgresql://localhost/usage",
                encryption_key="the-key",
                dev_auth_links=True,
                cookie_secure=True,
                base_url="https://usage.example.com",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="mailer",
                smtp_password="secret",
                smtp_sender="noreply@example.com",
                anthropic_api_key="the-anthropic-key",
                anthropic_model="claude-opus-5",
            ),
        ),
        (
            {},
            Settings(
                database_url="",
                encryption_key="",
                dev_auth_links=False,
                cookie_secure=False,
                base_url="",
                smtp_host="",
                smtp_port=0,
                smtp_username="",
                smtp_password="",
                smtp_sender="",
                anthropic_api_key="",
                anthropic_model="",
            ),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
