from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.sample_input import SampleInput


def test_inheritance() -> None:
    tested = SampleInput
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SampleInput
    result = list(tested.model_fields.keys())
    expected = ["entity_id", "value", "name", "unit", "measured_at"]
    assert result == expected


def test___init__() -> None:
    tested = SampleInput(entity_id="sensor.garage_temperature", value=84.9)
    result = tested.model_dump()
    expected = {"entity_id": "sensor.garage_temperature", "value": 84.9, "name": "", "unit": "", "measured_at": ""}
    assert result == expected
