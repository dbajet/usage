from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.enphase_sync_command import EnphaseSyncCommand
from usage.libraries.enphase_client import EnphaseClient
from usage.structures.app_exception import AppException
from usage.structures.enphase_feed import EnphaseFeed
from usage.structures.enphase_point import EnphasePoint
from usage.structures.enphase_tokens import EnphaseTokens

NOW = datetime(2026, 9, 16, 7, 14, tzinfo=UTC)

SQL_DUE = """
            SELECT id, house_id, client_id_sealed AS client_id, client_secret_sealed AS client_secret,
                   api_key_sealed AS api_key, system_id_sealed AS system_id,
                   access_token_sealed AS access_token, refresh_token_sealed AS refresh_token,
                   token_expires_at, active, backfill_from, backfill_done, fine_from, fine_done,
                   calls_used, calls_budget, calls_month, production_path, last_sync_at
            FROM enphase_feeds
            WHERE active AND source = %s AND (claimed_until IS NULL OR claimed_until < now())
            ORDER BY id
            """
SQL_UPSERT = """
                    INSERT INTO enphase_points(feed_id, measured_at, span_minutes, production, consumption, battery_level)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (feed_id, measured_at, span_minutes) DO UPDATE
                    SET production = COALESCE(EXCLUDED.production, enphase_points.production),
                        consumption = COALESCE(EXCLUDED.consumption, enphase_points.consumption),
                        battery_level = COALESCE(EXCLUDED.battery_level, enphase_points.battery_level)
                    """
SQL_LAST_POINT = """
                UPDATE enphase_feeds
                SET last_point_at = (SELECT MAX(measured_at) FROM enphase_points WHERE feed_id = %s)
                WHERE id = %s
                """
SQL_CLAIM = """
            UPDATE enphase_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
            """
SQL_TOKENS = """
            UPDATE enphase_feeds
            SET access_token_sealed = %s, refresh_token_sealed = %s, token_expires_at = %s
            WHERE id = %s
            """
SQL_RECORD = """
            UPDATE enphase_feeds
            SET claimed_until = NULL, last_sync_at = now(), last_error = %s,
                calls_used = CASE
                    WHEN calls_month = date_trunc('month', now())::date THEN calls_used + %s
                    ELSE %s END,
                calls_month = date_trunc('month', now())::date
            WHERE id = %s
            """
SQL_RESTART_FINE = "UPDATE enphase_feeds SET fine_from = %s, fine_done = %s WHERE id = %s"
SQL_HISTORY_DONE = "UPDATE enphase_feeds SET backfill_done = true, backfill_from = %s WHERE id = %s"


def helper_instance() -> EnphaseSyncCommand:
    return EnphaseSyncCommand(MagicMock(), MagicMock())


def helper_feed(
    backfill_done: bool = False,
    fine_from: date | None = None,
    fine_done: bool = False,
    calls_used: int = 0,
    calls_budget: int = 1000,
    calls_month: date | None = None,
) -> EnphaseFeed:
    return EnphaseFeed(
        feed_id=11,
        house_id=3,
        client_id="theClientId",
        client_secret="theClientSecret",
        api_key="theApiKey",
        system_id="3456789",
        access_token="theAccessToken",
        refresh_token="theRefreshToken",
        token_expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
        active=True,
        backfill_from=None,
        backfill_done=backfill_done,
        fine_from=fine_from,
        fine_done=fine_done,
        calls_used=calls_used,
        calls_budget=calls_budget,
        calls_month=calls_month,
    )


def helper_row() -> dict[str, Any]:
    return {
        "id": 11,
        "house_id": 3,
        "client_id": "theClientId",
        "client_secret": "theClientSecret",
        "api_key": "theApiKey",
        "system_id": "3456789",
        "access_token": "theAccessToken",
        "refresh_token": "theRefreshToken",
        "token_expires_at": datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
        "active": True,
        "backfill_from": None,
        "backfill_done": False,
        "fine_from": None,
        "fine_done": False,
        "calls_used": 0,
        "calls_budget": 1000,
        "calls_month": None,
        "production_path": "",
        "last_sync_at": None,
    }


