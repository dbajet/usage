from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.enphase_ingest_command import EnphaseIngestCommand
from usage.structures.app_exception import AppException
from usage.structures.enphase_live import EnphaseLive
from usage.structures.enphase_point import EnphasePoint

NOW = datetime(2026, 9, 16, 7, 14, tzinfo=UTC)

SQL_PREVIOUS = """
            SELECT house_id, measured_at, production_power, consumption_power, battery_level,
                   production_lifetime, consumption_lifetime
            FROM enphase_live WHERE house_id = %s
            """
SQL_REMEMBER = """
            INSERT INTO enphase_live(house_id, measured_at, production_power, consumption_power,
                                     battery_level, production_lifetime, consumption_lifetime, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (house_id) DO UPDATE
            SET measured_at = EXCLUDED.measured_at,
                production_power = EXCLUDED.production_power,
                consumption_power = EXCLUDED.consumption_power,
                battery_level = EXCLUDED.battery_level,
                production_lifetime = EXCLUDED.production_lifetime,
                consumption_lifetime = EXCLUDED.consumption_lifetime,
                push_seconds = LEAST(%s, GREATEST(1,
                    EXTRACT(EPOCH FROM (now() - enphase_live.updated_at))::int)),
                updated_at = now()
            """
SQL_STORE = """
            INSERT INTO enphase_points(feed_id, measured_at, span_minutes, production, consumption, battery_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (feed_id, measured_at, span_minutes) DO UPDATE
            SET production = EXCLUDED.production,
                consumption = EXCLUDED.consumption,
                battery_level = EXCLUDED.battery_level
            """
SQL_LOCAL_FEED = "SELECT id FROM enphase_feeds WHERE house_id = %s AND source = %s"
SQL_MAKE_FEED = """
            INSERT INTO enphase_feeds(house_id, client_id_sealed, client_secret_sealed, api_key_sealed,
                                      system_id_sealed, system_id_hash, source)
            VALUES (%s, '', '', '', %s, %s, %s)
            RETURNING id
            """


def helper_instance() -> EnphaseIngestCommand:
    return EnphaseIngestCommand(MagicMock())


def helper_payload(**overrides: Any) -> dict[str, Any]:
    result = {
        "measured_at": "2026-09-16T07:14:00+00:00",
        "production_power": 0.6,
        "consumption_power": 0.36,
        "battery_level": 82.0,
        "production_lifetime": 1.00005,
        "consumption_lifetime": 2.00003,
        "production_power_unit": "kW",
        "consumption_power_unit": "kW",
        "production_lifetime_unit": "MWh",
        "consumption_lifetime_unit": "MWh",
    }
    result.update(overrides)
    return result


def helper_live(minute: int = 14, produced: float = 1_000_050.0, consumed: float = 2_000_030.0) -> EnphaseLive:
    return EnphaseLive(
        house_id=3,
        measured_at=datetime(2026, 9, 16, 7, minute, tzinfo=UTC),
        production_power=600.0,
        consumption_power=360.0,
        battery_level=82.0,
        production_lifetime=produced,
        consumption_lifetime=consumed,
    )


def test___init__() -> None:
    database = MagicMock()
    tested = EnphaseIngestCommand(database)
    assert tested._database is database
    assert database.mock_calls == []


