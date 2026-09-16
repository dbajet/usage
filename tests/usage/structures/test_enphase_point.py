from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.enphase_point import EnphasePoint


def test_class() -> None:
    tested = EnphasePoint
    fields = ["measured_at", "span_minutes", "production", "consumption", "battery_level"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[EnphasePoint, dict[str, Any]]] = [
        (
            EnphasePoint(
                measured_at=datetime(2026, 9, 16, 7, 15, tzinfo=UTC),
                span_minutes=15,
                production=0.412,
                consumption=0.233,
                battery_level=87.5,
            ),
            {
                "measured_at": "2026-09-16T07:15:00+00:00",
                "span_minutes": 15,
                "production": 0.412,
                "consumption": 0.233,
                "battery_level": 87.5,
            },
        ),
        (
            EnphasePoint(measured_at=datetime(1970, 1, 1, tzinfo=UTC)),
            {
                "measured_at": "1970-01-01T00:00:00+00:00",
                "span_minutes": 15,
                "production": None,
                "consumption": None,
                "battery_level": None,
            },
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = EnphasePoint
    tests: list[tuple[dict[str, Any], EnphasePoint]] = [
        (
            {
                "measured_at": "2026-09-16T07:15:00+00:00",
                "span_minutes": "15",
                "production": "0.412",
                "consumption": "0.233",
                "battery_level": "87.5",
            },
            EnphasePoint(
                measured_at=datetime(2026, 9, 16, 7, 15, tzinfo=UTC),
                span_minutes=15,
                production=0.412,
                consumption=0.233,
                battery_level=87.5,
            ),
        ),
        (
            {},
            EnphasePoint(
                measured_at=datetime(1970, 1, 1, tzinfo=UTC),
                span_minutes=0,
                production=None,
                consumption=None,
                battery_level=None,
            ),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
