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
    assert mock_time.mock_calls == [call.sleep(3600), call.sleep(3600)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[REMINDER] tick failed: %s", error)]
    reset_mocks()


@patch("usage.commands.reminder_command.logging")
@patch("usage.commands.reminder_command.datetime", wraps=datetime)
def test_tick(mock_datetime: MagicMock, mock_logging: MagicMock) -> None:
    logger = MagicMock()

    def reset_mocks() -> None:
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
            WHERE reminders.enabled AND (reminders.sent_on IS NULL OR reminders.sent_on < %s)
            ORDER BY reminders.id
            """,
        ("2026-09-01",),
    )

    # not the first of the month: nothing happens
    mock_datetime.now.side_effect = [datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)]
    result = tested.tick()
    assert result is None
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert mock_logging.mock_calls == []
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_all()

    # first of the month: one reminder claimed and emailed, one already
    # claimed by the other colour, one whose email fails and is logged
    mock_datetime.now.side_effect = [datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)]
    sealed_rows = [
        {"id": 7, "email": "sealedJane", "house": "sealedFremur"},
        {"id": 8, "email": "sealedJohn", "house": "sealedFremur"},
        {"id": 9, "email": "sealedMary", "house": "sealedDougmar"},
    ]
    database.fetch_all.side_effect = [sealed_rows]
    database.decrypt_rows.side_effect = [
        [
            {"id": 7, "email": "jane@example.com", "house": "Fremur"},
            {"id": 8, "email": "john@example.com", "house": "Fremur"},
            {"id": 9, "email": "mary@example.com", "house": "Dougmar"},
        ],
    ]
    database.execute.side_effect = [0, 7, 0, 9]
    email_sender.send.side_effect = [True, False]
    mock_logging.getLogger.side_effect = [logger]
    result = tested.tick()
    assert result is None
    assert mock_datetime.mock_calls == [call.now(UTC)]
    assert mock_logging.mock_calls == [call.getLogger("usage")]
    assert logger.mock_calls == [call.warning("[REMINDER] email failed for reminder %s", 9)]
    exp_calls = [
        exp_materialize,
        exp_fetch,
        call.decrypt_rows(sealed_rows, ("email", "house")),
        call.execute(
            """
                UPDATE reminders SET sent_on = %s
                WHERE id = %s AND (sent_on IS NULL OR sent_on < %s)
                RETURNING id
                """,
            ("2026-09-01", 7, "2026-09-01"),
        ),
        call.execute(
            """
                UPDATE reminders SET sent_on = %s
                WHERE id = %s AND (sent_on IS NULL OR sent_on < %s)
                RETURNING id
                """,
            ("2026-09-01", 8, "2026-09-01"),
        ),
        call.execute(
            """
                UPDATE reminders SET sent_on = %s
                WHERE id = %s AND (sent_on IS NULL OR sent_on < %s)
                RETURNING id
                """,
            ("2026-09-01", 9, "2026-09-01"),
        ),
    ]
    assert database.mock_calls == exp_calls
    exp_calls = [
        call.send(
            "jane@example.com",
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
            "Usage: time to record the readings of Dougmar for August 2026",
            [
                "Hello,",
                "",
                "A new month has started - a good moment to record the meter readings of Dougmar for August 2026:",
                "https://usage.example.com",
                "",
                "You receive this monthly reminder for this house;",
                "you can turn it off in Settings > Account at any time.",
            ],
        ),
    ]
    assert email_sender.mock_calls == exp_calls
    reset_all()
