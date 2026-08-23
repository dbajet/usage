from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reading_update_request import ReadingUpdateRequest
from usage.handlers.reading_value_input import ReadingValueInput


def test_inheritance() -> None:
    tested = ReadingUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ReadingUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ["read_on", "values"]
    assert result == expected


def test___init__() -> None:
    tested = ReadingUpdateRequest(read_on="2026-01-16", values=[ReadingValueInput(register_id=21, value=17300.0)])
    result = tested.model_dump()
    expected = {"read_on": "2026-01-16", "values": [{"register_id": 21, "value": 17300.0}]}
    assert result == expected

    tested = ReadingUpdateRequest(read_on="2026-01-16")
    result = tested.model_dump()
    expected = {"read_on": "2026-01-16", "values": []}
    assert result == expected
