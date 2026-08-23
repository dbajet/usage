from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.user_house_request import UserHouseRequest


def test_inheritance() -> None:
    tested = UserHouseRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = UserHouseRequest
    result = list(tested.model_fields.keys())
    expected = ['user_id', 'house_id', 'linked']
    assert result == expected


def test___init__() -> None:
    tested = UserHouseRequest(user_id=9, house_id=3, linked=True)
    result = tested.model_dump()
    expected = {"user_id": 9, "house_id": 3, "linked": True}
    assert result == expected
