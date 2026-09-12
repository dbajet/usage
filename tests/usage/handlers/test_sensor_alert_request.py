from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.sensor_alert_request import SensorAlertRequest


def test_inheritance() -> None:
    tested = SensorAlertRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = SensorAlertRequest
    result = list(tested.model_fields.keys())
    expected = ["house_id", "enabled"]
    assert result == expected


def test___init__() -> None:
    tested = SensorAlertRequest(house_id=4, enabled=True)
    result = tested.model_dump()
    expected = {"house_id": 4, "enabled": True}
    assert result == expected
