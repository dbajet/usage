from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Constants:
    app_name: str = "Usage"
    contact_email: str = "usage@edgy.world"
    cookie_name: str = "usage_session"
    session_days: int = 30
    login_link_minutes: int = 15
    login_links_active_max: int = 5
    login_link_min_seconds: float = 1.5
    webauthn_cookie_name: str = "usage_webauthn"
    webauthn_challenge_minutes: int = 5
    kind_water: str = "water"
    kind_electricity: str = "electricity"
    kind_gas: str = "gas"
    kind_mileage: str = "mileage"
    kinds: tuple[str, ...] = ("water", "electricity", "gas", "mileage")
    source_manual: str = "manual"
    source_photo: str = "photo"
    source_import: str = "import"
    photo_max_bytes: int = 10_000_000
    photo_media_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp", "image/gif")
    page_size: int = 25
    anthropic_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    anthropic_beta_fallbacks: str = "server-side-fallback-2026-07-01"
    meter_reader_timeout_seconds: int = 60
    meter_reader_max_tokens: int = 1024
    email_test_suffixes: tuple[str, ...] = (
        "@example.com", ".example.com", "@example.org", ".example.org", "@example.net", ".example.net",
        ".test", ".invalid", ".example", ".localhost",
    )
    first_admin_email: str = "dbajet@gmail.com"
    first_admin_name: str = "Denis Bajet"


Constants = _Constants()
