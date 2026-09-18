from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.switch_bot_event import SwitchBotEvent


def test_class() -> None:
    tested = SwitchBotEvent
    fields = ["device_id", "temperature", "measured_at", "humidity", "battery"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SwitchBotEvent, dict[str, Any]]] = [
        (
            SwitchBotEvent(
                device_id="C271111EC0AB",
                temperature=26.1,
                measured_at=datetime(2026, 9, 18, 12, 37, tzinfo=UTC),
                humidity=52.0,
                battery=100,
            ),
            {
                "device_id": "C271111EC0AB",
                "temperature": 26.1,
                "measured_at": "2026-09-18T12:37:00+00:00",
                "humidity": 52.0,
                "battery": 100,
            },
        ),
        (
            SwitchBotEvent(device_id="C271111EC0AB", temperature=26.1, measured_at=datetime(1970, 1, 1, tzinfo=UTC)),
            {
                "device_id": "C271111EC0AB",
                "temperature": 26.1,
                "measured_at": "1970-01-01T00:00:00+00:00",
                "humidity": None,
                "battery": None,
            },
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SwitchBotEvent
    tests: list[tuple[dict[str, Any], SwitchBotEvent]] = [
        (
            {
                "device_id": "C271111EC0AB",
                "temperature": "26.1",
                "measured_at": "2026-09-18T12:37:00+00:00",
                "humidity": "52",
                "battery": "100",
            },
            SwitchBotEvent(
                device_id="C271111EC0AB",
                temperature=26.1,
                measured_at=datetime(2026, 9, 18, 12, 37, tzinfo=UTC),
                humidity=52.0,
                battery=100,
            ),
        ),
        (
            {},
            SwitchBotEvent(
                device_id="",
                temperature=0.0,
                measured_at=datetime(1970, 1, 1, tzinfo=UTC),
                humidity=None,
                battery=None,
            ),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
