from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.sensor_command import SensorCommand
from usage.commands.switch_bot_sync_command import SwitchBotSyncCommand
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.sensor_state import SensorState
from usage.structures.settings import Settings
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_feed import SwitchBotFeed
from usage.structures.switch_bot_reading import SwitchBotReading

NOW = datetime(2026, 9, 17, 14, 2, tzinfo=UTC)
EARLIER = datetime(2026, 9, 17, 11, 30, tzinfo=UTC)
WEBHOOK_AT = datetime(2026, 9, 18, 12, 30, tzinfo=UTC)

SQL_DUE = """
            SELECT id, house_id, token_sealed AS token, secret_sealed AS secret,
                   hub_ids_sealed AS hub_ids, active, event_token_sealed AS event_token, webhook_at
            FROM switchbot_feeds
            WHERE active AND (claimed_until IS NULL OR claimed_until < now())
              AND (last_sync_at IS NULL OR last_sync_at < now() - %s)
            ORDER BY id
            """
SQL_PREVIOUS = """
            SELECT sensors.entity_hash, sensors.battery, last.measured_at, last.value
            FROM sensors
            LEFT JOIN LATERAL (
                SELECT samples.measured_at, samples.value FROM samples
                WHERE samples.sensor_id = sensors.id
                ORDER BY samples.measured_at DESC LIMIT 1
            ) AS last ON true
            WHERE sensors.house_id = %s
            """
SQL_CLAIM = """
            UPDATE switchbot_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
            """
SQL_RECORD = """
            UPDATE switchbot_feeds
            SET claimed_until = NULL, last_sync_at = now(), last_error = %s,
                last_point_at = CASE WHEN %s THEN now() ELSE last_point_at END
            WHERE id = %s
            """


def helper_settings(base_url: str = "https://usage.example.com") -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=False,
        cookie_secure=True,
        base_url=base_url,
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-opus-5",
    )


def helper_instance(base_url: str = "https://usage.example.com") -> SwitchBotSyncCommand:
    return SwitchBotSyncCommand(MagicMock(), helper_settings(base_url), MagicMock(), MagicMock())


def helper_feed(
    hub_ids: tuple[str, ...] = ("FA7310762361",),
    event_token: str = "theEventToken",
    webhook_at: datetime | None = None,
) -> SwitchBotFeed:
    return SwitchBotFeed(
        feed_id=11,
        house_id=3,
        token="theToken",
        secret="theSecret",
        hub_ids=hub_ids,
        active=True,
        event_token=event_token,
        webhook_at=webhook_at,
    )


def helper_device(device_id: str = "C271111EC0AB", hub_id: str = "FA7310762361") -> SwitchBotDevice:
    return SwitchBotDevice(device_id=device_id, name="Grenier", device_type="Meter", hub_id=hub_id)


def helper_row() -> dict[str, Any]:
    return {
        "id": 11,
        "house_id": 3,
        "token": "theToken",
        "secret": "theSecret",
        "hub_ids": "FA7310762361",
        "active": True,
        "event_token": "theEventToken",
        "webhook_at": None,
    }


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    email_sender = MagicMock()
    limiter = MagicMock()
    tested = SwitchBotSyncCommand(database, settings, email_sender, limiter)
    assert tested._database is database
    assert tested._settings is settings
    assert tested._limiter is limiter
    assert isinstance(tested._sensors, SensorCommand)
    assert tested._sensors._database is database


@patch("usage.commands.switch_bot_sync_command.threading")
def test_start(mock_threading: MagicMock) -> None:
    thread = MagicMock()

    def reset_mocks() -> None:
        mock_threading.reset_mock()
        thread.reset_mock()

    tested = helper_instance()
    mock_threading.Thread.side_effect = [thread]
    result = tested.start()
    assert result is None
    exp_calls = [call.Thread(target=tested._loop, name="switchbot-sync", daemon=True)]
    assert mock_threading.mock_calls == exp_calls
    assert thread.mock_calls == [call.start()]
    reset_mocks()


