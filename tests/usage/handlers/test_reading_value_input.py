from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reading_value_input import ReadingValueInput


def test_inheritance() -> None:
    tested = ReadingValueInput
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ReadingValueInput
    result = list(tested.model_fields.keys())
    expected = ["register_id", "value"]
    assert result == expected


def test___init__() -> None:
    tested = ReadingValueInput(register_id=21, value=17273.0)
    result = tested.model_dump()
    expected = {"register_id": 21, "value": 17273.0}
    assert result == expected
