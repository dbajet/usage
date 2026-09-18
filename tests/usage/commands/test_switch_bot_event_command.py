from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.sensor_command import SensorCommand
from usage.commands.switch_bot_event_command import SwitchBotEventCommand
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.settings import Settings
from usage.structures.switch_bot_event import SwitchBotEvent

NOW = datetime(2026, 9, 18, 12, 41, tzinfo=UTC)
SAMPLED = datetime(2026, 9, 18, 12, 37, tzinfo=UTC)
SQL_FEED = "SELECT id, house_id FROM switchbot_feeds WHERE event_token_hash = %s AND active"


def helper_settings() -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=False,
        cookie_secure=True,
        base_url="https://usage.example.com",
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-opus-5",
    )


def helper_instance() -> SwitchBotEventCommand:
    return SwitchBotEventCommand(MagicMock(), helper_settings(), MagicMock())


def helper_payload() -> dict[str, Any]:
    return {
        "eventType": "changeReport",
        "eventVersion": "1",
        "context": {
            "deviceType": "WoIOSensor",
            "deviceMac": "C271111EC0AB",
            "temperature": 26.1,
            "humidity": 52,
            "battery": 100,
            "timeOfSample": int(SAMPLED.timestamp() * 1000),
        },
    }


def helper_event() -> SwitchBotEvent:
    return SwitchBotEvent(
        device_id="C271111EC0AB",
        temperature=26.1,
        measured_at=SAMPLED,
        humidity=52.0,
        battery=100,
    )


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    email_sender = MagicMock()
    tested = SwitchBotEventCommand(database, settings, email_sender)
    assert tested._database is database
    assert isinstance(tested._sensors, SensorCommand)
    assert tested._sensors._database is database


@patch.object(SwitchBotEventCommand, "_samples")
@patch.object(SwitchBotEventCommand, "_event")
@patch.object(SwitchBotEventCommand, "_feed")
def test_ingest(feed_of: MagicMock, event_of: MagicMock, samples_of: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    store = MagicMock()
    tested._sensors = store

    def reset_mocks() -> None:
        feed_of.reset_mock()
        event_of.reset_mock()
        samples_of.reset_mock()
        store.reset_mock()
        database.reset_mock()

    feed = {"id": 11, "house_id": 3}
    event = helper_event()
    sample = SensorSample(
        entity_id="switchbot.c271111ec0ab",
        name="switchbot.c271111ec0ab",
        unit="°C",
        value=26.1,
        measured_at=SAMPLED,
        reported_at=SAMPLED,
    )
    payload = helper_payload()
    exp_last_event = [call.execute("UPDATE switchbot_feeds SET last_event_at = now() WHERE id = %s", (11,))]

    # a reading for a thermometer this house collects
    feed_of.side_effect = [feed]
    event_of.side_effect = [event]
    samples_of.side_effect = [[sample]]
    store.store.side_effect = [{"accepted": 1, "created": 0}]
    database.execute.side_effect = [1]
    result = tested.ingest("theEventToken", payload)
    expected = {"accepted": 1}
    assert result == expected
    assert feed_of.mock_calls == [call("theEventToken")]
    assert event_of.mock_calls == [call(payload["context"])]
    assert samples_of.mock_calls == [call(event)]
    # never creates: the account reports every device it has, this house's or not
    assert store.mock_calls == [call.store(3, [sample], create=False)]
    assert database.mock_calls == exp_last_event
    reset_mocks()

    # a device this house does not collect - another house's, most likely - is
    # dropped by the store, and proves nothing about this feed being told anything
    feed_of.side_effect = [feed]
    event_of.side_effect = [event]
    samples_of.side_effect = [[sample]]
    store.store.side_effect = [{"accepted": 0, "created": 0}]
    result = tested.ingest("theEventToken", payload)
    expected = {"accepted": 0}
    assert result == expected
    assert store.mock_calls == [call.store(3, [sample], create=False)]
    assert database.mock_calls == []
    assert feed_of.mock_calls == [call("theEventToken")]
    assert event_of.mock_calls == [call(payload["context"])]
    assert samples_of.mock_calls == [call(event)]
    reset_mocks()

    # something other than a reading: a device coming online, a command landing
    feed_of.side_effect = [feed]
    result = tested.ingest("theEventToken", {"eventType": "somethingElse", "context": {}})
    expected = {"accepted": 0}
    assert result == expected
    assert feed_of.mock_calls == [call("theEventToken")]
    assert event_of.mock_calls == []
    assert samples_of.mock_calls == []
    assert store.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # a changeReport carrying no temperature at all
    feed_of.side_effect = [feed]
    event_of.side_effect = [None]
    result = tested.ingest("theEventToken", payload)
    expected = {"accepted": 0}
    assert result == expected
    assert event_of.mock_calls == [call(payload["context"])]
    assert samples_of.mock_calls == []
    assert store.mock_calls == []
    assert database.mock_calls == []
    assert feed_of.mock_calls == [call("theEventToken")]
    reset_mocks()


def test__feed() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    feed = {"id": 11, "house_id": 3}
    database.blind_index.side_effect = ["theEventHash"]
    database.fetch_one.side_effect = [feed]
    result = tested._feed("theEventToken")
    assert result == feed
    exp_calls = [call.blind_index("theEventToken"), call.fetch_one(SQL_FEED, ("theEventHash",))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a URL nobody minted, or one whose feed is paused: the same nothing either way
    database.blind_index.side_effect = ["theEventHash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._feed("theEventToken")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "Not found."
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__samples() -> None:
    tested = helper_instance()

    # both instants are the one the device stamped: the exact answer to the two
    # questions a polled status leaves open
    result = tested._samples(helper_event())
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="switchbot.c271111ec0ab",
            unit="°C",
            value=26.1,
            measured_at=SAMPLED,
            battery=100,
            reported_at=SAMPLED,
        ),
        SensorSample(
            entity_id="switchbot.c271111ec0ab.humidity",
            name="switchbot.c271111ec0ab",
            unit="%",
            value=52.0,
            measured_at=SAMPLED,
            battery=None,
            reported_at=SAMPLED,
            hidden=True,
        ),
    ]
    assert result == expected

    # a thermometer reporting no humidity writes the one sensor
    event = SwitchBotEvent(device_id="C271111EC0AB", temperature=19.446, measured_at=SAMPLED)
    result = tested._samples(event)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="switchbot.c271111ec0ab",
            unit="°C",
            value=19.45,
            measured_at=SAMPLED,
            battery=None,
            reported_at=SAMPLED,
        ),
    ]
    assert result == expected


