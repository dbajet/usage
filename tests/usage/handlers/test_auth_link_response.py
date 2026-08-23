from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.auth_link_response import AuthLinkResponse


def test_inheritance() -> None:
    tested = AuthLinkResponse
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = AuthLinkResponse
    result = list(tested.model_fields.keys())
    expected = ["message", "dev_link"]
    assert result == expected


def test___init__() -> None:
    tested = AuthLinkResponse(message="all good")
    result = tested.model_dump()
    expected = {"message": "all good", "dev_link": ""}
    assert result == expected

    tested = AuthLinkResponse(message="all good", dev_link="https://usage.example.com/?login=theToken")
    result = tested.model_dump()
    expected = {"message": "all good", "dev_link": "https://usage.example.com/?login=theToken"}
    assert result == expected
