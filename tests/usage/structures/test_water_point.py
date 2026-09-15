from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.water_point import WaterPoint


def test_class() -> None:
    tested = WaterPoint
    fields = ["measured_at", "volume", "reading", "method"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[WaterPoint, dict[str, str | float | None]]] = [
        (
            WaterPoint(
                measured_at=datetime(2026, 9, 14, 7, 14, tzinfo=UTC),
                volume=0.0034,
                reading=515.6251,
                method="Network",
            ),
            {
                "measured_at": "2026-09-14T07:14:00+00:00",
                "volume": 0.0034,
                "reading": 515.6251,
                "method": "Network",
            },
        ),
        (
            WaterPoint(measured_at=datetime(1970, 1, 1, tzinfo=UTC), volume=0.0),
            {"measured_at": "1970-01-01T00:00:00+00:00", "volume": 0.0, "reading": None, "method": ""},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = WaterPoint
    tests: list[tuple[dict[str, Any], WaterPoint]] = [
        (
            {
                "measured_at": "2026-09-14T07:14:00+00:00",
                "volume": "0.0034",
                "reading": "515.6251",
                "method": "Network",
            },
            WaterPoint(
                measured_at=datetime(2026, 9, 14, 7, 14, tzinfo=UTC),
                volume=0.0034,
                reading=515.6251,
                method="Network",
            ),
        ),
        ({}, WaterPoint(measured_at=datetime(1970, 1, 1, tzinfo=UTC), volume=0.0, reading=None, method="")),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
