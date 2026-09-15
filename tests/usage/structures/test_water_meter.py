from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.water_meter import WaterMeter


def test_class() -> None:
    tested = WaterMeter
    fields = ["uuid", "meter_id", "timezone"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[WaterMeter, dict[str, str]]] = [
        (
            WaterMeter(uuid="1234567890123456789", meter_id="900112233", timezone="US/Pacific"),
            {"uuid": "1234567890123456789", "meter_id": "900112233", "timezone": "US/Pacific"},
        ),
        (WaterMeter(uuid="1234567890123456789"), {"uuid": "1234567890123456789", "meter_id": "", "timezone": ""}),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = WaterMeter
    tests: list[tuple[dict[str, Any], WaterMeter]] = [
        (
            {"uuid": "1234567890123456789", "meter_id": "900112233", "timezone": "US/Pacific"},
            WaterMeter(uuid="1234567890123456789", meter_id="900112233", timezone="US/Pacific"),
        ),
        ({}, WaterMeter(uuid="", meter_id="", timezone="")),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
