from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.passkey_options_request import PasskeyOptionsRequest


def test_inheritance() -> None:
    tested = PasskeyOptionsRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = PasskeyOptionsRequest
    result = list(tested.model_fields.keys())
    expected = ["email"]
    assert result == expected


def test___init__() -> None:
    tested = PasskeyOptionsRequest(email="jane@example.com")
    result = tested.model_dump()
    expected = {"email": "jane@example.com"}
    assert result == expected
