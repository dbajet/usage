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
    meter_reader_timeout_seconds: int = 120
    meter_reader_max_tokens: int = 4096
    reminder_check_seconds: int = 300
    reminder_hour: int = 6
    reminder_minute: int = 15
    # Sensor series: (range in days, bucket in minutes) - about 150 points per range.
    sensor_ranges: tuple[tuple[int, int], ...] = ((1, 10), (7, 60), (30, 360), (365, 1440))
    ingest_max_samples: int = 1000
    ingest_token_bytes: int = 32
    # A sensor sits in exactly one of these states; the email goes out when it changes.
    alert_normal: str = ""
    alert_below: str = "below"
    alert_above: str = "above"
    # EyeOnWater: the "Export Data" button and nothing else - sign in, ask for a
    # CSV over a date range, poll the task, download it. The portal has no
    # documented API, so the fewer endpoints touched the better.
    water_host_default: str = "eyeonwater.com"
    water_hosts: tuple[str, ...] = ("eyeonwater.com", "eyeonwater.ca")
    water_sign_in_path: str = "/account/signin"
    water_initiate_path: str = "/reports/export_initiate"
    water_status_path: str = "/reports/export_check_status/"
    # Asked once, when a feed is set up, to turn an account into a meter uuid.
    water_search_path: str = "/api/2/residential/new_search"
    water_resolution: str = "quarter_hourly"
    # Gallons because that is the value the portal's own button sends. Cubic
    # Meters and CM are accepted too, so this is only a preference for the
    # request seen working: `export_unit` governs the CSV's `Flow` column alone,
    # and both columns are converted from the unit the CSV itself names.
    water_export_unit: str = "Gallons"
    water_timeout_seconds: int = 120
    water_poll_attempts: int = 30
    water_poll_seconds: float = 2.0
    # The meter publishes a few hours late, so a quarter-hour of freshness is
    # pointless: a quarter of an hour between pulls is already generous.
    water_sync_seconds: int = 900
    water_claim_minutes: int = 30
    # Re-asking for the last couple of days costs one export and repairs the
    # rows EyeOnWater re-estimates after the fact.
    water_recent_days: int = 2
    water_chunk_days: int = 31
    water_empty_chunks_max: int = 2
    water_chunks_per_tick: int = 4
    water_message_max: int = 300
    # An export whose rows cannot be read: deterministic, so the backfill walks
    # past it rather than retrying the same month for ever.
    water_unreadable_status: int = 422
    # A house always has some idle stretch in any 24 hours - asleep, out, the taps
    # shut. A rolling 24 hours without one means something is running that nobody
    # turned on. Rolling, not midnight to midnight: a stretch from one afternoon
    # to the next counts just as much, and calendar days would step over it.
    water_leak_hours: int = 24
    water_leak_span_hours: int = 23
    water_leak_min_readings: int = 20
    # Cubic metres per unit: the CSV reports `Read` in the meter's own unit
    # whatever `export_unit` asks for, so the reading has to be converted.
    water_cubic_meters: tuple[tuple[str, float], ...] = (
        ("CM", 1.0),
        ("CUBIC_METER", 1.0),
        ("CUBIC METERS", 1.0),
        ("LITER", 0.001),
        ("LITERS", 0.001),
        ("HECTOLITERS", 0.1),
        ("CF", 0.0283168466),
        ("CUBIC_FEET", 0.0283168466),
        ("CUBIC FEET", 0.0283168466),
        ("10 CF", 0.283168466),
        ("CCF", 2.83168466),
        ("GAL", 0.0037854118),
        ("GALLONS", 0.0037854118),
        ("10 GAL", 0.037854118),
        ("100 GAL", 0.37854118),
        ("KGAL", 3.7854118),
        ("IMPERIAL GALLONS", 0.00454609),
        ("ACRE FEET", 1233.48184),
        ("OIL BARRELS", 0.158987295),
        ("FLUID BARRELS", 0.119240471),
    )
    # Water is a counter, so its buckets are sums - and the day view keeps the
    # meter's own quarter-hour rather than inventing emptier buckets.
    water_ranges: tuple[tuple[int, int], ...] = ((1, 15), (7, 60), (30, 360), (365, 1440))
    email_test_suffixes: tuple[str, ...] = (
        "@example.com", ".example.com", "@example.org", ".example.org", "@example.net", ".example.net",
        ".test", ".invalid", ".example", ".localhost",
    )
    first_admin_email: str = "dbajet@gmail.com"
    first_admin_name: str = "Denis Bajet"


Constants = _Constants()
