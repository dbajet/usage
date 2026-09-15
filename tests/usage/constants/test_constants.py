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
        "source_import",
        "photo_max_bytes",
        "photo_media_types",
        "page_size",
        "anthropic_url",
        "anthropic_version",
        "anthropic_beta_fallbacks",
        "meter_reader_timeout_seconds",
        "meter_reader_max_tokens",
        "reminder_check_seconds",
        "reminder_hour",
        "reminder_minute",
        "sensor_ranges",
        "ingest_max_samples",
        "ingest_token_bytes",
        "alert_normal",
        "alert_below",
        "alert_above",
        "water_host_default",
        "water_hosts",
        "water_sign_in_path",
        "water_initiate_path",
        "water_status_path",
        "water_search_path",
        "water_resolution",
        "water_export_unit",
        "water_timeout_seconds",
        "water_poll_attempts",
        "water_poll_seconds",
        "water_sync_seconds",
        "water_claim_minutes",
        "water_recent_days",
        "water_chunk_days",
        "water_empty_chunks_max",
        "water_chunks_per_tick",
        "water_message_max",
        "water_unreadable_status",
        "water_leak_hours",
        "water_leak_span_hours",
        "water_leak_min_readings",
        "water_cubic_meters",
        "water_ranges",
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


def test_source_import() -> None:
    tested = Constants
    result = tested.source_import
    expected = "import"
    assert result == expected


def test_photo_max_bytes() -> None:
    tested = Constants
    result = tested.photo_max_bytes
    expected = 10_000_000
    assert result == expected


def test_photo_media_types() -> None:
    tested = Constants
    result = tested.photo_media_types
    expected = ("image/jpeg", "image/png", "image/webp", "image/gif")
    assert result == expected


def test_page_size() -> None:
    tested = Constants
    result = tested.page_size
    expected = 25
    assert result == expected


def test_anthropic_url() -> None:
    tested = Constants
    result = tested.anthropic_url
    expected = "https://api.anthropic.com/v1/messages"
    assert result == expected


def test_anthropic_version() -> None:
    tested = Constants
    result = tested.anthropic_version
    expected = "2023-06-01"
    assert result == expected


def test_anthropic_beta_fallbacks() -> None:
    tested = Constants
    result = tested.anthropic_beta_fallbacks
    expected = "server-side-fallback-2026-07-01"
    assert result == expected


def test_meter_reader_timeout_seconds() -> None:
    tested = Constants
    result = tested.meter_reader_timeout_seconds
    expected = 120
    assert result == expected


def test_meter_reader_max_tokens() -> None:
    tested = Constants
    result = tested.meter_reader_max_tokens
    expected = 4096
    assert result == expected


def test_reminder_check_seconds() -> None:
    tested = Constants
    result = tested.reminder_check_seconds
    expected = 300
    assert result == expected


def test_reminder_hour() -> None:
    tested = Constants
    result = tested.reminder_hour
    expected = 6
    assert result == expected


def test_reminder_minute() -> None:
    tested = Constants
    result = tested.reminder_minute
    expected = 15
    assert result == expected


def test_sensor_ranges() -> None:
    tested = Constants
    result = tested.sensor_ranges
    expected = ((1, 10), (7, 60), (30, 360), (365, 1440))
    assert result == expected


def test_ingest_max_samples() -> None:
    tested = Constants
    result = tested.ingest_max_samples
    expected = 1000
    assert result == expected


def test_ingest_token_bytes() -> None:
    tested = Constants
    result = tested.ingest_token_bytes
    expected = 32
    assert result == expected


def test_alert_normal() -> None:
    tested = Constants
    result = tested.alert_normal
    expected = ""
    assert result == expected


def test_alert_below() -> None:
    tested = Constants
    result = tested.alert_below
    expected = "below"
    assert result == expected


def test_alert_above() -> None:
    tested = Constants
    result = tested.alert_above
    expected = "above"
    assert result == expected


def test_water_host_default() -> None:
    tested = Constants
    result = tested.water_host_default
    expected = 'eyeonwater.com'
    assert result == expected


