from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.user_update_request import UserUpdateRequest


def test_inheritance() -> None:
    tested = UserUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = UserUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ['name', 'is_admin']
    assert result == expected


def test___init__() -> None:
    tested = UserUpdateRequest(name="Jane", is_admin=True)
    result = tested.model_dump()
    expected = {"name": "Jane", "is_admin": True}
    assert result == expected

    tested = UserUpdateRequest()
    result = tested.model_dump()
    expected = {"name": "", "is_admin": False}
    assert result == expected
