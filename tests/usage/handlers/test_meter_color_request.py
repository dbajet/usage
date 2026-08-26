from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.meter_color_request import MeterColorRequest


def test_inheritance() -> None:
    tested = MeterColorRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = MeterColorRequest
    result = list(tested.model_fields.keys())
    expected = ["meter_id", "color"]
    assert result == expected


def test___init__() -> None:
    tested = MeterColorRequest(meter_id=9, color="#2a78d6")
    result = tested.model_dump()
    expected = {"meter_id": 9, "color": "#2a78d6"}
    assert result == expected

    tested = MeterColorRequest(meter_id=9)
    result = tested.model_dump()
    expected = {"meter_id": 9, "color": ""}
    assert result == expected
