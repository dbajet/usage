from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.switch_bot_feed import SwitchBotFeed


def test_class() -> None:
    tested = SwitchBotFeed
    fields = ["feed_id", "house_id", "token", "secret", "hub_ids", "active", "event_token", "webhook_at"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SwitchBotFeed, dict[str, Any]]] = [
        (
            SwitchBotFeed(
                feed_id=11,
                house_id=3,
                token="theToken",
                secret="theSecret",
                hub_ids=("FA7310762361", "E1B2C3D4E5F6"),
                active=True,
                event_token="theEventToken",
                webhook_at=datetime(2026, 9, 18, 12, 30, tzinfo=UTC),
            ),
            {
                "feed_id": 11,
                "house_id": 3,
                "token": "theToken",
                "secret": "theSecret",
                "hub_ids": ["FA7310762361", "E1B2C3D4E5F6"],
                "active": True,
                "event_token": "theEventToken",
                "webhook_at": "2026-09-18T12:30:00+00:00",
            },
        ),
        (
            SwitchBotFeed(feed_id=0, house_id=0, token="", secret="", active=False),
            {"feed_id": 0, "house_id": 0, "token": "", "secret": "", "hub_ids": [], "active": False,
             "event_token": "", "webhook_at": None},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SwitchBotFeed
    tests: list[tuple[dict[str, Any], SwitchBotFeed]] = [
        (
            {
                "feed_id": 11,
                "house_id": 3,
                "token": "theToken",
                "secret": "theSecret",
                "hub_ids": ["FA7310762361", "E1B2C3D4E5F6"],
                "active": True,
                "event_token": "theEventToken",
                "webhook_at": "2026-09-18T12:30:00+00:00",
            },
            SwitchBotFeed(
                feed_id=11,
                house_id=3,
                token="theToken",
                secret="theSecret",
                hub_ids=("FA7310762361", "E1B2C3D4E5F6"),
                active=True,
                event_token="theEventToken",
                webhook_at=datetime(2026, 9, 18, 12, 30, tzinfo=UTC),
            ),
        ),
        ({}, SwitchBotFeed(feed_id=0, house_id=0, token="", secret="", hub_ids=(), active=False,
                           event_token="", webhook_at=None)),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
