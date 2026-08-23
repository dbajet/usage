from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.user_request import UserRequest


def test_inheritance() -> None:
    tested = UserRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = UserRequest
    result = list(tested.model_fields.keys())
    expected = ['email', 'name', 'is_admin']
    assert result == expected


def test___init__() -> None:
    tested = UserRequest(email="jane@example.com", name="Jane", is_admin=True)
    result = tested.model_dump()
    expected = {"email": "jane@example.com", "name": "Jane", "is_admin": True}
    assert result == expected

    tested = UserRequest(email="jane@example.com")
    result = tested.model_dump()
    expected = {"email": "jane@example.com", "name": "", "is_admin": False}
    assert result == expected
