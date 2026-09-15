from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.water_sync_command import WaterSyncCommand
from usage.libraries.email_texts import EmailTexts
from usage.structures.app_exception import AppException
from usage.structures.settings import Settings
from usage.structures.water_feed import WaterFeed
from usage.structures.water_leak import WaterLeak
from usage.structures.water_point import WaterPoint

SQL_DUE = """
            SELECT id, house_id, hostname, username_sealed AS username, password_sealed AS password,
                   meter_uuid_sealed AS meter_uuid, export_unit, active, backfill_from, backfill_done, empty_chunks
            FROM water_feeds
            WHERE active AND (claimed_until IS NULL OR claimed_until < now())
              AND (last_sync_at IS NULL OR last_sync_at < now() - %s)
            ORDER BY id
            """
SQL_UPSERT = """
                    INSERT INTO water_points(feed_id, measured_at, volume, reading, method)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (feed_id, measured_at) DO UPDATE
                    SET volume = EXCLUDED.volume, reading = EXCLUDED.reading, method = EXCLUDED.method
                    """
SQL_LAST_POINT = """
                UPDATE water_feeds
                SET last_point_at = (SELECT MAX(measured_at) FROM water_points WHERE feed_id = %s)
                WHERE id = %s
                """
SQL_CLAIM = """
            UPDATE water_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
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


def helper_instance() -> WaterSyncCommand:
    return WaterSyncCommand(MagicMock(), helper_settings(), MagicMock())


def helper_feed(
    backfill_from: date | None = None,
    backfill_done: bool = False,
    empty_chunks: int = 0,
) -> WaterFeed:
    return WaterFeed(
        feed_id=11,
        house_id=3,
        hostname="eyeonwater.com",
        username="theUsername",
        password="thePassword",
        meter_uuid="1234567890123456789",
        export_unit="Gallons",
        active=True,
        backfill_from=backfill_from,
        backfill_done=backfill_done,
        empty_chunks=empty_chunks,
    )


def helper_point(minute: int = 14, volume: float = 0.0096) -> WaterPoint:
    return WaterPoint(
        measured_at=datetime(2026, 9, 14, 7, minute, tzinfo=UTC),
        volume=volume,
        reading=515.6251,
        method="Network",
    )


def helper_row() -> dict[str, Any]:
    return {
        "id": 11,
        "house_id": 3,
        "hostname": "eyeonwater.com",
        "username": "theUsername",
        "password": "thePassword",
        "meter_uuid": "1234567890123456789",
        "export_unit": "Gallons",
        "active": True,
        "backfill_from": None,
        "backfill_done": False,
        "empty_chunks": 0,
    }


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    email_sender = MagicMock()
    tested = WaterSyncCommand(database, settings, email_sender)
    assert tested._database is database
    assert tested._settings is settings
    assert tested._email_sender is email_sender


@patch("usage.commands.water_sync_command.threading")
def test_start(mock_threading: MagicMock) -> None:
    thread = MagicMock()

    def reset_mocks() -> None:
        mock_threading.reset_mock()
        thread.reset_mock()

    tested = helper_instance()
    mock_threading.Thread.side_effect = [thread]
    result = tested.start()
    assert result is None
    exp_calls = [call.Thread(target=tested._loop, name="water-sync", daemon=True)]
    assert mock_threading.mock_calls == exp_calls
    assert thread.mock_calls == [call.start()]
    reset_mocks()


@patch("usage.commands.water_sync_command.logging")
@patch("usage.commands.water_sync_command.time")
@patch.object(WaterSyncCommand, "tick")
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
    assert logger.mock_calls == [call.warning("[WATER] tick failed: %s", error)]
    reset_mocks()


@patch("usage.commands.water_sync_command.logging")
@patch.object(WaterSyncCommand, "_record")
@patch.object(WaterSyncCommand, "_sync")
@patch.object(WaterSyncCommand, "_claim")
@patch.object(WaterSyncCommand, "_feed")
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
        call.fetch_all(SQL_DUE, (timedelta(seconds=900),)),
        call.decrypt_rows([row], ("username", "password", "meter_uuid")),
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

    # EyeOnWater said no: the reason is kept and the claim released
    error = AppException(401, "EyeOnWater rejected the username or password.")
    database.fetch_all.side_effect = [[row]]
    database.decrypt_rows.side_effect = [[row]]
    feed_of.side_effect = [feed]
    claim.side_effect = [True]
    sync.side_effect = [error]
    record.side_effect = [None]
    tested.tick()
    assert sync.mock_calls == [call(feed)]
    assert record.mock_calls == [call(11, "EyeOnWater rejected the username or password.")]
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
    assert logger.mock_calls == [call.warning("[WATER] feed %s failed: %s", 11, unknown)]
    assert database.mock_calls == exp_database
    reset_mocks()


@patch("usage.commands.water_sync_command.datetime", wraps=datetime)
@patch.object(WaterSyncCommand, "_leak")
@patch.object(WaterSyncCommand, "_record")
@patch.object(WaterSyncCommand, "_chunk")
@patch.object(WaterSyncCommand, "_store")
@patch.object(WaterSyncCommand, "_client")
def test__sync(
    client_of: MagicMock,
    store: MagicMock,
    chunk: MagicMock,
    record: MagicMock,
    leak: MagicMock,
    mock_datetime: MagicMock,
) -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        client_of.reset_mock()
        store.reset_mock()
        chunk.reset_mock()
        record.reset_mock()
        leak.reset_mock()
        mock_datetime.reset_mock()
        client.reset_mock()

    tested = helper_instance()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    points = [helper_point()]

    # the history is in: only the rolling window is asked for
    feed = helper_feed(backfill_done=True)
    client_of.side_effect = [client]
    mock_datetime.now.side_effect = [now]
    client.export.side_effect = [points]
    store.side_effect = [1]
    record.side_effect = [None]
    leak.side_effect = [None]
    result = tested._sync(feed)
    assert result is None
    assert client_of.mock_calls == [call(feed)]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert client.mock_calls == [call.export("1234567890123456789", date(2026, 9, 13), date(2026, 9, 15))]
    assert store.mock_calls == [call(11, points)]
    assert chunk.mock_calls == []
    assert record.mock_calls == [call(11, "")]
    assert leak.mock_calls == [call(feed)]
    reset_mocks()

    # still walking back: four chunks a round, and the walk stops when it ends
    feed = helper_feed()
    walked = helper_feed(backfill_from=date(2026, 8, 15), empty_chunks=1)
    done = helper_feed(backfill_from=date(2026, 7, 15), backfill_done=True, empty_chunks=2)
    client_of.side_effect = [client]
    mock_datetime.now.side_effect = [now]
    client.export.side_effect = [points]
    store.side_effect = [1]
    chunk.side_effect = [walked, done]
    record.side_effect = [None]
    leak.side_effect = [None]
    tested._sync(feed)
    assert chunk.mock_calls == [call(client, feed, date(2026, 9, 15)), call(client, walked, date(2026, 9, 15))]
    assert record.mock_calls == [call(11, "")]
    reset_mocks()

    # a walk that never ends is capped at four chunks a round
    feed = helper_feed()
    client_of.side_effect = [client]
    mock_datetime.now.side_effect = [now]
    client.export.side_effect = [points]
    store.side_effect = [1]
    chunk.side_effect = [feed, feed, feed, feed]
    record.side_effect = [None]
    leak.side_effect = [None]
    tested._sync(feed)
    assert chunk.mock_calls == [call(client, feed, date(2026, 9, 15))] * 4
    reset_mocks()


@patch.object(WaterSyncCommand, "_store")
def test__chunk(store: MagicMock) -> None:
    client = MagicMock()
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        store.reset_mock()
        client.reset_mock()
        database.reset_mock()

    points = [helper_point()]
    today = date(2026, 9, 15)

    # the first chunk starts at today and reaches a month back
    feed = helper_feed()
    client.export.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._chunk(client, feed, today)
    expected = helper_feed(backfill_from=date(2026, 8, 16), empty_chunks=0)
    assert result == expected
    assert client.mock_calls == [call.export("1234567890123456789", date(2026, 8, 16), date(2026, 9, 15))]
    assert store.mock_calls == [call(11, points)]
    exp_calls = [
        call.execute(
            "UPDATE water_feeds SET backfill_from = %s, empty_chunks = %s, backfill_done = %s WHERE id = %s",
            ("2026-08-16", 0, False, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the next one carries on from the day before the last start
    feed = helper_feed(backfill_from=date(2026, 8, 16))
    client.export.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._chunk(client, feed, today)
    expected = helper_feed(backfill_from=date(2026, 7, 16), empty_chunks=0)
    assert result == expected
    assert client.mock_calls == [call.export("1234567890123456789", date(2026, 7, 16), date(2026, 8, 15))]
    reset_mocks()

    # an empty month is counted, and the second one in a row ends the walk
    feed = helper_feed(backfill_from=date(2026, 8, 16))
    client.export.side_effect = [[]]
    store.side_effect = [0]
    database.execute.side_effect = [11]
    result = tested._chunk(client, feed, today)
    expected = helper_feed(backfill_from=date(2026, 7, 16), empty_chunks=1)
    assert result == expected
    exp_calls = [
        call.execute(
            "UPDATE water_feeds SET backfill_from = %s, empty_chunks = %s, backfill_done = %s WHERE id = %s",
            ("2026-07-16", 1, False, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    feed = helper_feed(backfill_from=date(2026, 8, 16), empty_chunks=1)
    client.export.side_effect = [[]]
    store.side_effect = [0]
    database.execute.side_effect = [11]
    result = tested._chunk(client, feed, today)
    expected = helper_feed(backfill_from=date(2026, 7, 16), backfill_done=True, empty_chunks=2)
    assert result == expected
    exp_calls = [
        call.execute(
            "UPDATE water_feeds SET backfill_from = %s, empty_chunks = %s, backfill_done = %s WHERE id = %s",
            ("2026-07-16", 2, True, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.water_sync_command.logging")
@patch.object(WaterSyncCommand, "_store")
def test__chunk__unreadable(store: MagicMock, mock_logging: MagicMock) -> None:
    client = MagicMock()
    logger = MagicMock()
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        store.reset_mock()
        mock_logging.reset_mock()
        client.reset_mock()
        logger.reset_mock()
        database.reset_mock()

    feed = helper_feed(backfill_from=date(2026, 8, 16))
    today = date(2026, 9, 15)

    # An export whose rows cannot be read counts as barren: retrying it every tick
    # would pin the whole walk on one bad month.
    client.export.side_effect = [AppException(422, "The EyeOnWater export was not in the expected format.")]
    database.execute.side_effect = [11]
    mock_logging.getLogger.side_effect = [logger]
    result = tested._chunk(client, feed, today)
    expected = helper_feed(backfill_from=date(2026, 7, 16), empty_chunks=1)
    assert result == expected
    assert store.mock_calls == []
    assert client.mock_calls == [call.export("1234567890123456789", date(2026, 7, 16), date(2026, 8, 15))]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    exp_calls = [call.warning("[WATER] feed %s: unreadable export for %s to %s", 11, date(2026, 7, 16), date(2026, 8, 15))]
    assert logger.mock_calls == exp_calls
    exp_calls = [
        call.execute(
            "UPDATE water_feeds SET backfill_from = %s, empty_chunks = %s, backfill_done = %s WHERE id = %s",
            ("2026-07-16", 1, False, 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # anything else is the sync's problem, not the walk's: it goes up
    client.export.side_effect = [AppException(502, "EyeOnWater could not be reached.")]
    with pytest.raises(AppException) as exc_info:
        tested._chunk(client, feed, today)
    assert exc_info.value.status_code == 502
    assert store.mock_calls == []
    assert mock_logging.mock_calls == []
    assert logger.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()


@patch.object(WaterSyncCommand, "_send_leak")
@patch.object(WaterSyncCommand, "_continuous_flow")
def test__leak(reading_day: MagicMock, send_leak: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        reading_day.reset_mock()
        send_leak.reset_mock()
        database.reset_mock()

    feed = helper_feed()
    leak = WaterLeak(feed_id=11, readings=96, hours=23.8, smallest=0.003, total=0.412)
    sql = "UPDATE water_feeds SET leaking = %s WHERE id = %s AND leaking IS DISTINCT FROM %s RETURNING id"

    # a day that never went quiet, and the feed did not know it yet
    reading_day.side_effect = [leak]
    database.execute.side_effect = [11]
    result = tested._leak(feed)
    assert result is None
    assert reading_day.mock_calls == [call(11)]
    assert database.mock_calls == [call.execute(sql, (True, 11, True))]
    assert send_leak.mock_calls == [call(3, leak)]
    reset_mocks()

    # the same day again: the state has not moved, so nothing is sent
    reading_day.side_effect = [leak]
    database.execute.side_effect = [0]
    tested._leak(feed)
    assert database.mock_calls == [call.execute(sql, (True, 11, True))]
    assert send_leak.mock_calls == []
    reset_mocks()

    # back to normal: the state is cleared quietly, with no email
    reading_day.side_effect = [None]
    database.execute.side_effect = [11]
    tested._leak(feed)
    assert database.mock_calls == [call.execute(sql, (False, 11, False))]
    assert send_leak.mock_calls == []
    reset_mocks()


def test__continuous_flow() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = """
            SELECT COUNT(*) AS readings, MIN(volume) AS smallest, SUM(volume) AS total,
                   MIN(measured_at) AS oldest, MAX(measured_at) AS newest
            FROM water_points
            WHERE feed_id = %s
              AND measured_at > (SELECT MAX(measured_at) FROM water_points WHERE feed_id = %s) - %s
            """
    exp_calls = [call.fetch_one(sql, (11, 11, timedelta(hours=24)))]
    oldest = datetime(2026, 9, 14, 0, 14, tzinfo=UTC)
    newest = datetime(2026, 9, 14, 23, 59, tzinfo=UTC)

    def row(**changes: Any) -> dict[str, Any]:
        return {
            "readings": 96,
            "smallest": Decimal("0.003"),
            "total": Decimal("0.412"),
            "oldest": oldest,
            "newest": newest,
        } | changes

    # a full day of readings and not one of them zero
    database.fetch_one.side_effect = [row()]
    result = tested._continuous_flow(11)
    expected = WaterLeak(feed_id=11, readings=96, hours=23.8, smallest=0.003, total=0.412)
    assert result == expected
    assert database.mock_calls == exp_calls
    reset_mocks()

    # every way a day says nothing is wrong, or says nothing at all
    tests: list[dict[str, Any] | None] = [
        None,
        row(oldest=None),
        row(newest=None),
        # one quiet quarter of an hour is all it takes
        row(smallest=Decimal("0")),
        # too few readings, or too short a stretch, to be a day at all
        row(readings=19),
        row(newest=datetime(2026, 9, 14, 12, 0, tzinfo=UTC)),
    ]
    for answer in tests:
        database.fetch_one.side_effect = [answer]
        result = tested._continuous_flow(11)
        assert result is None
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch("usage.commands.water_sync_command.logging")
@patch.object(EmailTexts, "water_leak")
def test__send_leak(water_leak: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()
    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender

    def reset_mocks() -> None:
        water_leak.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()
        database.reset_mock()
        email_sender.reset_mock()

    leak = WaterLeak(feed_id=11, readings=96, hours=23.8, smallest=0.003, total=0.412)
    recipients_sql = """
            SELECT users.email_sealed AS email
            FROM water_alerts
            JOIN users ON users.id = water_alerts.user_id
            JOIN user_houses ON user_houses.user_id = water_alerts.user_id
                            AND user_houses.house_id = water_alerts.house_id
            WHERE water_alerts.house_id = %s AND water_alerts.enabled
            ORDER BY water_alerts.user_id
            """

    # nobody asked for them: not even the house name is looked up
    database.fetch_all.side_effect = [[]]
    result = tested._send_leak(3, leak)
    assert result is None
    assert database.mock_calls == [call.fetch_all(recipients_sql, (3,))]
    assert water_leak.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()

    database.fetch_all.side_effect = [[{"email": "sealedJane"}]]
    database.fetch_one.side_effect = [{"name": "sealedDougmar"}]
    database.decrypt.side_effect = ["Dougmar", "jane@example.com"]
    water_leak.side_effect = [("theSubject", ["theBody"])]
    email_sender.send.side_effect = [True]
    tested._send_leak(3, leak)
    exp_calls = [
        call.fetch_all(recipients_sql, (3,)),
        call.fetch_one("SELECT name_sealed AS name FROM houses WHERE id = %s", (3,)),
        call.decrypt("sealedDougmar"),
        call.decrypt("sealedJane"),
    ]
    assert database.mock_calls == exp_calls
    assert water_leak.mock_calls == [call("Dougmar", leak, "https://usage.example.com")]
    assert email_sender.mock_calls == [call.send("jane@example.com", "theSubject", ["theBody"])]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # a house that vanished under us still names its recipients
    database.fetch_all.side_effect = [[{"email": "sealedJane"}]]
    database.fetch_one.side_effect = [None]
    database.decrypt.side_effect = ["jane@example.com"]
    water_leak.side_effect = [("theSubject", ["theBody"])]
    email_sender.send.side_effect = [False]
    mock_logging.getLogger.side_effect = [logger]
    tested._send_leak(3, leak)
    assert water_leak.mock_calls == [call("", leak, "https://usage.example.com")]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[WATER] leak email failed for %s of house %s", "jane@example.com", 3)]
    reset_mocks()


def test__store() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # nothing to store: not even a transaction
    result = tested._store(11, [])
    expected = 0
    assert result == expected
    assert database.mock_calls == []
    reset_mocks()

    points = [helper_point(14), helper_point(29, 0.0)]
    database.execute.side_effect = [1, 2, 11]
    result = tested._store(11, points)
    expected = 2
    assert result == expected
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(SQL_UPSERT, (11, "2026-09-14T07:14:00+00:00", 0.0096, 515.6251, "Network")),
        call.execute(SQL_UPSERT, (11, "2026-09-14T07:29:00+00:00", 0.0, 515.6251, "Network")),
        call.execute(SQL_LAST_POINT, (11, 11)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__claim() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_calls = [call.execute(SQL_CLAIM, (timedelta(minutes=30), 11))]
    tests = [(11, True), (0, False)]
    for returned, expected in tests:
        database.execute.side_effect = [returned]
        result = tested._claim(11)
        assert result is expected
        assert database.mock_calls == exp_calls
        reset_mocks()


def test__record() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.execute.side_effect = [11]
    result = tested._record(11, "EyeOnWater could not be reached.")
    assert result is None
    exp_calls = [
        call.execute(
            "UPDATE water_feeds SET claimed_until = NULL, last_sync_at = now(), last_error = %s WHERE id = %s",
            ("EyeOnWater could not be reached.", 11),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.water_sync_command.EyeOnWaterClient")
def test__client(client_class: MagicMock) -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        client_class.reset_mock()
        client.reset_mock()

    tested = WaterSyncCommand
    client_class.side_effect = [client]
    result = tested._client(helper_feed())
    assert result is client
    exp_calls = [call("eyeonwater.com", "theUsername", "thePassword", "Gallons")]
    assert client_class.mock_calls == exp_calls
    assert client.mock_calls == []
    reset_mocks()


def test__feed() -> None:
    tested = WaterSyncCommand
    result = tested._feed(helper_row())
    expected = helper_feed()
    assert result == expected

    result = tested._feed({**helper_row(), "backfill_from": date(2021, 4, 1), "backfill_done": True, "empty_chunks": 2})
    expected = helper_feed(backfill_from=date(2021, 4, 1), backfill_done=True, empty_chunks=2)
    assert result == expected
