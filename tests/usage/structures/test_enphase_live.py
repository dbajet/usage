from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.enphase_live import EnphaseLive


def test_class() -> None:
    tested = EnphaseLive
    fields = [
        "house_id",
        "measured_at",
        "production_power",
        "consumption_power",
        "battery_level",
        "production_lifetime",
        "consumption_lifetime",
    ]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[EnphaseLive, dict[str, Any]]] = [
        (
            EnphaseLive(
                house_id=3,
                measured_at=datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
                production_power=600.0,
                consumption_power=360.0,
                battery_level=82.0,
                production_lifetime=1_000_000.0,
                consumption_lifetime=2_000_000.0,
            ),
            {
                "house_id": 3,
                "measured_at": "2026-09-16T07:14:00+00:00",
                "production_power": 600.0,
                "consumption_power": 360.0,
                "battery_level": 82.0,
                "production_lifetime": 1_000_000.0,
                "consumption_lifetime": 2_000_000.0,
            },
        ),
        (
            EnphaseLive(house_id=3, measured_at=datetime(1970, 1, 1, tzinfo=UTC)),
            {
                "house_id": 3,
                "measured_at": "1970-01-01T00:00:00+00:00",
                "production_power": None,
                "consumption_power": None,
                "battery_level": None,
                "production_lifetime": None,
                "consumption_lifetime": None,
            },
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = EnphaseLive
    tests: list[tuple[dict[str, Any], EnphaseLive]] = [
        (
            {
                "house_id": "3",
                "measured_at": "2026-09-16T07:14:00+00:00",
                "production_power": "600",
                "consumption_power": "360",
                "battery_level": "82",
                "production_lifetime": "1000000",
                "consumption_lifetime": "2000000",
            },
            EnphaseLive(
                house_id=3,
                measured_at=datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
                production_power=600.0,
                consumption_power=360.0,
                battery_level=82.0,
                production_lifetime=1_000_000.0,
                consumption_lifetime=2_000_000.0,
            ),
        ),
        ({}, EnphaseLive(house_id=0, measured_at=datetime(1970, 1, 1, tzinfo=UTC))),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
