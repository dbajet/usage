from __future__ import annotations

import os
from unittest.mock import patch

from usage.libraries.settings_loader import SettingsLoader
from usage.structures.settings import Settings


def test_load() -> None:
    tested = SettingsLoader()

    # full environment
    environment = {
        "DATABASE_URL": "postgresql://user:password@host:5432/db",
        "USAGE_ENCRYPTION_KEY": "the-encryption-key",
        "USAGE_DEV_AUTH_LINKS": "False",
        "USAGE_COOKIE_SECURE": "True",
        "USAGE_BASE_URL": "https://usage.example.com/",
        "SES_SMTP_HOST": "smtp.example.com",
        "SES_SMTP_PORT": "465",
        "SES_SMTP_USERNAME": "the-username",
        "SES_SMTP_PASSWORD": "the-password",
        "SES_SENDER_EMAIL": "sender@example.com",
        "ANTHROPIC_API_KEY": "the-anthropic-key",
        "USAGE_ANTHROPIC_MODEL": "claude-sonnet-5",
    }
    with patch.dict(os.environ, environment, clear=True):
        result = tested.load()
    expected = Settings(
        database_url="postgresql://user:password@host:5432/db",
        encryption_key="the-encryption-key",
        dev_auth_links=False,
        cookie_secure=True,
        base_url="https://usage.example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-sonnet-5",
    )
    assert result == expected

    # empty environment falls back to the defaults
    with patch.dict(os.environ, {}, clear=True):
        result = tested.load()
    expected = Settings(
        database_url="postgresql://user_usage:usage_dev_password@usage-db:5432/db_usage",
        encryption_key="",
        dev_auth_links=True,
        cookie_secure=False,
        base_url="",
        smtp_host="",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_sender="",
        anthropic_api_key="",
        anthropic_model="claude-opus-5",
    )
    assert result == expected

    # empty SES_SMTP_PORT falls back to the default
    with patch.dict(os.environ, {"SES_SMTP_PORT": ""}, clear=True):
        result = tested.load()
    expected = Settings(
        database_url="postgresql://user_usage:usage_dev_password@usage-db:5432/db_usage",
        encryption_key="",
        dev_auth_links=True,
        cookie_secure=False,
        base_url="",
        smtp_host="",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_sender="",
        anthropic_api_key="",
        anthropic_model="claude-opus-5",
    )
    assert result == expected
