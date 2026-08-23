from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Constants:
    app_name: str = "Usage"
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
    photo_max_bytes: int = 10_000_000
    page_size: int = 25
    first_admin_email: str = "dbajet@gmail.com"
    first_admin_name: str = "Denis Bajet"


Constants = _Constants()
