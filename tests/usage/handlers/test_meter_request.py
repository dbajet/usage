from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.meter_request import MeterRequest
from usage.handlers.register_input import RegisterInput


def test_inheritance() -> None:
    tested = MeterRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = MeterRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "kind", "label", "unit", "monthly", "registers"]
    assert result == expected


def test___init__() -> None:
    tested = MeterRequest(
        house_id=3,
        kind="electricity",
        label="EDF",
        unit="kWh",
        monthly=True,
        registers=[RegisterInput(label="HC", initial_value=100.0), RegisterInput(label="HP", initial_value=200.0)],
    )
    result = tested.model_dump()
    expected = {
        "house_id": 3,
        "kind": "electricity",
        "label": "EDF",
        "unit": "kWh",
        "monthly": True,
        "registers": [
            {"label": "HC", "initial_value": 100.0},
            {"label": "HP", "initial_value": 200.0},
        ],
    }
    assert result == expected

    tested = MeterRequest(house_id=3, kind="water")
    result = tested.model_dump()
    expected = {"house_id": 3, "kind": "water", "label": "", "unit": "", "monthly": False, "registers": []}
    assert result == expected
