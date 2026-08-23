from __future__ import annotations

from tests.conftest import is_dataclass
from usage.constants.constants import Constants, _Constants


def test_class() -> None:
    tested = _Constants
    fields = [
        "app_name",
        "contact_email",
        "cookie_name",
        "session_days",
        "login_link_minutes",
        "login_links_active_max",
        "login_link_min_seconds",
        "webauthn_cookie_name",
        "webauthn_challenge_minutes",
        "kind_water",
        "kind_electricity",
        "kind_gas",
        "kind_mileage",
        "kinds",
        "source_manual",
        "source_photo",
        "photo_max_bytes",
        "page_size",
        "email_test_suffixes",
        "first_admin_email",
        "first_admin_name",
    ]
    result = is_dataclass(tested, fields)
    assert result is True


def test_app_name() -> None:
    tested = Constants
    result = tested.app_name
    expected = "Usage"
    assert result == expected


def test_contact_email() -> None:
    tested = Constants
    result = tested.contact_email
    expected = "usage@edgy.world"
    assert result == expected


def test_cookie_name() -> None:
    tested = Constants
    result = tested.cookie_name
    expected = "usage_session"
    assert result == expected


def test_session_days() -> None:
    tested = Constants
    result = tested.session_days
    expected = 30
    assert result == expected


def test_login_link_minutes() -> None:
    tested = Constants
    result = tested.login_link_minutes
    expected = 15
    assert result == expected


def test_login_links_active_max() -> None:
    tested = Constants
    result = tested.login_links_active_max
    expected = 5
    assert result == expected


def test_login_link_min_seconds() -> None:
    tested = Constants
    result = tested.login_link_min_seconds
    expected = 1.5
    assert result == expected


def test_webauthn_cookie_name() -> None:
    tested = Constants
    result = tested.webauthn_cookie_name
    expected = "usage_webauthn"
    assert result == expected


def test_webauthn_challenge_minutes() -> None:
    tested = Constants
    result = tested.webauthn_challenge_minutes
    expected = 5
    assert result == expected


def test_kind_water() -> None:
    tested = Constants
    result = tested.kind_water
    expected = "water"
    assert result == expected


def test_kind_electricity() -> None:
    tested = Constants
    result = tested.kind_electricity
    expected = "electricity"
    assert result == expected


def test_kind_gas() -> None:
    tested = Constants
    result = tested.kind_gas
    expected = "gas"
    assert result == expected


def test_kind_mileage() -> None:
    tested = Constants
    result = tested.kind_mileage
    expected = "mileage"
    assert result == expected


def test_kinds() -> None:
    tested = Constants
    result = tested.kinds
    expected = ("water", "electricity", "gas", "mileage")
    assert result == expected


def test_source_manual() -> None:
    tested = Constants
    result = tested.source_manual
    expected = "manual"
    assert result == expected


def test_source_photo() -> None:
    tested = Constants
    result = tested.source_photo
    expected = "photo"
    assert result == expected


def test_photo_max_bytes() -> None:
    tested = Constants
    result = tested.photo_max_bytes
    expected = 10_000_000
    assert result == expected


def test_page_size() -> None:
    tested = Constants
    result = tested.page_size
    expected = 25
    assert result == expected


def test_email_test_suffixes() -> None:
    tested = Constants
    result = tested.email_test_suffixes
    expected = (
        "@example.com", ".example.com", "@example.org", ".example.org", "@example.net", ".example.net",
        ".test", ".invalid", ".example", ".localhost",
    )
    assert result == expected


def test_first_admin_email() -> None:
    tested = Constants
    result = tested.first_admin_email
    expected = "dbajet@gmail.com"
    assert result == expected


def test_first_admin_name() -> None:
    tested = Constants
    result = tested.first_admin_name
    expected = "Denis Bajet"
    assert result == expected