@patch("usage.commands.switch_bot_sync_command.logging")
@patch("usage.commands.switch_bot_sync_command.time")
@patch.object(SwitchBotSyncCommand, "tick")
def test__loop(tick: MagicMock, mock_time: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()

    def reset_mocks() -> None:
        tick.reset_mock()
        mock_time.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()

    tested = helper_instance()
    # two rounds - the first fails and is logged, the second works - then the
    # sleep breaks the endless loop for the test
    error = RuntimeError("boom")
    stop = KeyboardInterrupt()
    tick.side_effect = [error, None]
    mock_time.sleep.side_effect = [None, stop]
    mock_logging.getLogger.side_effect = [logger]
    with pytest.raises(KeyboardInterrupt):
        tested._loop()
    assert tick.mock_calls == [call(), call()]
    assert mock_time.mock_calls == [call.sleep(60), call.sleep(60)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[SWITCHBOT] tick failed: %s", error)]
    reset_mocks()


@patch("usage.commands.switch_bot_sync_command.logging")
@patch.object(SwitchBotSyncCommand, "_record")
@patch.object(SwitchBotSyncCommand, "_sync")
@patch.object(SwitchBotSyncCommand, "_claim")
@patch.object(SwitchBotSyncCommand, "_feed")
def test_tick(
    feed_of: MagicMock,
    claim: MagicMock,
    sync: MagicMock,
    record: MagicMock,
    mock_logging: MagicMock,
) -> None:
    logger = MagicMock()
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        feed_of.reset_mock()
        claim.reset_mock()
        sync.reset_mock()
        record.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()
        database.reset_mock()

    row = helper_row()
    feed = helper_feed()
    exp_database = [
        call.fetch_all(SQL_DUE, (timedelta(seconds=600),)),
        call.decrypt_rows([row], ("token", "secret", "hub_ids", "event_token")),
    ]

    # pulled
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    feed_of.side_effect = [feed]
    claim.side_effect = [True]
    sync.side_effect = [None]
    result = tested.tick()
    assert result is None
    assert feed_of.mock_calls == [call(row)]
    assert claim.mock_calls == [call(11)]
    assert sync.mock_calls == [call(feed)]
    assert record.mock_calls == []
    assert mock_logging.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    # the other colour got there first
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    feed_of.side_effect = [feed]
    claim.side_effect = [False]
    tested.tick()
    assert claim.mock_calls == [call(11)]
    assert sync.mock_calls == []
    assert record.mock_calls == []
    assert mock_logging.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    # SwitchBot said no: the reason is kept and the claim released
    error = AppException(401, "SwitchBot refused the token and secret.")
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    feed_of.side_effect = [feed]
    claim.side_effect = [True]
    sync.side_effect = [error]
    record.side_effect = [None]
    tested.tick()
    assert sync.mock_calls == [call(feed)]
    assert record.mock_calls == [call(11, "SwitchBot refused the token and secret.")]
    assert mock_logging.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    # anything else must not strand the claim either
    unknown = RuntimeError("boom")
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    feed_of.side_effect = [feed]
    claim.side_effect = [True]
    sync.side_effect = [unknown]
    record.side_effect = [None]
    mock_logging.getLogger.side_effect = [logger]
    tested.tick()
    assert sync.mock_calls == [call(feed)]
    assert record.mock_calls == [call(11, "The import failed unexpectedly.")]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[SWITCHBOT] feed %s failed: %s", 11, unknown)]
    assert database.mock_calls == exp_database
    reset_mocks()


@patch("usage.commands.switch_bot_sync_command.datetime", wraps=datetime)
@patch("usage.commands.switch_bot_sync_command.SwitchBotHubs")
@patch("usage.commands.switch_bot_sync_command.SwitchBotClient")
@patch.object(SwitchBotSyncCommand, "_record")
@patch.object(SwitchBotSyncCommand, "_register")
@patch.object(SwitchBotSyncCommand, "_samples")
@patch.object(SwitchBotSyncCommand, "_previous")
@patch.object(SwitchBotSyncCommand, "_read")
def test__sync(
    read: MagicMock,
    previous: MagicMock,
    samples_of: MagicMock,
    register: MagicMock,
    record: MagicMock,
    client_class: MagicMock,
    hubs_class: MagicMock,
    mock_datetime: MagicMock,
) -> None:
    client = MagicMock()
    hubs = MagicMock()
    tested = helper_instance()
    store = MagicMock()
    tested._sensors = store

    def reset_mocks() -> None:
        read.reset_mock()
        previous.reset_mock()
        samples_of.reset_mock()
        register.reset_mock()
        record.reset_mock()
        client_class.reset_mock()
        hubs_class.reset_mock()
        mock_datetime.reset_mock()
        client.reset_mock()
        hubs.reset_mock()
        store.reset_mock()

    feed = helper_feed()
    mine = helper_device()
    # the same account, behind the other house's hub: never asked, never charged for
    theirs = helper_device("E493333GE2CD", "BB2210762399")
    # a switch sharing the hub with the thermometers: asked, and it answers nothing
    mute = helper_device("F504444HF3DE")
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4, humidity=61.0, battery=87)
    sample = SensorSample(
        entity_id="switchbot.c271111ec0ab",
        name="Grenier",
        unit="°C",
        value=19.4,
        measured_at=NOW,
    )
    states = {"theHash": SensorState(entity_hash="theHash")}

    mock_datetime.now.side_effect = [NOW]
    client_class.side_effect = [client]
    client.devices.side_effect = [[mine, theirs, mute]]
    hubs_class.side_effect = [hubs]
    hubs.following.side_effect = [[mine, mute]]
    previous.side_effect = [states]
    read.side_effect = [reading, None]
    samples_of.side_effect = [[sample]]
    store.store.side_effect = [{"accepted": 1, "created": 1}]
    register.side_effect = [None]
    record.side_effect = [None]
    result = tested._sync(feed)
    assert result is None
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.devices()]
    assert hubs_class.mock_calls == [call([mine, theirs, mute])]
    assert hubs.mock_calls == [call.following(("FA7310762361",))]
    assert previous.mock_calls == [call(3)]
    assert read.mock_calls == [call(client, mine), call(client, mute)]
    assert samples_of.mock_calls == [call(mine, reading, states, NOW)]
    assert store.mock_calls == [call.store(3, [sample])]
    assert register.mock_calls == [call(client, feed)]
    assert record.mock_calls == [call(11, "", True)]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    # a tick where nothing could be read: the feed is well, it simply has nothing
    mock_datetime.now.side_effect = [NOW]
    client_class.side_effect = [client]
    client.devices.side_effect = [[mine]]
    hubs_class.side_effect = [hubs]
    hubs.following.side_effect = [[mine]]
    previous.side_effect = [states]
    read.side_effect = [None]
    register.side_effect = [None]
    record.side_effect = [None]
    tested._sync(feed)
    assert store.mock_calls == []
    assert register.mock_calls == [call(client, feed)]
    assert record.mock_calls == [call(11, "", False)]
    assert samples_of.mock_calls == []
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.devices()]
    assert hubs_class.mock_calls == [call([mine])]
    assert hubs.mock_calls == [call.following(("FA7310762361",))]
    assert previous.mock_calls == [call(3)]
    assert read.mock_calls == [call(client, mine)]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    reset_mocks()

    # the hubs this house follows have nothing behind them any more
    client_class.side_effect = [client]
    client.devices.side_effect = [[theirs]]
    hubs_class.side_effect = [hubs]
    hubs.following.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested._sync(feed)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "This account has nothing behind the hubs this house follows."
    assert previous.mock_calls == []
    assert read.mock_calls == []
    assert store.mock_calls == []
    assert register.mock_calls == []
    assert record.mock_calls == []
    assert client_class.mock_calls == [call("theToken", "theSecret", tested._limiter)]
    assert client.mock_calls == [call.devices()]
    assert hubs_class.mock_calls == [call([theirs])]
    assert hubs.mock_calls == [call.following(("FA7310762361",))]
    assert mock_datetime.mock_calls == []
    reset_mocks()


