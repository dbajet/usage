from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.meter_update_request import MeterUpdateRequest


def test_inheritance() -> None:
    tested = MeterUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = MeterUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ['label', 'unit', 'active']
    assert result == expected


def test___init__() -> None:
    tested = MeterUpdateRequest(label="EDF", unit="kWh", active=False)
    result = tested.model_dump()
    expected = {"label": "EDF", "unit": "kWh", "active": False}
    assert result == expected

    tested = MeterUpdateRequest()
    result = tested.model_dump()
    expected = {"label": "", "unit": "", "active": True}
    assert result == expected
