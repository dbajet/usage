from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.meter_order_request import MeterOrderRequest


def test_inheritance() -> None:
    tested = MeterOrderRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = MeterOrderRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "meter_ids"]
    assert result == expected


def test___init__() -> None:
    tested = MeterOrderRequest(house_id=3, meter_ids=[9, 7, 8])
    result = tested.model_dump()
    expected = {"house_id": 3, "meter_ids": [9, 7, 8]}
    assert result == expected
