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
    expected = ['label', 'unit', 'monthly', 'active']
    assert result == expected


def test___init__() -> None:
    tested = MeterUpdateRequest(label="EDF", unit="kWh", monthly=True, active=False)
    result = tested.model_dump()
    expected = {"label": "EDF", "unit": "kWh", "monthly": True, "active": False}
    assert result == expected

    tested = MeterUpdateRequest()
    result = tested.model_dump()
    expected = {"label": "", "unit": "", "monthly": False, "active": True}
    assert result == expected
