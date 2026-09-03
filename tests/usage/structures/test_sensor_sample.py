from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.sensor_sample import SensorSample


def test_class() -> None:
    tested = SensorSample
    fields = ["entity_id", "name", "unit", "value", "measured_at"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SensorSample, dict[str, str | float]]] = [
        (
            SensorSample(
                entity_id="sensor.garage_temperature",
                name="Garage",
                unit="°F",
                value=84.9,
                measured_at=datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC),
            ),
            {
                "entity_id": "sensor.garage_temperature",
                "name": "Garage",
                "unit": "°F",
                "value": 84.9,
                "measured_at": "2026-09-02T23:16:59+00:00",
            },
        ),
        (
            SensorSample(entity_id="", name="", unit="", value=0.0, measured_at=datetime(1970, 1, 1, tzinfo=UTC)),
            {"entity_id": "", "name": "", "unit": "", "value": 0.0, "measured_at": "1970-01-01T00:00:00+00:00"},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SensorSample
    tests: list[tuple[dict[str, Any], SensorSample]] = [
        (
            {
                "entity_id": "sensor.garage_temperature",
                "name": "Garage",
                "unit": "°F",
                "value": 84.9,
                "measured_at": "2026-09-02T23:16:59+00:00",
            },
            SensorSample(
                entity_id="sensor.garage_temperature",
                name="Garage",
                unit="°F",
                value=84.9,
                measured_at=datetime(2026, 9, 2, 23, 16, 59, tzinfo=UTC),
            ),
        ),
        (
            {},
            SensorSample(entity_id="", name="", unit="", value=0.0, measured_at=datetime(1970, 1, 1, tzinfo=UTC)),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
