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
    expected = ['name']
    assert result == expected


def test___init__() -> None:
    tested = HouseRequest(name="Fremur")
    result = tested.model_dump()
    expected = {"name": "Fremur"}
    assert result == expected
