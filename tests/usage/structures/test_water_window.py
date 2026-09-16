from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.water_window import WaterWindow


def test_class() -> None:
    tested = WaterWindow
    fields = ["feed_id", "readings", "hours", "smallest", "total"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[WaterWindow, dict[str, Any]]] = [
        (
            WaterWindow(feed_id=11, readings=96, hours=23.8, smallest=0.003, total=0.412),
            {"feed_id": 11, "readings": 96, "hours": 23.8, "smallest": 0.003, "total": 0.412},
        ),
        (
            WaterWindow(feed_id=0, readings=0, hours=0.0, smallest=0.0, total=0.0),
            {"feed_id": 0, "readings": 0, "hours": 0.0, "smallest": 0.0, "total": 0.0},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = WaterWindow
    tests: list[tuple[dict[str, Any], WaterWindow]] = [
        (
            {"feed_id": "11", "readings": "96", "hours": "23.8", "smallest": "0.003", "total": "0.412"},
            WaterWindow(feed_id=11, readings=96, hours=23.8, smallest=0.003, total=0.412),
        ),
        ({}, WaterWindow(feed_id=0, readings=0, hours=0.0, smallest=0.0, total=0.0)),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
