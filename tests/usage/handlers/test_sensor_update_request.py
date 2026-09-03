from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.sensor_update_request import SensorUpdateRequest


def test_inheritance() -> None:
    tested = SensorUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SensorUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ["name", "unit", "color", "active"]
    assert result == expected


def test___init__() -> None:
    tested = SensorUpdateRequest(name="Garage", unit="°F", color="#2a78d6", active=False)
    result = tested.model_dump()
    expected = {"name": "Garage", "unit": "°F", "color": "#2a78d6", "active": False}
    assert result == expected
