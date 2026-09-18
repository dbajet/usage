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
    # What a Realtime graph says about its own pace, beside its points. A feed
    # is only worth asking again once the thing behind it could have answered:
    # a gateway pushing every minute earns a minute, a water meter pulled every
    # quarter-hour earns the quarter-hour. Both ends are held - an overdue feed
    # must not turn the page into a spin, and a quiet one is still looked in on,
    # because a backfill is not on any schedule the page can read.
    realtime_poll_min_seconds: int = 30
    realtime_poll_max_seconds: int = 900
    # A push arrives on Home Assistant's own cadence, which is the house's
    # business and not this app's: it is measured from the gap between two of
    # them rather than assumed here. This is only what stands in until two have
    # been seen, and the longest gap allowed to teach it - an outage is not a
    # cadence, and one must not put the page to sleep for the afternoon.
    realtime_push_default_seconds: int = 600
    realtime_push_max_seconds: int = 1800
    # Long enough that two different graphs never collide, short enough to be
    # worth sending on every answer.
    realtime_stamp_length: int = 16
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
    # SwitchBot's cloud API (v1.1), which is how a house with no Home Assistant
    # gets its thermometers in. Two calls - what the account has, and what one
    # device reads now - and no history endpoint of any kind, so a house fed
    # this way starts the day it is switched on and nothing is backfilled.
    switchbot_host: str = "api.switch-bot.com"
    switchbot_devices_path: str = "/v1.1/devices"
    switchbot_status_path: str = "/v1.1/devices/{device_id}/status"
    switchbot_timeout_seconds: int = 30
    # SwitchBot answers 200 and puts its verdict in the body; 100 is success.
    switchbot_success_code: int = 100
    # Anything else it says: a device the hub could not reach, a parameter it
    # did not like. Deterministic for this tick, so that device is skipped
    # rather than the whole feed failing on it.
    switchbot_unreadable_status: int = 422
    switchbot_message_max: int = 300
    # The loop looks every minute and pulls a feed every ten, as the water one
    # does: a feed just added should show something straight away rather than
    # sitting empty, which reads exactly like a feed that does not work.
    #
    # Ten minutes because that is the finest bucket the graph draws and the
    # cadence Home Assistant pushes at, so both houses' graphs have the same
    # resolution. It also sets what a feed can afford: a tick costs one call
    # plus one per device behind the chosen hubs, so the day's allowance covers
    # about sixty devices - far more than a house has, and the limiter below is
    # what says so out loud if one ever gets there.
    switchbot_tick_seconds: int = 60
    switchbot_sync_seconds: int = 600
    switchbot_claim_minutes: int = 10
    # The allowance is the token's and the day's - ten thousand calls - and a
    # slot is left spare because we count a call when we make it and SwitchBot
    # counts it when it lands. Nobody waits out a day for a slot: a tick that
    # cannot have one says so and is tried again on the next.
    switchbot_calls_per_day: int = 9_000
    switchbot_rate_window_seconds: float = 86_400.0
    switchbot_rate_wait_seconds: float = 0.0
    # A pulled sensor is named after the device, there being no Home Assistant
    # entity to name it after.
    switchbot_entity_prefix: str = "switchbot."
    # The humidity of the same device, collected hidden: a percentage has no
    # business on the temperature graph, but it moves while a room holds still,
    # which is what proves the thermometer is still being heard from. Unhide it
    # in Settings, Sensors to draw it like any other.
    switchbot_humidity_suffix: str = ".humidity"
    switchbot_temperature_unit: str = "°C"
    switchbot_humidity_unit: str = "%"
    # Enough of a token to tell two accounts apart in a list, and no more: it
    # is a credential, and the form never shows one again once it is stored.
    switchbot_token_tail: int = 6
    # A device with no hub says so two different ways and neither is an id: an
    # empty string, and the twelve zeros SwitchBot's own samples show. Both mean
    # the cloud cannot place the device, and they answer to one name here.
    switchbot_zero_hub_id: str = "000000000000"
    switchbot_no_hub_id: str = "none"
    # How a hub with nothing behind it yet is still recognised as a place. Only
    # the picker's grouping rests on this, never what is collected - and "Hub"
    # has been in the type of every one of them, from the Hub Mini to the Hub 3.
    switchbot_hub_type: str = "hub"
    # The webhook, which is the only thing that knows when a reading was taken.
    # SwitchBot posts a `changeReport` to one URL per account as the change
    # happens, carrying the instant the device sampled it - where a status call
    # carries no instant at all and a poll can only date a change to somewhere
    # inside its own interval.
    switchbot_webhook_setup_path: str = "/v1.1/webhook/setupWebhook"
    switchbot_webhook_delete_path: str = "/v1.1/webhook/deleteWebhook"
    switchbot_webhook_all_devices: str = "ALL"
    switchbot_event_path: str = "/api/switchbot/events/"
    switchbot_event_change: str = "changeReport"
    switchbot_event_token_bytes: int = 32
    # Nothing signs the incoming POST - SwitchBot documents no signature for it
    # at all - so the secret is the URL, and it is generated here rather than
    # chosen. It has to be recoverable to be registered with them, so it is
    # sealed like a password rather than only hashed like the house's token.
    switchbot_webhook_scheme: str = "https://"
    # What a Fahrenheit reading has to become: everything is stored in Celsius,
    # the unit a status call answers in.
    switchbot_scale_fahrenheit: str = "FAHRENHEIT"
    switchbot_fahrenheit_offset: float = 32.0
    switchbot_fahrenheit_factor: float = 1.8
    # `timeOfSample` is epoch milliseconds, but a seconds value would be a
    # plausible reading of the same field and would land the sample in 1970.
    # Anything below this is taken to be seconds; anything outside the window
    # around now is not trusted at all and the arrival stands in for it.
    switchbot_epoch_millis_floor: int = 100_000_000_000
    switchbot_event_future_seconds: int = 3600
    switchbot_event_past_days: int = 7
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
    # pointless: a quarter of an hour between pulls of one feed is already generous.
    water_sync_seconds: int = 900
    # The loop looks far more often than it pulls, and asks the database which
    # feeds are due. A feed added or reset between two pulls would otherwise sit
    # untouched for a quarter of an hour with nothing at all to show for itself,
    # which reads exactly like a feed that does not work.
    water_tick_seconds: int = 60
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
    # Enphase Enlighten, developer API v4. Unlike the water portal this one is
    # metered: every request counts against the plan's monthly allowance, which
    # is what shapes the whole design below.
    enphase_host: str = "api.enphaseenergy.com"
    enphase_authorize_path: str = "/oauth/authorize"
    enphase_token_path: str = "/oauth/token"
    # Enphase's own landing page, which prints the authorisation code for the
    # person to paste back. Registering a redirect that points at this app would
    # mean a public unauthenticated route whose only job is to catch one code a
    # year: the paste costs the admin ten seconds and costs the app nothing.
    enphase_redirect_uri: str = "https://api.enphaseenergy.com/oauth/redirect_uri"
    enphase_systems_path: str = "/api/v4/systems"
    enphase_production_path: str = "/api/v4/systems/{system_id}/telemetry/production_meter"
    # Which endpoint answers for production on a given system, once it is known.
    # An empty string means nobody has found out yet.
    enphase_production_meter: str = "meter"
    enphase_production_micro: str = "micro"
    # The fallback for a system with no production CTs: the microinverters always
    # report what they made, whether or not a meter was fitted to measure it.
    enphase_production_micro_path: str = "/api/v4/systems/{system_id}/telemetry/production_micro"
    enphase_consumption_path: str = "/api/v4/systems/{system_id}/telemetry/consumption_meter"
    enphase_battery_path: str = "/api/v4/systems/{system_id}/telemetry/battery"
    enphase_energy_lifetime_path: str = "/api/v4/systems/{system_id}/energy_lifetime"
    enphase_consumption_lifetime_path: str = "/api/v4/systems/{system_id}/consumption_lifetime"
    enphase_granularity: str = "day"
    # Only for telemetry that carries a single interval, where there is no
    # gap to measure the resolution from.
    enphase_default_span_minutes: int = 15
    enphase_page_size: int = 100
    enphase_timeout_seconds: int = 60
    # An access token lasts about a day and a refresh token about a month, so a
    # feed left paused for a month has to be authorised again by hand. The skew
    # refreshes a little early rather than letting a call fail on the boundary.
    enphase_token_skew_seconds: int = 300
    enphase_tick_seconds: int = 60
    enphase_claim_minutes: int = 30
    # The pace is derived from what is left of the month's allowance, never
    # hard-coded, but it is held between these two: fast enough that the page is
    # worth calling Realtime, slow enough that a generous plan cannot be spent
    # in an afternoon.
    enphase_sync_min_seconds: int = 900
    enphase_sync_max_seconds: int = 21_600
    # The free "Watt" plan. An account on a larger plan raises this per feed,
    # and the pace opens up on its own.
    enphase_calls_budget: int = 1000
    # The per-minute ceiling is a second, independent limit: the plan allows ten
    # a minute, and one slot is left spare because the window is measured on our
    # clock and enforced on theirs. A backfill tick asks for far more than ten in
    # a row, so this is what actually keeps it out of a 429.
    enphase_calls_per_minute: int = 9
    enphase_rate_window_seconds: float = 60.0
    # A whole window: the sync sleeps off a full minute rather than giving up,
    # since nobody is waiting on it. The feed form passes the same budget and
    # only ever reaches it if a backfill is bursting at that exact moment.
    enphase_rate_wait_seconds: float = 60.0
    # The window is shared through the database, so the count is taken under a
    # Postgres advisory lock; the namespace keeps it clear of anyone else's.
    # Where a house's solar came from. The cloud feed owns the years and is
    # metered; the local one is Home Assistant reading the gateway on the house's
    # own network, which is free, live, and has no history at all. A house may
    # well have both, and then they describe the same panels - so the two are
    # never summed, only preferred one over the other, bucket by bucket.
    enphase_source_cloud: str = "cloud"
    enphase_source_local: str = "local"
    # The local feed stands in for a system id it does not have; one per house.
    enphase_local_system_id: str = "local"
    # A push carries the gateway's lifetime counters and the app differences
    # them, so a value re-sent unchanged is a zero and never a double count.
    # A gap longer than this is a restart rather than an interval, and its
    # delta is dropped rather than drawn as one enormous bar.
    enphase_push_max_gap_minutes: int = 60
    enphase_push_min_gap_seconds: float = 1.0
    # The tiles show what the panels are doing this second, which is the whole
    # point of a local feed; after this long with no push they stop claiming it.
    enphase_live_stale_minutes: int = 15
    # A push says what unit it is in and the app converts, rather than the
    # template doing arithmetic on the way out. Home Assistant lets a sensor's
    # display unit be overridden from the interface - an Envoy reports kW and
    # MWh by default - so a factor baked into the template is one settings
    # change away from being silently wrong by a thousand. Same rule as the
    # water CSV: convert from the unit the data itself names.
    enphase_power_watts: tuple[tuple[str, float], ...] = (
        ("W", 1.0),
        ("KW", 1_000.0),
        ("MW", 1_000_000.0),
    )
    enphase_energy_watt_hours: tuple[tuple[str, float], ...] = (
        ("WH", 1.0),
        ("KWH", 1_000.0),
        ("MWH", 1_000_000.0),
        ("GWH", 1_000_000_000.0),
    )
    rate_limit_lock_namespace: int = 8421
    rate_limit_retry_seconds: float = 0.05
    enphase_recent_days: int = 2
    # Production, consumption and the batteries: one call each per day of
    # telemetry, which is what a tick costs and so what paces the feed.
    enphase_streams: int = 3
    # Quarter-hourly history costs three calls per day walked, so it is worth a
    # fortnight - enough to fill the day and week views - and no more. The daily
    # pass below covers the years for two calls in total.
    enphase_fine_days: int = 14
    enphase_fine_days_per_tick: int = 2
    enphase_watt_hours_per_kwh: float = 1000.0
    enphase_battery_max_percent: float = 100.0
    enphase_message_max: int = 300
    # Telemetry we cannot read will not become readable on the next tick: the
    # walk counts it and moves past, rather than pinning itself on one bad day.
    enphase_unreadable_status: int = 422
    # Production and consumption are counters and so are summed; the battery is
    # a level and is averaged. The month and the year are served by the daily
    # rows, which is the only resolution the lifetime endpoints have - and the
    # only one whose whole history fits in the allowance.
    enphase_daily_bucket_minutes: int = 1440
    enphase_ranges: tuple[tuple[int, int], ...] = ((1, 15), (7, 60), (30, 1440), (365, 1440))
    email_test_suffixes: tuple[str, ...] = (
        "@example.com", ".example.com", "@example.org", ".example.org", "@example.net", ".example.net",
        ".test", ".invalid", ".example", ".localhost",
    )
    first_admin_email: str = "dbajet@gmail.com"
    first_admin_name: str = "Denis Bajet"


Constants = _Constants()
