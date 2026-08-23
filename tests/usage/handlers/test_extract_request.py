from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.extract_request import ExtractRequest


def test_inheritance() -> None:
    tested = ExtractRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ExtractRequest
    result = list(tested.model_fields.keys())
    expected = ["meter_id", "image_base64", "media_type", "register_id"]
    assert result == expected


def test___init__() -> None:
    tested = ExtractRequest(meter_id=9, image_base64="aGVsbG8=", media_type="image/jpeg")
    result = tested.model_dump()
    expected = {"meter_id": 9, "image_base64": "aGVsbG8=", "media_type": "image/jpeg", "register_id": 0}
    assert result == expected
