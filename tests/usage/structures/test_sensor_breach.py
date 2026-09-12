from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.sensor_breach import SensorBreach


def test_class() -> None:
    tested = SensorBreach
    fields = ["sensor_id", "name", "value", "unit", "state", "threshold"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SensorBreach, dict[str, Any]]] = [
        (
            SensorBreach(sensor_id=3, name="Freezer", value=12.5, unit="°F", state="above", threshold=10.0),
            {"sensor_id": 3, "name": "Freezer", "value": 12.5, "unit": "°F", "state": "above", "threshold": 10.0},
        ),
        (
            SensorBreach(sensor_id=0, name="", value=0.0, unit="", state="", threshold=0.0),
            {"sensor_id": 0, "name": "", "value": 0.0, "unit": "", "state": "", "threshold": 0.0},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SensorBreach
    tests: list[tuple[dict[str, Any], SensorBreach]] = [
        (
            {"sensor_id": 3, "name": "Freezer", "value": 12.5, "unit": "°F", "state": "above", "threshold": 10.0},
            SensorBreach(sensor_id=3, name="Freezer", value=12.5, unit="°F", state="above", threshold=10.0),
        ),
        (
            {},
            SensorBreach(sensor_id=0, name="", value=0.0, unit="", state="", threshold=0.0),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
