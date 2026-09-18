from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.switch_bot_reading import SwitchBotReading


def test_class() -> None:
    tested = SwitchBotReading
    fields = ["device_id", "temperature", "humidity", "battery"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SwitchBotReading, dict[str, Any]]] = [
        (
            SwitchBotReading(device_id="C271111EC0AB", temperature=26.1, humidity=52.0, battery=87),
            {"device_id": "C271111EC0AB", "temperature": 26.1, "humidity": 52.0, "battery": 87},
        ),
        (
            SwitchBotReading(device_id="C271111EC0AB", temperature=26.1),
            {"device_id": "C271111EC0AB", "temperature": 26.1, "humidity": None, "battery": None},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SwitchBotReading
    tests: list[tuple[dict[str, Any], SwitchBotReading]] = [
        (
            {"device_id": "C271111EC0AB", "temperature": "26.1", "humidity": "52", "battery": "87"},
            SwitchBotReading(device_id="C271111EC0AB", temperature=26.1, humidity=52.0, battery=87),
        ),
        ({}, SwitchBotReading(device_id="", temperature=0.0, humidity=None, battery=None)),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
