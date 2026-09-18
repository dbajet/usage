from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.house_request import HouseRequest


def test_inheritance() -> None:
    tested = HouseRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = HouseRequest
    result = list(tested.model_fields.keys())
    expected = ['name', 'timezone', 'shows_sensors', 'shows_switchbot', 'shows_water', 'shows_power']
    assert result == expected


def test___init__() -> None:
    tested = HouseRequest(
        name="Fremur",
        timezone="Europe/Paris",
        shows_sensors=True,
        shows_switchbot=True,
        shows_water=True,
        shows_power=True,
    )
    result = tested.model_dump()
    expected = {
        "name": "Fremur",
        "timezone": "Europe/Paris",
        "shows_sensors": True,
        "shows_switchbot": True,
        "shows_water": True,
        "shows_power": True,
    }
    assert result == expected

    tested = HouseRequest(name="Fremur")
    result = tested.model_dump()
    expected = {
        "name": "Fremur",
        "timezone": "",
        "shows_sensors": False,
        "shows_switchbot": False,
        "shows_water": False,
        "shows_power": False,
    }
    assert result == expected
