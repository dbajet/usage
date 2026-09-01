from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.reminder_command import ReminderCommand
from usage.structures.settings import Settings


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


def helper_instance() -> ReminderCommand:
    return ReminderCommand(MagicMock(), helper_settings(), MagicMock())


def test___init__() -> None:
    database = MagicMock()
    email_sender = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()
        email_sender.reset_mock()

    settings = helper_settings()
    tested = ReminderCommand(database, settings, email_sender)
    assert tested._database is database
    assert tested._settings == settings
    assert tested._email_sender is email_sender
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()


@patch("usage.commands.reminder_command.threading")
def test_start(mock_threading: MagicMock) -> None:
    thread = MagicMock()

    def reset_mocks() -> None:
        mock_threading.reset_mock()
        thread.reset_mock()

    tested = helper_instance()
    mock_threading.Thread.side_effect = [thread]
    result = tested.start()
    assert result is None
    exp_calls = [call.Thread(target=tested._loop, name="reminders", daemon=True)]
    assert mock_threading.mock_calls == exp_calls
    assert thread.mock_calls == [call.start()]
    reset_mocks()


@patch("usage.commands.reminder_command.logging")
@patch("usage.commands.reminder_command.time")
@patch.object(ReminderCommand, "tick")
def test__loop(tick: MagicMock, mock_time: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()

    def reset_mocks() -> None:
        tick.reset_mock()
        mock_time.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()

    tested = helper_instance()
    # two iterations - the first tick fails and is logged, the second works -
    # then the sleep breaks the endless loop for the test
    error = RuntimeError("boom")
    stop = KeyboardInterrupt()
    tick.side_effect = [error, None]
    mock_time.sleep.side_effect = [None, stop]
    mock_logging.getLogger.side_effect = [logger]
    with pytest.raises(KeyboardInterrupt):
        tested._loop()
    assert tick.mock_calls == [call(), call()]
    assert mock_time.mock_calls == [call.sleep(300), call.sleep(300)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[REMINDER] tick failed: %s", error)]
    reset_mocks()


@patch("usage.commands.reminder_command.logging")
@patch("usage.commands.reminder_command.datetime", wraps=datetime)
@patch.object(ReminderCommand, "_local_time")
@patch.object(ReminderCommand, "_is_due")
def test_tick(is_due: MagicMock, local_time: MagicMock, mock_datetime: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()

    def reset_mocks() -> None:
        is_due.reset_mock()
        local_time.reset_mock()
        mock_datetime.reset_mock()
        mock_logging.reset_mock()
        logger.reset_mock()

    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender

    def reset_all() -> None:
        reset_mocks()
        database.reset_mock()
        email_sender.reset_mock()

    now = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)
    house_rows = [{"id": 1, "timezone": "Europe/Paris"}, {"id": 2, "timezone": "America/Los_Angeles"}]
    exp_houses_fetch = call.fetch_all("SELECT id, timezone FROM houses ORDER BY id")
    exp_materialize = call.execute(
        """
            INSERT INTO reminders(user_id, house_id)
            SELECT user_id, house_id FROM user_houses
            ON CONFLICT (user_id, house_id) DO NOTHING
            """,
    )
    exp_fetch = call.fetch_all(
        """
                SELECT reminders.id, users.email_sealed AS email, houses.name_sealed AS house
                FROM reminders
                JOIN users ON users.id = reminders.user_id
                JOIN houses ON houses.id = reminders.house_id
                WHERE reminders.house_id = %s AND reminders.enabled
                  AND (reminders.sent_on IS NULL OR reminders.sent_on < %s)
                ORDER BY reminders.id
                """,
        (1, "2026-09-01"),
    )

    # no house has reached 06:15 on the first: nothing happens
    mock_datetime.now.side_effect = [now]
    database.fetch_all.side_effect = [house_rows]
    is_due.side_effect = [False, False]
    result = tested.tick()
    assert result is None
    assert is_due.mock_calls == [call(now, "Europe/Paris"), call(now, "America/Los_Angeles")]
    assert local_time.mock_calls == []
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert mock_logging.mock_calls == []
    assert database.mock_calls == [exp_houses_fetch]
    assert email_sender.mock_calls == []
    reset_all()

    # the first house is past 06:15 local on the first: one reminder claimed
    # and emailed, one already claimed by the other colour, one whose email
    # fails and is logged; the second house is not due yet
    mock_datetime.now.side_effect = [now]
    database.fetch_all.side_effect = [house_rows, [
        {"id": 7, "email": "sealedJane", "house": "sealedFremur"},
        {"id": 8, "email": "sealedJohn", "house": "sealedFremur"},
        {"id": 9, "email": "sealedMary", "house": "sealedFremur"},
    ]]
    is_due.side_effect = [True, False]
    local_time.side_effect = [datetime(2026, 9, 1, 10, 0, 0)]
    database.decrypt_rows.side_effect = [
        [
            {"id": 7, "email": "jane@example.com", "house": "Fremur"},
            {"id": 8, "email": "john@example.com", "house": "Fremur"},
            {"id": 9, "email": "mary@example.com", "house": "Fremur"},
        ],
    ]
    database.execute.side_effect = [0, 0, 8, 9]
    email_sender.send.side_effect = [True, False]
    mock_logging.getLogger.side_effect = [logger]
    result = tested.tick()
    assert result is None
    assert is_due.mock_calls == [call(now, "Europe/Paris"), call(now, "America/Los_Angeles")]
    assert local_time.mock_calls == [call(now, "Europe/Paris")]
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[REMINDER] email failed for reminder %s", 9)]
    exp_claim = """
                    UPDATE reminders SET sent_on = %s
                    WHERE id = %s AND (sent_on IS NULL OR sent_on < %s)
                    RETURNING id
                    """
    exp_calls = [
        exp_houses_fetch,
        exp_materialize,
        exp_fetch,
        call.decrypt_rows(
            [
                {"id": 7, "email": "sealedJane", "house": "sealedFremur"},
                {"id": 8, "email": "sealedJohn", "house": "sealedFremur"},
                {"id": 9, "email": "sealedMary", "house": "sealedFremur"},
            ],
            ("email", "house"),
        ),
        call.execute(exp_claim, ("2026-09-01", 7, "2026-09-01")),
        call.execute(exp_claim, ("2026-09-01", 8, "2026-09-01")),
        call.execute(exp_claim, ("2026-09-01", 9, "2026-09-01")),
    ]
    assert database.mock_calls == exp_calls
    exp_calls = [
        call.send(
            "john@example.com",
            "Usage: time to record the readings of Fremur for August 2026",
            [
                "Hello,",
                "",
                "A new month has started - a good moment to record the meter readings of Fremur for August 2026:",
                "https://usage.example.com",
                "",
                "You receive this monthly reminder for this house;",
                "you can turn it off in Settings > Account at any time.",
            ],
        ),
        call.send(
            "mary@example.com",
            "Usage: time to record the readings of Fremur for August 2026",
            [
                "Hello,",
                "",
                "A new month has started - a good moment to record the meter readings of Fremur for August 2026:",
                "https://usage.example.com",
                "",
                "You receive this monthly reminder for this house;",
                "you can turn it off in Settings > Account at any time.",
            ],
        ),
    ]
    assert email_sender.mock_calls == exp_calls
    reset_all()


def test__local_time() -> None:
    tested = ReminderCommand
    now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    tests = [
        ("Europe/Paris", "2026-09-01T14:00:00+02:00"),
        ("America/Los_Angeles", "2026-09-01T05:00:00-07:00"),
        # an unknown zone falls back to UTC
        ("Mars/Olympus", "2026-09-01T12:00:00+00:00"),
        ("", "2026-09-01T12:00:00+00:00"),
    ]
    for timezone, expected in tests:
        result = tested._local_time(now, timezone).isoformat()
        assert result == expected, f"---> {timezone}"


def test__is_due() -> None:
    tested = ReminderCommand
    tests = [
        # 06:15 in Paris (UTC+2 in September) is 04:15 UTC
        (datetime(2026, 9, 1, 4, 15, 0, tzinfo=UTC), "Europe/Paris", True),
        (datetime(2026, 9, 1, 4, 14, 0, tzinfo=UTC), "Europe/Paris", False),
        # 06:15 in Los Angeles (UTC-7 in September) is 13:15 UTC
        (datetime(2026, 9, 1, 13, 15, 0, tzinfo=UTC), "America/Los_Angeles", True),
        (datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC), "America/Los_Angeles", False),
        # still the previous month in Los Angeles at midnight UTC
        (datetime(2026, 9, 1, 0, 30, 0, tzinfo=UTC), "America/Los_Angeles", False),
        # the reminder stays due for the rest of the first day
        (datetime(2026, 9, 1, 21, 45, 0, tzinfo=UTC), "Europe/Paris", True),
        # not the first of the month
        (datetime(2026, 9, 2, 8, 0, 0, tzinfo=UTC), "Europe/Paris", False),
        # an unknown zone falls back to UTC
        (datetime(2026, 9, 1, 6, 15, 0, tzinfo=UTC), "Mars/Olympus", True),
        (datetime(2026, 9, 1, 6, 14, 0, tzinfo=UTC), "Mars/Olympus", False),
    ]
    for now, timezone, expected in tests:
        result = tested._is_due(now, timezone)
        assert result is expected, f"---> {now} {timezone}"