@patch.object(SwitchBotSyncCommand, "_mint")
@patch.object(SwitchBotSyncCommand, "_webhook_error")
def test__register(webhook_error: MagicMock, mint: MagicMock) -> None:
    client = MagicMock()
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        webhook_error.reset_mock()
        mint.reset_mock()
        client.reset_mock()
        database.reset_mock()

    url = "https://usage.example.com/api/switchbot/events/theEventToken"
    exp_stored = [
        call.execute(
            "UPDATE switchbot_feeds SET webhook_at = now(), webhook_error = '' WHERE id = %s",
            (11,),
        ),
    ]

    # never registered: asked for, and written down so it is not asked again
    client.setup_webhook.side_effect = [None]
    database.execute.side_effect = [1]
    result = tested._register(client, helper_feed())
    assert result is None
    assert client.mock_calls == [call.setup_webhook(url)]
    assert database.mock_calls == exp_stored
    assert webhook_error.mock_calls == []
    assert mint.mock_calls == []
    reset_mocks()

    # a feed set up before any of this existed has no secret yet: one is minted
    # rather than leaving it unable to register for ever
    mint.side_effect = ["theEventToken"]
    client.setup_webhook.side_effect = [None]
    database.execute.side_effect = [1]
    result = tested._register(client, helper_feed(event_token=""))
    assert result is None
    assert mint.mock_calls == [call(11)]
    assert client.mock_calls == [call.setup_webhook(url)]
    assert database.mock_calls == exp_stored
    assert webhook_error.mock_calls == []
    reset_mocks()

    # already registered: not asked again, for ever
    result = tested._register(client, helper_feed(webhook_at=WEBHOOK_AT))
    assert result is None
    assert client.mock_calls == []
    assert database.mock_calls == []
    assert webhook_error.mock_calls == []
    assert mint.mock_calls == []
    reset_mocks()

    # SwitchBot refused it: said so, and tried again on the next tick
    client.setup_webhook.side_effect = [AppException(422, "SwitchBot refused the request: wrong parameter")]
    webhook_error.side_effect = [None]
    result = tested._register(client, helper_feed())
    assert result is None
    assert client.mock_calls == [call.setup_webhook(url)]
    assert database.mock_calls == []
    assert webhook_error.mock_calls == [call(11, "SwitchBot refused the request: wrong parameter")]
    assert mint.mock_calls == []
    reset_mocks()

    # no public address to post to, which is not worth a call to find out
    local = helper_instance("http://localhost:8063")
    local_database = local._database
    webhook_error.side_effect = [None]
    result = local._register(client, helper_feed())
    assert result is None
    assert client.mock_calls == []
    assert local_database.mock_calls == []
    exp_calls = [call(11, "The app has no public https address, so SwitchBot has nowhere to post events.")]
    assert webhook_error.mock_calls == exp_calls
    assert mint.mock_calls == []
    reset_mocks()


