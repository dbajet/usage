from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.api_message import ApiMessage


def test_inheritance() -> None:
    tested = ApiMessage
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ApiMessage
    result = list(tested.model_fields.keys())
    expected = ["message"]
    assert result == expected


def test___init__() -> None:
    tested = ApiMessage(message="all good")
    result = tested.model_dump()
    expected = {"message": "all good"}
    assert result == expected