def helper_point(minute: int = 0, production: float | None = 0.412) -> EnphasePoint:
    return EnphasePoint(
        measured_at=datetime(2026, 9, 16, 7, minute, tzinfo=UTC),
        span_minutes=15,
        production=production,
    )


def test___init__() -> None:
    database = MagicMock()
    limiter = MagicMock()
    tested = EnphaseSyncCommand(database, limiter)
    assert tested._database is database
    assert tested._limiter is limiter
    assert database.mock_calls == []
    assert limiter.mock_calls == []


@patch("usage.commands.enphase_sync_command.threading.Thread")
def test_start(thread_class: MagicMock) -> None:
    thread = MagicMock()

    def reset_mocks() -> None:
        thread_class.reset_mock()
        thread.reset_mock()

    thread_class.side_effect = [thread]
    tested = helper_instance()
    result = tested.start()
    assert result is None
    assert thread_class.mock_calls == [call(target=tested._loop, name="enphase-sync", daemon=True)]
    assert thread.mock_calls == [call.start()]
    reset_mocks()


@patch("usage.commands.enphase_sync_command.logging")
@patch("usage.commands.enphase_sync_command.time")
@patch.object(EnphaseSyncCommand, "tick")
def test__loop(tick: MagicMock, mock_time: MagicMock, mock_logging: MagicMock) -> None:
    def reset_mocks() -> None:
        tick.reset_mock()
        mock_time.reset_mock()
        mock_logging.reset_mock()

    # the loop sleeps between rounds; the third sleep breaks the test out of it
    failure = Exception("theFailure")
    tick.side_effect = [None, failure, None]
    mock_time.sleep.side_effect = [None, None, RuntimeError("stop")]
    tested = helper_instance()
    with pytest.raises(RuntimeError):
        tested._loop()
    assert tick.mock_calls == [call(), call(), call()]
    assert mock_time.mock_calls == [call.sleep(60), call.sleep(60), call.sleep(60)]
    # a failed tick is written down and the loop goes round again
    exp_calls = [
        call.getLogger("usage"),
        call.getLogger().warning("[ENPHASE] tick failed: %s", failure),
    ]
    assert mock_logging.mock_calls == exp_calls
    reset_mocks()


