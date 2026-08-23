from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.auth_link_request import AuthLinkRequest


def test_inheritance() -> None:
    tested = AuthLinkRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = AuthLinkRequest
    result = list(tested.model_fields.keys())
    expected = ["email"]
    assert result == expected


def test___init__() -> None:
    tested = AuthLinkRequest(email="jane@example.com")
    result = tested.model_dump()
    expected = {"email": "jane@example.com"}
    assert result == expected
