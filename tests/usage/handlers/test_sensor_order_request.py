from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.sensor_order_request import SensorOrderRequest


def test_inheritance() -> None:
    tested = SensorOrderRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SensorOrderRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "sensor_ids"]
    assert result == expected


def test___init__() -> None:
    tested = SensorOrderRequest(house_id=3, sensor_ids=[9, 7])
    result = tested.model_dump()
    expected = {"house_id": 3, "sensor_ids": [9, 7]}
    assert result == expected