@patch.object(EnphaseSyncCommand, "_run")
@patch.object(EnphaseSyncCommand, "_claim")
@patch.object(EnphaseSyncCommand, "_is_due")
def test_tick(is_due: MagicMock, claim: MagicMock, run: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        is_due.reset_mock()
        claim.reset_mock()
        run.reset_mock()
        database.reset_mock()

    sealed = ("client_id", "client_secret", "api_key", "system_id", "access_token", "refresh_token")
    exp_database = [call.fetch_all(SQL_DUE, ("cloud",)), call.decrypt_rows([helper_row()], sealed)]

    # a feed that is due and unclaimed is pulled
    database.fetch_all.side_effect = [[helper_row()]]
    database.decrypt_rows.side_effect = [[helper_row()]]
    is_due.side_effect = [True]
    claim.side_effect = [True]
    result = tested.tick()
    assert result is None
    assert is_due.mock_calls == [call(helper_feed(), None)]
    assert claim.mock_calls == [call(11)]
    assert run.mock_calls == [call(helper_feed())]
    assert database.mock_calls == exp_database
    reset_mocks()

    # not due yet: the allowance is not spent on it
    database.fetch_all.side_effect = [[helper_row()]]
    database.decrypt_rows.side_effect = [[helper_row()]]
    is_due.side_effect = [False]
    result = tested.tick()
    assert result is None
    assert is_due.mock_calls == [call(helper_feed(), None)]
    assert claim.mock_calls == []
    assert run.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()

    # the other colour got there first
    database.fetch_all.side_effect = [[helper_row()]]
    database.decrypt_rows.side_effect = [[helper_row()]]
    is_due.side_effect = [True]
    claim.side_effect = [False]
    result = tested.tick()
    assert result is None
    assert is_due.mock_calls == [call(helper_feed(), None)]
    assert claim.mock_calls == [call(11)]
    assert run.mock_calls == []
    assert database.mock_calls == exp_database
    reset_mocks()


@patch("usage.commands.enphase_sync_command.logging")
@patch.object(EnphaseSyncCommand, "_record")
@patch.object(EnphaseSyncCommand, "_save_tokens")
@patch.object(EnphaseSyncCommand, "_sync")
@patch.object(EnphaseSyncCommand, "_client")
def test__run(
    client_of: MagicMock,
    sync: MagicMock,
    save_tokens: MagicMock,
    record: MagicMock,
    mock_logging: MagicMock,
) -> None:
    client = MagicMock()
    tokens = EnphaseTokens(access_token="theNewAccess", refresh_token="theNewRefresh")

    def reset_mocks() -> None:
        client_of.reset_mock()
        sync.reset_mock()
        save_tokens.reset_mock()
        record.reset_mock()
        mock_logging.reset_mock()
        client.reset_mock()

    feed = helper_feed()

    # the happy path writes an empty message, which means "well"
    client.tokens = tokens
    client.calls = 6
    client_of.side_effect = [client]
    sync.side_effect = [None]
    tested = helper_instance()
    result = tested._run(feed)
    assert result is None
    assert client_of.mock_calls == [call(feed)]
    assert sync.mock_calls == [call(client, feed)]
    assert save_tokens.mock_calls == [call(feed, tokens)]
    assert record.mock_calls == [call(11, "", 6)]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # a refusal is written to the feed rather than raised
    client.tokens = tokens
    client.calls = 2
    client_of.side_effect = [client]
    sync.side_effect = [AppException(401, "Enphase refused the stored authorisation.")]
    tested = helper_instance()
    result = tested._run(feed)
    assert result is None
    assert client_of.mock_calls == [call(feed)]
    assert sync.mock_calls == [call(client, feed)]
    # the rotated pair is kept even though the pull failed: it is the only copy
    assert save_tokens.mock_calls == [call(feed, tokens)]
    assert record.mock_calls == [call(11, "Enphase refused the stored authorisation.", 2)]
    assert mock_logging.mock_calls == []
    reset_mocks()

    # an unknown failure must not strand the claim either
    failure = ValueError("theFailure")
    client.tokens = tokens
    client.calls = 1
    client_of.side_effect = [client]
    sync.side_effect = [failure]
    tested = helper_instance()
    result = tested._run(feed)
    assert result is None
    assert client_of.mock_calls == [call(feed)]
    assert sync.mock_calls == [call(client, feed)]
    assert save_tokens.mock_calls == [call(feed, tokens)]
    assert record.mock_calls == [call(11, "The import failed unexpectedly.", 1)]
    exp_calls = [
        call.getLogger("usage"),
        call.getLogger().warning("[ENPHASE] feed %s failed: %s", 11, failure),
    ]
    assert mock_logging.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.enphase_sync_command.datetime", wraps=datetime)
@patch.object(EnphaseSyncCommand, "_fine_chunk")
@patch.object(EnphaseSyncCommand, "_history")
@patch.object(EnphaseSyncCommand, "_store")
@patch.object(EnphaseSyncCommand, "_day")
@patch.object(EnphaseSyncCommand, "_recent_days")
def test__sync(
    recent_days: MagicMock,
    day_of: MagicMock,
    store: MagicMock,
    history: MagicMock,
    fine_chunk: MagicMock,
    mock_datetime: MagicMock,
) -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        recent_days.reset_mock()
        day_of.reset_mock()
        store.reset_mock()
        history.reset_mock()
        fine_chunk.reset_mock()
        mock_datetime.reset_mock()
        client.reset_mock()

    today = date(2026, 9, 16)
    yesterday = date(2026, 9, 15)
    points = [helper_point()]

    # a fresh feed: the recent days, then the daily history, then two fine days
    feed = helper_feed()
    walked = helper_feed(backfill_done=True)
    mock_datetime.now.side_effect = [NOW]
    recent_days.side_effect = [[today, yesterday]]
    day_of.side_effect = [points, points]
    store.side_effect = [1, 1]
    history.side_effect = [walked]
    fine_chunk.side_effect = [walked, walked]
    tested = helper_instance()
    result = tested._sync(client, feed)
    assert result is None
    assert recent_days.mock_calls == [call(today)]
    assert day_of.mock_calls == [call(client, "3456789", today), call(client, "3456789", yesterday)]
    assert store.mock_calls == [call(11, points), call(11, points)]
    assert history.mock_calls == [call(client, feed, today)]
    assert fine_chunk.mock_calls == [call(client, walked, today), call(client, walked, today)]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert client.mock_calls == []
    reset_mocks()

    # the daily history is already owned, and the fortnight is already walked
    feed = helper_feed(backfill_done=True, fine_done=True)
    mock_datetime.now.side_effect = [NOW]
    recent_days.side_effect = [[today]]
    day_of.side_effect = [points]
    store.side_effect = [1]
    tested = helper_instance()
    result = tested._sync(client, feed)
    assert result is None
    assert recent_days.mock_calls == [call(today)]
    assert day_of.mock_calls == [call(client, "3456789", today)]
    assert store.mock_calls == [call(11, points)]
    assert history.mock_calls == []
    assert fine_chunk.mock_calls == []
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert client.mock_calls == []
    reset_mocks()


def test__recent_days() -> None:
    tested = helper_instance()
    result = tested._recent_days(date(2026, 9, 16))
    expected = [date(2026, 9, 16), date(2026, 9, 15)]
    assert result == expected


def test__day() -> None:
    client = MagicMock()

    def reset_mocks() -> None:
        client.reset_mock()

    produced = [helper_point(0)]
    consumed = [helper_point(15)]
    charged = [helper_point(30)]
    client.production.side_effect = [produced]
    client.consumption.side_effect = [consumed]
    client.battery.side_effect = [charged]
    tested = helper_instance()
    result = tested._day(client, "3456789", date(2026, 9, 16))
    expected = [*produced, *consumed, *charged]
    assert result == expected
    exp_calls = [
        call.production("3456789", date(2026, 9, 16)),
        call.consumption("3456789", date(2026, 9, 16)),
        call.battery("3456789", date(2026, 9, 16)),
    ]
    assert client.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.enphase_sync_command.logging")
@patch.object(EnphaseSyncCommand, "_store")
def test__history(store: MagicMock, mock_logging: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        store.reset_mock()
        mock_logging.reset_mock()
        database.reset_mock()
        client.reset_mock()

    today = date(2026, 9, 16)
    feed = helper_feed()
    points = [helper_point()]
    exp_client = [call.daily("3456789", None, today)]
    exp_database = [call.execute(SQL_HISTORY_DONE, ("2026-09-16", 11))]

    # the whole life of the system, in two calls, once
    client.daily.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._history(client, feed, today)
    expected = helper_feed(backfill_done=True)._replace(backfill_from=today)
    assert result == expected
    assert store.mock_calls == [call(11, points)]
    assert client.mock_calls == exp_client
    assert database.mock_calls == exp_database
    assert mock_logging.mock_calls == []
    reset_mocks()

    # unreadable today is unreadable for ever: marked done rather than retried
    client.daily.side_effect = [AppException(422, "not JSON")]
    database.execute.side_effect = [11]
    result = tested._history(client, feed, today)
    assert result == expected
    assert store.mock_calls == []
    assert client.mock_calls == exp_client
    assert database.mock_calls == exp_database
    exp_calls = [
        call.getLogger("usage"),
        call.getLogger().warning("[ENPHASE] feed %s: unreadable history", 11),
    ]
    assert mock_logging.mock_calls == exp_calls
    reset_mocks()

    # a refusal or an outage is not a verdict on the history: it is raised
    client.daily.side_effect = [AppException(429, "rate limited")]
    with pytest.raises(AppException) as exc_info:
        tested._history(client, feed, today)
    assert exc_info.value.status_code == 429
    assert store.mock_calls == []
    assert client.mock_calls == exp_client
    assert database.mock_calls == []
    assert mock_logging.mock_calls == []
    reset_mocks()


@patch("usage.commands.enphase_sync_command.logging")
@patch.object(EnphaseSyncCommand, "_store")
@patch.object(EnphaseSyncCommand, "_day")
def test__fine_chunk(day_of: MagicMock, store: MagicMock, mock_logging: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    client = MagicMock()

    def reset_mocks() -> None:
        day_of.reset_mock()
        store.reset_mock()
        mock_logging.reset_mock()
        database.reset_mock()
        client.reset_mock()

    today = date(2026, 9, 16)
    points = [helper_point()]

    # the first step is today itself
    day_of.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._fine_chunk(client, helper_feed(), today)
    expected = helper_feed(fine_from=today)
    assert result == expected
    assert day_of.mock_calls == [call(client, "3456789", today)]
    assert store.mock_calls == [call(11, points)]
    assert database.mock_calls == [call.execute(SQL_RESTART_FINE, ("2026-09-16", False, 11))]
    assert mock_logging.mock_calls == []
    assert client.mock_calls == []
    reset_mocks()

    # one day further back each time
    day_of.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._fine_chunk(client, helper_feed(fine_from=date(2026, 9, 10)), today)
    expected = helper_feed(fine_from=date(2026, 9, 9))
    assert result == expected
    assert day_of.mock_calls == [call(client, "3456789", date(2026, 9, 9))]
    assert store.mock_calls == [call(11, points)]
    assert database.mock_calls == [call.execute(SQL_RESTART_FINE, ("2026-09-09", False, 11))]
    assert mock_logging.mock_calls == []
    assert client.mock_calls == []
    reset_mocks()

    # the fortnight is covered: the expensive walk stops for good
    day_of.side_effect = [points]
    store.side_effect = [1]
    database.execute.side_effect = [11]
    result = tested._fine_chunk(client, helper_feed(fine_from=date(2026, 9, 3)), today)
    expected = helper_feed(fine_from=date(2026, 9, 2), fine_done=True)
    assert result == expected
    assert day_of.mock_calls == [call(client, "3456789", date(2026, 9, 2))]
    assert store.mock_calls == [call(11, points)]
    assert database.mock_calls == [call.execute(SQL_RESTART_FINE, ("2026-09-02", True, 11))]
    assert mock_logging.mock_calls == []
    assert client.mock_calls == []
    reset_mocks()

    # a day that cannot be read is stepped over rather than retried for ever
    day_of.side_effect = [AppException(422, "not JSON")]
    database.execute.side_effect = [11]
    result = tested._fine_chunk(client, helper_feed(), today)
    expected = helper_feed(fine_from=today)
    assert result == expected
    assert day_of.mock_calls == [call(client, "3456789", today)]
    assert store.mock_calls == []
    assert database.mock_calls == [call.execute(SQL_RESTART_FINE, ("2026-09-16", False, 11))]
    exp_calls = [
        call.getLogger("usage"),
        call.getLogger().warning("[ENPHASE] feed %s: unreadable telemetry for %s", 11, today),
    ]
    assert mock_logging.mock_calls == exp_calls
    assert client.mock_calls == []
    reset_mocks()

    # anything else stops the tick
    day_of.side_effect = [AppException(429, "rate limited")]
    with pytest.raises(AppException) as exc_info:
        tested._fine_chunk(client, helper_feed(), today)
    assert exc_info.value.status_code == 429
    assert day_of.mock_calls == [call(client, "3456789", today)]
    assert store.mock_calls == []
    assert database.mock_calls == []
    assert mock_logging.mock_calls == []
    assert client.mock_calls == []
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

    points = [
        EnphasePoint(measured_at=datetime(2026, 9, 16, 7, 0, tzinfo=UTC), span_minutes=15, production=0.412),
        EnphasePoint(measured_at=datetime(2026, 9, 16, 7, 0, tzinfo=UTC), span_minutes=15, battery_level=87.5),
        EnphasePoint(measured_at=datetime(2026, 9, 15, tzinfo=UTC), span_minutes=1440, consumption=21.0),
    ]
    database.execute.side_effect = [1, 2, 3, 11]
    result = tested._store(11, points)
    expected = 3
    assert result == expected
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(SQL_UPSERT, (11, "2026-09-16T07:00:00+00:00", 15, 0.412, None, None)),
        call.execute(SQL_UPSERT, (11, "2026-09-16T07:00:00+00:00", 15, None, None, 87.5)),
        call.execute(SQL_UPSERT, (11, "2026-09-15T00:00:00+00:00", 1440, None, 21.0, None)),
        call.execute(SQL_LAST_POINT, (11, 11)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.enphase_sync_command.datetime", wraps=datetime)
@patch.object(EnphaseSyncCommand, "pace")
def test__is_due(pace: MagicMock, mock_datetime: MagicMock) -> None:
    def reset_mocks() -> None:
        pace.reset_mock()
        mock_datetime.reset_mock()

    feed = helper_feed()

    # never pulled: due at once, and without working out a pace for it
    tested = helper_instance()
    result = tested._is_due(feed, None)
    assert result is True
    assert pace.mock_calls == []
    assert mock_datetime.mock_calls == []
    reset_mocks()

    tests: list[tuple[datetime, bool]] = [
        (NOW - timedelta(seconds=7620), True),
        (NOW - timedelta(seconds=7619), True),
        (NOW - timedelta(seconds=7618), False),
        (NOW, False),
    ]
    for last_sync_at, expected in tests:
        pace.side_effect = [7619]
        mock_datetime.now.side_effect = [NOW]
        tested = helper_instance()
        result = tested._is_due(feed, last_sync_at)
        assert result is expected
        assert pace.mock_calls == [call(feed)]
        assert mock_datetime.mock_calls == [call.now(UTC)]
        reset_mocks()


@patch("usage.commands.enphase_sync_command.datetime", wraps=datetime)
def test_pace(mock_datetime: MagicMock) -> None:
    def reset_mocks() -> None:
        mock_datetime.reset_mock()

    # 2026-09-16 07:14 UTC to the first of October is 1_269_960 seconds
    tests: list[tuple[EnphaseFeed, int]] = [
        # a whole free allowance spread over what is left of the month
        (helper_feed(), 7619),
        # half of it already spent: the feed slows down to make the rest last
        (helper_feed(calls_used=500, calls_month=date(2026, 9, 1)), 15239),
        # a generous plan is held at the floor rather than hammering the API
        (helper_feed(calls_budget=1_000_000), 900),
        # a tiny one is held at the ceiling rather than going silent for a fortnight
        (helper_feed(calls_budget=6), 21600),
        # spent: nothing to do but wait for the month to turn
        (helper_feed(calls_used=1000, calls_month=date(2026, 9, 1)), 1_269_960),
        (helper_feed(calls_used=1200, calls_month=date(2026, 9, 1)), 1_269_960),
    ]
    # the turn of the month is built from the clock, so it is on the mock too
    exp_datetime = [call.now(UTC), call(2026, 10, 1, tzinfo=UTC)]
    for feed, expected in tests:
        mock_datetime.now.side_effect = [NOW]
        tested = helper_instance()
        result = tested.pace(feed)
        assert result == expected
        assert mock_datetime.mock_calls == exp_datetime
        reset_mocks()


def test__calls_left() -> None:
    tested = helper_instance()
    today = date(2026, 9, 16)
    tests: list[tuple[EnphaseFeed, int]] = [
        # never counted yet
        (helper_feed(), 1000),
        # counted this month: what is left of it
        (helper_feed(calls_used=250, calls_month=date(2026, 9, 1)), 750),
        # counted in an older month, so the allowance has come back since
        (helper_feed(calls_used=990, calls_month=date(2026, 8, 1)), 1000),
        (helper_feed(calls_used=990, calls_month=date(2025, 9, 1)), 1000),
        # no budget on the feed: the free plan's
        (helper_feed(calls_budget=0, calls_used=100, calls_month=date(2026, 9, 1)), 900),
    ]
    for feed, expected in tests:
        result = tested._calls_left(feed, today)
        assert result == expected


def test__seconds_left() -> None:
    tested = helper_instance()
    tests: list[tuple[datetime, float]] = [
        (NOW, 1_269_960.0),
        # the first instant of a month is the whole month
        (datetime(2026, 9, 1, tzinfo=UTC), 2_592_000.0),
        # December rolls the year, not just the month
        (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), 60.0),
        # never zero: a pace divided by it would not survive that
        (datetime(2026, 10, 1, tzinfo=UTC), 2_678_400.0),
    ]
    for now, expected in tests:
        result = tested._seconds_left(now)
        assert result == expected


def test__save_tokens() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    feed = helper_feed()

    # nothing rotated: no write at all
    result = tested._save_tokens(feed, EnphaseTokens(access_token="theAccessToken", refresh_token="theRefreshToken"))
    assert result is None
    assert database.mock_calls == []
    reset_mocks()

    # the pair that came back is the only one that still works
    tokens = EnphaseTokens(
        access_token="theNewAccess",
        refresh_token="theNewRefresh",
        expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    )
    database.encrypt.side_effect = ["sealedAccess", "sealedRefresh"]
    database.execute.side_effect = [11]
    result = tested._save_tokens(feed, tokens)
    assert result is None
    exp_calls = [
        call.encrypt("theNewAccess"),
        call.encrypt("theNewRefresh"),
        call.execute(SQL_TOKENS, ("sealedAccess", "sealedRefresh", "2026-09-17T07:14:00+00:00", 11)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # a pair with no stated life stores none
    database.encrypt.side_effect = ["sealedAccess", "sealedRefresh"]
    database.execute.side_effect = [11]
    result = tested._save_tokens(feed, EnphaseTokens(access_token="theNewAccess", refresh_token="theNewRefresh"))
    assert result is None
    exp_calls = [
        call.encrypt("theNewAccess"),
        call.encrypt("theNewRefresh"),
        call.execute(SQL_TOKENS, ("sealedAccess", "sealedRefresh", None, 11)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__claim() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_calls = [call.execute(SQL_CLAIM, (timedelta(minutes=30), 11))]
    tests: list[tuple[int, bool]] = [(11, True), (0, False)]
    for claimed, expected in tests:
        database.execute.side_effect = [claimed]
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
    result = tested._record(11, "", 6)
    assert result is None
    assert database.mock_calls == [call.execute(SQL_RECORD, ("", 6, 6, 11))]
    reset_mocks()

    database.execute.side_effect = [11]
    result = tested._record(11, "Enphase could not be reached.", 2)
    assert result is None
    exp_calls = [call.execute(SQL_RECORD, ("Enphase could not be reached.", 2, 2, 11))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__client() -> None:
    tested = helper_instance()
    result = tested._client(helper_feed())
    assert isinstance(result, EnphaseClient)
    # the shared window travels with every client the sync builds
    assert result._limiter is tested._limiter
    assert result._client_id == "theClientId"
    assert result._client_secret == "theClientSecret"
    assert result._api_key == "theApiKey"
    expected = EnphaseTokens(
        access_token="theAccessToken",
        refresh_token="theRefreshToken",
        expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
    )
    assert result.tokens == expected


def test__feed() -> None:
    tested = helper_instance()
    result = tested._feed(helper_row())
    expected = helper_feed()
    assert result == expected


def test__save_production_path() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    sql = "UPDATE enphase_feeds SET production_path = %s WHERE id = %s"

    # the pull found out something the feed did not know
    database.execute.side_effect = [11]
    result = tested._save_production_path(helper_feed(), "micro")
    assert result is None
    assert database.mock_calls == [call.execute(sql, ("micro", 11))]
    reset_mocks()

    # already known, and unchanged: nothing to write
    result = tested._save_production_path(helper_feed()._replace(production_path="micro"), "micro")
    assert result is None
    assert database.mock_calls == []
    reset_mocks()

    # a night taught it nothing, so the question stays open rather than being
    # closed with an empty answer
    result = tested._save_production_path(helper_feed()._replace(production_path="micro"), "")
    assert result is None
    assert database.mock_calls == []
    reset_mocks()
