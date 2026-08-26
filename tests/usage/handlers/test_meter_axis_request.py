from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.meter_axis_request import MeterAxisRequest


def test_inheritance() -> None:
    tested = MeterAxisRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = MeterAxisRequest
    result = list(tested.model_fields.keys())
    expected = ["meter_id", "axis"]
    assert result == expected


def test___init__() -> None:
    tested = MeterAxisRequest(meter_id=9, axis="right")
    result = tested.model_dump()
    expected = {"meter_id": 9, "axis": "right"}
    assert result == expected

    tested = MeterAxisRequest(meter_id=9)
    result = tested.model_dump()
    expected = {"meter_id": 9, "axis": ""}
    assert result == expected