def test_water_hosts() -> None:
    tested = Constants
    result = tested.water_hosts
    expected = ('eyeonwater.com', 'eyeonwater.ca')
    assert result == expected


def test_water_sign_in_path() -> None:
    tested = Constants
    result = tested.water_sign_in_path
    expected = '/account/signin'
    assert result == expected


def test_water_initiate_path() -> None:
    tested = Constants
    result = tested.water_initiate_path
    expected = '/reports/export_initiate'
    assert result == expected


def test_water_status_path() -> None:
    tested = Constants
    result = tested.water_status_path
    expected = '/reports/export_check_status/'
    assert result == expected


def test_water_search_path() -> None:
    tested = Constants
    result = tested.water_search_path
    expected = '/api/2/residential/new_search'
    assert result == expected


def test_water_resolution() -> None:
    tested = Constants
    result = tested.water_resolution
    expected = 'quarter_hourly'
    assert result == expected


def test_water_export_unit() -> None:
    tested = Constants
    result = tested.water_export_unit
    expected = 'Gallons'
    assert result == expected


def test_water_timeout_seconds() -> None:
    tested = Constants
    result = tested.water_timeout_seconds
    expected = 120
    assert result == expected


def test_water_poll_attempts() -> None:
    tested = Constants
    result = tested.water_poll_attempts
    expected = 30
    assert result == expected


def test_water_poll_seconds() -> None:
    tested = Constants
    result = tested.water_poll_seconds
    expected = 2.0
    assert result == expected


def test_water_sync_seconds() -> None:
    tested = Constants
    result = tested.water_sync_seconds
    expected = 900
    assert result == expected


def test_water_claim_minutes() -> None:
    tested = Constants
    result = tested.water_claim_minutes
    expected = 30
    assert result == expected


def test_water_recent_days() -> None:
    tested = Constants
    result = tested.water_recent_days
    expected = 2
    assert result == expected


def test_water_chunk_days() -> None:
    tested = Constants
    result = tested.water_chunk_days
    expected = 31
    assert result == expected


def test_water_empty_chunks_max() -> None:
    tested = Constants
    result = tested.water_empty_chunks_max
    expected = 2
    assert result == expected


def test_water_chunks_per_tick() -> None:
    tested = Constants
    result = tested.water_chunks_per_tick
    expected = 4
    assert result == expected


def test_water_message_max() -> None:
    tested = Constants
    result = tested.water_message_max
    expected = 300
    assert result == expected


def test_water_unreadable_status() -> None:
    tested = Constants
    result = tested.water_unreadable_status
    expected = 422
    assert result == expected


def test_water_leak_hours() -> None:
    tested = Constants
    result = tested.water_leak_hours
    expected = 24
    assert result == expected


def test_water_leak_span_hours() -> None:
    tested = Constants
    result = tested.water_leak_span_hours
    expected = 23
    assert result == expected


def test_water_leak_min_readings() -> None:
    tested = Constants
    result = tested.water_leak_min_readings
    expected = 20
    assert result == expected


def test_water_cubic_meters() -> None:
    tested = Constants
    result = tested.water_cubic_meters
    expected = (
        ('CM', 1.0),
        ('CUBIC_METER', 1.0),
        ('CUBIC METERS', 1.0),
        ('LITER', 0.001),
        ('LITERS', 0.001),
        ('HECTOLITERS', 0.1),
        ('CF', 0.0283168466),
        ('CUBIC_FEET', 0.0283168466),
        ('CUBIC FEET', 0.0283168466),
        ('10 CF', 0.283168466),
        ('CCF', 2.83168466),
        ('GAL', 0.0037854118),
        ('GALLONS', 0.0037854118),
        ('10 GAL', 0.037854118),
        ('100 GAL', 0.37854118),
        ('KGAL', 3.7854118),
        ('IMPERIAL GALLONS', 0.00454609),
        ('ACRE FEET', 1233.48184),
        ('OIL BARRELS', 0.158987295),
        ('FLUID BARRELS', 0.119240471),
    )
    assert result == expected


def test_water_ranges() -> None:
    tested = Constants
    result = tested.water_ranges
    expected = ((1, 15), (7, 60), (30, 360), (365, 1440))
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