@patch("usage.commands.switch_bot_sync_command.secrets.token_urlsafe")
def test__mint(token_urlsafe: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        token_urlsafe.reset_mock()
        database.reset_mock()

    token_urlsafe.side_effect = ["theEventToken"]
    database.encrypt.side_effect = ["sealedEventToken"]
    database.blind_index.side_effect = ["theEventHash"]
    database.execute.side_effect = [1]
    result = tested._mint(11)
    expected = "theEventToken"
    assert result == expected
    assert token_urlsafe.mock_calls == [call(32)]
    exp_calls = [
        call.encrypt("theEventToken"),
        call.blind_index("theEventToken"),
        call.execute(
            "UPDATE switchbot_feeds SET event_token_sealed = %s, event_token_hash = %s WHERE id = %s",
            ("sealedEventToken", "theEventHash", 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__event_url() -> None:
    tested = helper_instance()
    result = tested._event_url("theEventToken")
    expected = "https://usage.example.com/api/switchbot/events/theEventToken"
    assert result == expected

    # http is not an address SwitchBot will post to, and neither is nothing
    for base_url in ("http://localhost:8063", ""):
        tested = helper_instance(base_url)
        result = tested._event_url("theEventToken")
        assert result == ""


def test__webhook_error() -> None:
    tested = helper_instance()
    database = tested._database

    database.execute.side_effect = [1]
    result = tested._webhook_error(11, "SwitchBot could not be reached.")
    assert result is None
    exp_calls = [
        call.execute(
            "UPDATE switchbot_feeds SET webhook_error = %s WHERE id = %s",
            ("SwitchBot could not be reached.", 11),
        ),
    ]
    assert database.mock_calls == exp_calls


@patch("usage.commands.switch_bot_sync_command.logging")
def test__read(mock_logging: MagicMock) -> None:
    client = MagicMock()
    logger = MagicMock()

    def reset_mocks() -> None:
        mock_logging.reset_mock()
        logger.reset_mock()
        client.reset_mock()

    tested = helper_instance()
    device = helper_device()
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4)

    client.status.side_effect = [reading]
    result = tested._read(client, device)
    assert result == reading
    assert client.mock_calls == [call.status("C271111EC0AB")]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # one device the hub could not reach is not a broken feed
    client.status.side_effect = [AppException(422, "SwitchBot refused the request: device offline")]
    mock_logging.getLogger.side_effect = [logger]
    result = tested._read(client, device)
    assert result is None
    assert client.mock_calls == [call.status("C271111EC0AB")]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    exp_calls = [
        call.info("[SWITCHBOT] device %s unreadable: %s", "C271111EC0AB", "SwitchBot refused the request: device offline"),
    ]
    assert logger.mock_calls == exp_calls
    reset_mocks()

    # a refused token is not one device's problem: it ends the tick
    client.status.side_effect = [AppException(401, "SwitchBot refused the token and secret.")]
    with pytest.raises(AppException) as exc_info:
        tested._read(client, device)
    assert exc_info.value.status_code == 401
    assert client.mock_calls == [call.status("C271111EC0AB")]
    assert mock_logging.mock_calls == []
    reset_mocks()


def test__samples() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    device = helper_device()
    exp_database = [
        call.blind_index("switchbot.c271111ec0ab"),
        call.blind_index("switchbot.c271111ec0ab.humidity"),
    ]

    # nothing stored yet: both instants are this poll, and the humidity sensor
    # is created hidden - it is evidence, not a curve for the temperature graph
    database.blind_index.side_effect = ["temperatureHash", "humidityHash"]
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.446, humidity=61.0, battery=87)
    result = tested._samples(device, reading, {}, NOW)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="Grenier",
            unit="°C",
            value=19.45,
            measured_at=NOW,
            battery=87,
            reported_at=NOW,
        ),
        SensorSample(
            entity_id="switchbot.c271111ec0ab.humidity",
            name="Grenier humidity",
            unit="%",
            value=61.0,
            measured_at=NOW,
            battery=None,
            reported_at=NOW,
            hidden=True,
        ),
    ]
    assert result == expected
    assert database.mock_calls == exp_database
    reset_mocks()

    # nothing has moved at all: both keep the instant they already had, so an
    # unchanged room is one sample, and `reported_at` is left alone rather than
    # standing in this poll for a freshness nothing has vouched for
    previous = {
        "temperatureHash": SensorState(entity_hash="temperatureHash", value=19.4, measured_at=EARLIER, battery=87),
        "humidityHash": SensorState(entity_hash="humidityHash", value=61.0, measured_at=EARLIER),
    }
    database.blind_index.side_effect = ["temperatureHash", "humidityHash"]
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4, humidity=61.0, battery=87)
    result = tested._samples(device, reading, previous, NOW)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="Grenier",
            unit="°C",
            value=19.4,
            measured_at=EARLIER,
            battery=87,
            reported_at=None,
        ),
        SensorSample(
            entity_id="switchbot.c271111ec0ab.humidity",
            name="Grenier humidity",
            unit="%",
            value=61.0,
            measured_at=EARLIER,
            battery=None,
            reported_at=None,
            hidden=True,
        ),
    ]
    assert result == expected
    assert database.mock_calls == exp_database
    reset_mocks()

    # the room holds its temperature and the humidity moves: the thermometer is
    # heard from, which is the whole reason the humidity is collected at all
    database.blind_index.side_effect = ["temperatureHash", "humidityHash"]
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4, humidity=62.0, battery=87)
    result = tested._samples(device, reading, previous, NOW)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="Grenier",
            unit="°C",
            value=19.4,
            measured_at=EARLIER,
            battery=87,
            reported_at=NOW,
        ),
        SensorSample(
            entity_id="switchbot.c271111ec0ab.humidity",
            name="Grenier humidity",
            unit="%",
            value=62.0,
            measured_at=NOW,
            battery=None,
            reported_at=NOW,
            hidden=True,
        ),
    ]
    assert result == expected
    assert database.mock_calls == exp_database
    reset_mocks()

    # a thermometer reporting no humidity at all: one sample, and the charge is
    # what settles whether it has been heard from
    database.blind_index.side_effect = ["temperatureHash", "humidityHash"]
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4, humidity=None, battery=86)
    result = tested._samples(device, reading, previous, NOW)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="Grenier",
            unit="°C",
            value=19.4,
            measured_at=EARLIER,
            battery=86,
            reported_at=NOW,
        ),
    ]
    assert result == expected
    assert database.mock_calls == exp_database
    reset_mocks()

    # a device the account never named falls back to its id
    database.blind_index.side_effect = ["temperatureHash", "humidityHash"]
    reading = SwitchBotReading(device_id="C271111EC0AB", temperature=19.4)
    result = tested._samples(SwitchBotDevice(device_id="C271111EC0AB"), reading, previous, NOW)
    expected = [
        SensorSample(
            entity_id="switchbot.c271111ec0ab",
            name="C271111EC0AB",
            unit="°C",
            value=19.4,
            measured_at=EARLIER,
            battery=None,
            reported_at=None,
        ),
    ]
    assert result == expected
    assert database.mock_calls == exp_database
    reset_mocks()


