from __future__ import annotations

from typing import NamedTuple


class Settings(NamedTuple):
    database_url: str
    encryption_key: str
    dev_auth_links: bool
    cookie_secure: bool
    base_url: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_sender: str
    anthropic_api_key: str
    anthropic_model: str

    def to_dict(self) -> dict[str, str | bool | int]:
        return {
            "database_url": self.database_url,
            "encryption_key": self.encryption_key,
            "dev_auth_links": self.dev_auth_links,
            "cookie_secure": self.cookie_secure,
            "base_url": self.base_url,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "smtp_password": self.smtp_password,
            "smtp_sender": self.smtp_sender,
            "anthropic_api_key": self.anthropic_api_key,
            "anthropic_model": self.anthropic_model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Settings:
        return cls(
            database_url=str(data.get("database_url") or ""),
            encryption_key=str(data.get("encryption_key") or ""),
            dev_auth_links=bool(data.get("dev_auth_links")),
            cookie_secure=bool(data.get("cookie_secure")),
            base_url=str(data.get("base_url") or ""),
            smtp_host=str(data.get("smtp_host") or ""),
            smtp_port=int(str(data.get("smtp_port") or 0) or 0),
            smtp_username=str(data.get("smtp_username") or ""),
            smtp_password=str(data.get("smtp_password") or ""),
            smtp_sender=str(data.get("smtp_sender") or ""),
            anthropic_api_key=str(data.get("anthropic_api_key") or ""),
            anthropic_model=str(data.get("anthropic_model") or ""),
        )
