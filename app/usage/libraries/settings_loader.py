from __future__ import annotations

import os

from usage.structures.settings import Settings


class SettingsLoader:
    def load(self) -> Settings:
        return Settings(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql://user_usage:usage_dev_password@usage-db:5432/db_usage",
            ),
            encryption_key=os.environ.get("USAGE_ENCRYPTION_KEY", ""),
            dev_auth_links=os.environ.get("USAGE_DEV_AUTH_LINKS", "true").lower() == "true",
            cookie_secure=os.environ.get("USAGE_COOKIE_SECURE", "false").lower() == "true",
            base_url=os.environ.get("USAGE_BASE_URL", "").rstrip("/"),
            smtp_host=os.environ.get("SES_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SES_SMTP_PORT", "587") or "587"),
            smtp_username=os.environ.get("SES_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SES_SMTP_PASSWORD", ""),
            smtp_sender=os.environ.get("SES_SENDER_EMAIL", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.environ.get("USAGE_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        )