def test__instant() -> None:
    tested = helper_instance()
    stored = SensorState(entity_hash="theHash", value=19.4, measured_at=EARLIER)
    tests: list[tuple[SensorState | None, float, datetime]] = [
        # unchanged: the instant it has had since it changed
        (stored, 19.4, EARLIER),
        # moved: all that is known is that it happened since the last poll
        (stored, 19.5, NOW),
        # never stored, or stored without a sample behind it
        (None, 19.4, NOW),
        (SensorState(entity_hash="theHash", value=19.4), 19.4, NOW),
    ]
    for state, value, expected in tests:
        result = tested._instant(state, value, NOW)
        assert result == expected


def test__moved() -> None:
    tested = helper_instance()
    stored = SensorState(entity_hash="theHash", value=61.0)
    tests: list[tuple[SensorState | None, float | None, bool]] = [
        (stored, 62.0, True),
        (stored, 61.0, False),
        (None, 61.0, True),
        # nothing said is not news
        (stored, None, False),
        (None, None, False),
    ]
    for state, value, expected in tests:
        result = tested._moved(state, value)
        assert result is expected


def test__charged() -> None:
    tested = helper_instance()
    stored = SensorState(entity_hash="theHash", battery=87)
    tests: list[tuple[SensorState | None, int | None, bool]] = [
        (stored, 86, True),
        (stored, 87, False),
        (None, 87, True),
        (stored, None, False),
    ]
    for state, battery, expected in tests:
        result = tested._charged(state, battery)
        assert result is expected