@patch("usage.commands.enphase_ingest_command.IngestToken")
@patch.object(EnphaseIngestCommand, "_local_feed")
@patch.object(EnphaseIngestCommand, "_store")
@patch.object(EnphaseIngestCommand, "_interval")
@patch.object(EnphaseIngestCommand, "_remember")
@patch.object(EnphaseIngestCommand, "_previous")
@patch.object(EnphaseIngestCommand, "_push")
def test_ingest(
    push: MagicMock,
    previous: MagicMock,
    remember: MagicMock,
    interval: MagicMock,
    store: MagicMock,
    local_feed: MagicMock,
    token_class: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        push.reset_mock()
        previous.reset_mock()
        remember.reset_mock()
        interval.reset_mock()
        store.reset_mock()
        local_feed.reset_mock()
        token_class.reset_mock()
        database.reset_mock()

    payload = helper_payload()
    current = helper_live()
    before = helper_live(9, 1_000_000.0, 2_000_000.0)
    point = EnphasePoint(measured_at=before.measured_at, span_minutes=5, production=0.05)
    exp_token = [call(database), call().house_id("Bearer theToken")]

    # an ordinary push: the baseline moves on and the interval is drawn
    token_class.return_value.house_id.side_effect = [3]
    push.side_effect = [current]
    previous.side_effect = [before]
    interval.side_effect = [point]
    local_feed.side_effect = [12]
    result = tested.ingest("Bearer theToken", payload)
    expected = {"accepted": True, "stored": True}
    assert result == expected
    assert token_class.mock_calls == exp_token
    assert push.mock_calls == [call(3, payload)]
    assert previous.mock_calls == [call(3)]
    # the baseline is written before the interval is worked out, so an outage
    # loses one gap rather than every gap after it
    assert remember.mock_calls == [call(current)]
    assert interval.mock_calls == [call(before, current)]
    assert local_feed.mock_calls == [call(3)]
    assert store.mock_calls == [call(12, point)]
    exp_calls = [call.transaction(), call.transaction().__enter__(), call.transaction().__exit__(None, None, None)]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the very first push has nothing to measure from: remembered, nothing drawn
    token_class.return_value.house_id.side_effect = [3]
    push.side_effect = [current]
    previous.side_effect = [None]
    interval.side_effect = [None]
    result = tested.ingest("Bearer theToken", payload)
    expected = {"accepted": True, "stored": False}
    assert result == expected
    assert token_class.mock_calls == exp_token
    assert push.mock_calls == [call(3, payload)]
    assert previous.mock_calls == [call(3)]
    assert remember.mock_calls == [call(current)]
    assert interval.mock_calls == [call(None, current)]
    assert local_feed.mock_calls == []
    assert store.mock_calls == []
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.enphase_ingest_command.datetime", wraps=datetime)
def test__push(mock_datetime: MagicMock) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    result = tested._push(3, helper_payload())
    assert result == helper_live()
    # the instant the gateway names is read, not the clock we happen to have
    assert mock_datetime.mock_calls == [call.fromisoformat("2026-09-16T07:14:00+00:00")]
    reset_mocks()

    # strings off a template, and a charge outside the scale
    mock_datetime.now.side_effect = [NOW]
    result = tested._push(3, {"production_power": "600", "battery_level": "140", "measured_at": ""})
    expected = EnphaseLive(house_id=3, measured_at=NOW, production_power=600.0, battery_level=100.0)
    assert result == expected
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    # a gateway that is offline sends nothing worth storing
    for payload in [{}, {"production_power": None}, {"production_power": "unavailable"}]:
        mock_datetime.now.side_effect = [NOW]
        with pytest.raises(AppException) as exc_info:
            tested._push(3, payload)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "The push carried no reading at all."
        assert mock_datetime.mock_calls == [call.now(UTC)]
        reset_mocks()


def test__previous() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_calls = [call.fetch_one(SQL_PREVIOUS, (3,))]

    database.fetch_one.side_effect = [
        {
            "house_id": 3,
            "measured_at": datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
            "production_power": Decimal("600.000"),
            "consumption_power": Decimal("360.000"),
            "battery_level": Decimal("82.00"),
            "production_lifetime": Decimal("1000050.000"),
            "consumption_lifetime": Decimal("2000030.000"),
        },
    ]
    result = tested._previous(3)
    assert result == helper_live()
    assert database.mock_calls == exp_calls
    reset_mocks()

    database.fetch_one.side_effect = [None]
    result = tested._previous(3)
    assert result is None
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__remember() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.execute.side_effect = [0]
    result = tested._remember(helper_live())
    assert result is None
    exp_calls = [
        call.execute(SQL_REMEMBER, (3, "2026-09-16T07:14:00+00:00", 600.0, 360.0, 82.0, 1_000_050.0, 2_000_030.0, 1800)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__interval() -> None:
    tested = helper_instance()
    before = helper_live(9, 1_000_000.0, 2_000_000.0)

    # an ordinary five minutes: the energy between two readings, labelled by
    # when that interval began
    result = tested._interval(before, helper_live(14, 1_000_050.0, 2_000_030.0))
    expected = EnphasePoint(
        measured_at=datetime(2026, 9, 16, 7, 9, tzinfo=UTC),
        span_minutes=5,
        production=0.05,
        consumption=0.03,
        battery_level=82.0,
    )
    assert result == expected

    # nothing to measure from yet
    result = tested._interval(None, helper_live())
    assert result is None

    # the same push again, and two inside a second: nothing happened between them
    result = tested._interval(before, helper_live(9, 1_000_000.0, 2_000_000.0))
    assert result is None

    # an outage, not an interval: charting it would put one enormous bar where a
    # quiet night belongs. The baseline has already moved, so only this gap is lost.
    after_outage = helper_live(0, 9_000_000.0, 9_000_000.0)._replace(
        measured_at=datetime(2026, 9, 16, 8, 15, tzinfo=UTC),
    )
    result = tested._interval(helper_live(0, 1_000_000.0, 2_000_000.0), after_outage)
    assert result is None

    # a counter that went backwards is a replaced gateway, not negative generation
    result = tested._interval(before, helper_live(14, 12.0, 2_000_030.0))
    expected = EnphasePoint(
        measured_at=datetime(2026, 9, 16, 7, 9, tzinfo=UTC),
        span_minutes=5,
        production=None,
        consumption=0.03,
        battery_level=82.0,
    )
    assert result == expected

    # neither counter and no charge either: nothing to draw
    bare = EnphaseLive(house_id=3, measured_at=datetime(2026, 9, 16, 7, 14, tzinfo=UTC), production_power=600.0)
    result = tested._interval(EnphaseLive(house_id=3, measured_at=datetime(2026, 9, 16, 7, 9, tzinfo=UTC)), bare)
    assert result is None


def test__consumed() -> None:
    tested = helper_instance()
    tests: list[tuple[float | None, float | None, float | None]] = [
        (1_000_000.0, 1_000_050.0, 0.05),
        (1_000_000.0, 1_000_000.0, 0.0),
        # the counter went backwards: a replaced or reset gateway
        (1_000_000.0, 12.0, None),
        (None, 1_000_050.0, None),
        (1_000_000.0, None, None),
        (None, None, None),
    ]
    for before, after, expected in tests:
        result = tested._consumed(before, after)
        assert result == expected


def test__store() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    point = EnphasePoint(
        measured_at=datetime(2026, 9, 16, 7, 9, tzinfo=UTC),
        span_minutes=5,
        production=0.05,
        consumption=0.03,
        battery_level=82.0,
    )
    database.execute.side_effect = [0]
    result = tested._store(12, point)
    assert result is None
    exp_calls = [call.execute(SQL_STORE, (12, "2026-09-16T07:09:00+00:00", 5, 0.05, 0.03, 82.0))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__local_feed() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # the house already has one
    database.fetch_one.side_effect = [{"id": 12}]
    result = tested._local_feed(3)
    expected = 12
    assert result == expected
    assert database.mock_calls == [call.fetch_one(SQL_LOCAL_FEED, (3, "local"))]
    reset_mocks()

    # the first push that needs one makes it: no credentials, nothing to pull with
    database.fetch_one.side_effect = [None]
    database.encrypt.side_effect = ["sealedLocal"]
    database.blind_index.side_effect = ["hashedLocal"]
    database.execute.side_effect = [12]
    result = tested._local_feed(3)
    assert result == expected
    exp_calls = [
        call.fetch_one(SQL_LOCAL_FEED, (3, "local")),
        call.encrypt("local"),
        call.blind_index("local"),
        call.execute(SQL_MAKE_FEED, (3, "sealedLocal", "hashedLocal", "local")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.enphase_ingest_command.datetime", wraps=datetime)
def test__moment(mock_datetime: MagicMock) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    mock_datetime.now.side_effect = [NOW]
    result = tested._moment("")
    assert result == NOW
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    result = tested._moment("2026-09-16T07:14:00+00:00")
    assert result == NOW
    assert mock_datetime.mock_calls == [call.fromisoformat("2026-09-16T07:14:00+00:00")]
    reset_mocks()

    # Home Assistant can send a naive instant; it means UTC rather than nothing
    result = tested._moment("2026-09-16T07:14:00")
    assert result == NOW
    assert mock_datetime.mock_calls == [call.fromisoformat("2026-09-16T07:14:00")]
    reset_mocks()

    with pytest.raises(AppException) as exc_info:
        tested._moment("the sixteenth")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The push carried an unreadable instant."
    assert mock_datetime.mock_calls == [call.fromisoformat("the sixteenth")]
    reset_mocks()


def test__percent() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        (82, 82.0),
        ("82.456", 82.46),
        # a charge outside the scale is clamped rather than drawn off the graph
        (140, 100.0),
        (-3, 0.0),
        (None, None),
        ("unavailable", None),
    ]
    for raw, expected in tests:
        result = tested._percent(raw)
        assert result == expected


def test__number() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        (600, 600.0),
        ("600", 600.0),
        ("60.5", 60.5),
        # Home Assistant sends these strings for an entity it cannot read
        ("unavailable", None),
        ("unknown", None),
        (True, None),
        (None, None),
        ({}, None),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected


def test__converted() -> None:
    tested = helper_instance()
    watts = (("W", 1.0), ("KW", 1_000.0), ("MW", 1_000_000.0))
    hours = (("WH", 1.0), ("KWH", 1_000.0), ("MWH", 1_000_000.0), ("GWH", 1_000_000_000.0))
    tests: list[tuple[dict[str, Any], tuple[tuple[str, float], ...], float | None]] = [
        # what an Envoy actually reports, which is not what the field is named for
        ({"production_power": 0.72, "production_power_unit": "kW"}, watts, 720.0),
        ({"production_lifetime": 12.5, "production_lifetime_unit": "MWh"}, hours, 12_500_000.0),
        ({"production_power": 720, "production_power_unit": "W"}, watts, 720.0),
        ({"production_lifetime": 1.5, "production_lifetime_unit": "GWh"}, hours, 1_500_000_000.0),
        # the unit is named in whatever case the sender likes
        ({"production_power": 0.72, "production_power_unit": " kw "}, watts, 720.0),
        # no unit at all means the base one, which is what the field implies
        ({"production_power": 720}, watts, 720.0),
        ({"production_power": 720, "production_power_unit": ""}, watts, 720.0),
        # a unit nobody here knows is no reading, never a number off by a thousand
        ({"production_power": 720, "production_power_unit": "horsepower"}, watts, None),
        ({"production_power": 720, "production_power_unit": "MWh"}, watts, None),
        # nothing to convert
        ({}, watts, None),
        ({"production_power": "unavailable", "production_power_unit": "kW"}, watts, None),
    ]
    for data, factors, expected in tests:
        field = "production_lifetime" if "production_lifetime" in data else "production_power"
        result = tested._converted(data, field, factors)
        assert result == expected
