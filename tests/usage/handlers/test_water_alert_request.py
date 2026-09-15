from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.water_alert_request import WaterAlertRequest


def test_inheritance() -> None:
    tested = WaterAlertRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = WaterAlertRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "enabled"]
    assert result == expected


def test___init__() -> None:
    tested = WaterAlertRequest(house_id=3, enabled=True)
    result = tested.model_dump()
    expected = {"house_id": 3, "enabled": True}
    assert result == expected

    tested = WaterAlertRequest(house_id=3)
    result = tested.model_dump()
    expected = {"house_id": 3, "enabled": False}
    assert result == expected
