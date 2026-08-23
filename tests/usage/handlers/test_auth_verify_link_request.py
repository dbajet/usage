from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.auth_verify_link_request import AuthVerifyLinkRequest


def test_inheritance() -> None:
    tested = AuthVerifyLinkRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = AuthVerifyLinkRequest
    result = list(tested.model_fields.keys())
    expected = ["token"]
    assert result == expected


def test___init__() -> None:
    tested = AuthVerifyLinkRequest(token="theToken")
    result = tested.model_dump()
    expected = {"token": "theToken"}
    assert result == expected