def test__previous() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    rows = [
        {"entity_hash": "temperatureHash", "battery": 87, "measured_at": EARLIER, "value": Decimal("19.40")},
        # a sensor with no sample yet, and none that ever carried a charge
        {"entity_hash": "humidityHash", "battery": None, "measured_at": None, "value": None},
    ]
    database.fetch_all.side_effect = [rows]
    result = tested._previous(3)
    expected = {
        "temperatureHash": SensorState(
            entity_hash="temperatureHash",
            value=19.4,
            measured_at=EARLIER,
            battery=87,
        ),
        "humidityHash": SensorState(entity_hash="humidityHash", value=None, measured_at=None, battery=None),
    }
    assert result == expected
    assert database.mock_calls == [call.fetch_all(SQL_PREVIOUS, (3,))]
    reset_mocks()


def test__claim() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    tests: list[tuple[int, bool]] = [(1, True), (0, False)]
    for claimed, expected in tests:
        database.execute.side_effect = [claimed]
        result = tested._claim(11)
        assert result is expected
        assert database.mock_calls == [call.execute(SQL_CLAIM, (timedelta(minutes=10), 11))]
        reset_mocks()


def test__record() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.execute.side_effect = [1]
    result = tested._record(11, "", True)
    assert result is None
    assert database.mock_calls == [call.execute(SQL_RECORD, ("", True, 11))]
    reset_mocks()

    # a failure, and nothing stored: the last reading's instant stands still
    database.execute.side_effect = [1]
    tested._record(11, "SwitchBot could not be reached.")
    exp_calls = [call.execute(SQL_RECORD, ("SwitchBot could not be reached.", False, 11))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__feed() -> None:
    tested = helper_instance()

    result = tested._feed(helper_row())
    expected = helper_feed()
    assert result == expected

    row = helper_row() | {"hub_ids": "", "active": False, "webhook_at": WEBHOOK_AT}
    result = tested._feed(row)
    expected = SwitchBotFeed(
        feed_id=11,
        house_id=3,
        token="theToken",
        secret="theSecret",
        hub_ids=(),
        active=False,
        event_token="theEventToken",
        webhook_at=WEBHOOK_AT,
    )
    assert result == expected