@patch.object(SwitchBotEventCommand, "_instant")
def test__event(instant: MagicMock) -> None:
    tested = helper_instance()

    def reset_mocks() -> None:
        instant.reset_mock()

    context = helper_payload()["context"]
    instant.side_effect = [SAMPLED]
    result = tested._event(context)
    expected = helper_event()
    assert result == expected
    assert instant.mock_calls == [call(context["timeOfSample"])]
    reset_mocks()

    # Fahrenheit, which the status endpoint never answers in but an event may
    instant.side_effect = [SAMPLED]
    result = tested._event({"deviceMac": "C271111EC0AB", "temperature": 79.0, "scale": "FAHRENHEIT"})
    expected = SwitchBotEvent(device_id="C271111EC0AB", temperature=26.11111111111111, measured_at=SAMPLED)
    assert result == expected
    assert instant.mock_calls == [call(None)]
    reset_mocks()

    # not a reading: no device, or nothing that is a temperature
    tests: list[dict[str, Any]] = [
        {"temperature": 26.1},
        {"deviceMac": "   ", "temperature": 26.1},
        {"deviceMac": "C271111EC0AB", "power": "on"},
        {"deviceMac": "C271111EC0AB", "temperature": "warm"},
    ]
    for context in tests:
        result = tested._event(context)
        assert result is None
        assert instant.mock_calls == []
        reset_mocks()


def test__celsius() -> None:
    tested = helper_instance()
    tests: list[tuple[float, str, float]] = [
        (26.1, "", 26.1),
        (26.1, "CELSIUS", 26.1),
        (79.0, "FAHRENHEIT", 26.11111111111111),
        (79.0, " fahrenheit ", 26.11111111111111),
        (32.0, "FAHRENHEIT", 0.0),
    ]
    for temperature, scale, expected in tests:
        result = tested._celsius(temperature, scale)
        assert result == expected


@patch("usage.commands.switch_bot_event_command.logging")
@patch("usage.commands.switch_bot_event_command.datetime", wraps=datetime)
def test__instant(mock_datetime: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()

    tested = helper_instance()

    # milliseconds, which is what SwitchBot sends
    mock_datetime.now.side_effect = [NOW]
    result = tested._instant(int(SAMPLED.timestamp() * 1000))
    assert result == SAMPLED
    assert mock_datetime.mock_calls == [call.now(UTC), call.fromtimestamp(1789735020.0, UTC)]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # seconds, which the documented example reads as just as easily: taken as
    # such rather than filed in 1970 for ever
    mock_datetime.now.side_effect = [NOW]
    result = tested._instant(int(SAMPLED.timestamp()))
    assert result == SAMPLED
    assert mock_datetime.mock_calls == [call.now(UTC), call.fromtimestamp(1789735020.0, UTC)]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # nothing to read, or nothing that is a number: the arrival stands in
    for raw in (None, "later", [], True):
        mock_datetime.now.side_effect = [NOW]
        result = tested._instant(raw)
        assert result == NOW
        assert mock_datetime.mock_calls == [call.now(UTC)]
        assert mock_logging.mock_calls == []
        reset_mocks()

    # a clock ahead of ours, which must not put a reading in the future
    mock_datetime.now.side_effect = [NOW]
    result = tested._instant(int((NOW + timedelta(hours=2)).timestamp() * 1000))
    assert result == NOW
    assert mock_datetime.mock_calls == [call.now(UTC), call.fromtimestamp(1789742460.0, UTC)]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # and one so far behind that it is not an instant worth trusting
    mock_datetime.now.side_effect = [NOW]
    mock_logging.getLogger.side_effect = [logger]
    result = tested._instant(int((NOW - timedelta(days=30)).timestamp() * 1000))
    assert result == NOW
    assert mock_datetime.mock_calls == [call.now(UTC), call.fromtimestamp(1787143260.0, UTC)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    exp_calls = [call.info("[SWITCHBOT] event stamped %s, taken as now", "2026-08-19T12:41:00+00:00")]
    assert logger.mock_calls == exp_calls
    reset_mocks()

    # a value no calendar can hold
    mock_datetime.now.side_effect = [NOW]
    result = tested._instant(10 ** 30)
    assert result == NOW
    assert mock_datetime.mock_calls == [call.now(UTC), call.fromtimestamp(1e+27, UTC)]
    assert mock_logging.mock_calls == []
    reset_mocks()


def test__number() -> None:
    tested = helper_instance()
    tests: list[tuple[Any, float | None]] = [
        (26.1, 26.1),
        ("26.1", 26.1),
        (0, 0.0),
        (None, None),
        (True, None),
        ("warm", None),
        ([], None),
    ]
    for raw, expected in tests:
        result = tested._number(raw)
        assert result == expected
