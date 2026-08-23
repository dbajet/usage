from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reading_request import ReadingRequest
from usage.handlers.reading_value_input import ReadingValueInput


def test_inheritance() -> None:
    tested = ReadingRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ReadingRequest
    result = list(tested.model_fields.keys())
    expected = ["meter_id", "read_on", "source", "values"]
    assert result == expected


def test___init__() -> None:
    tested = ReadingRequest(
        meter_id=9,
        read_on="2026-01-15",
        source="photo",
        values=[ReadingValueInput(register_id=21, value=17273.0)],
    )
    result = tested.model_dump()
    expected = {
        "meter_id": 9,
        "read_on": "2026-01-15",
        "source": "photo",
        "values": [{"register_id": 21, "value": 17273.0}],
    }
    assert result == expected

    tested = ReadingRequest(meter_id=9, read_on="2026-01-15")
    result = tested.model_dump()
    expected = {"meter_id": 9, "read_on": "2026-01-15", "source": "manual", "values": []}
    assert result == expected
