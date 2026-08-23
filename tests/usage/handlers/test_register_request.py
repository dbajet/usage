from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.register_request import RegisterRequest


def test_inheritance() -> None:
    tested = RegisterRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = RegisterRequest
    result = list(tested.model_fields.keys())
    expected = ['label', 'initial_value']
    assert result == expected


def test___init__() -> None:
    tested = RegisterRequest(label="HP", initial_value=100.0)
    result = tested.model_dump()
    expected = {"label": "HP", "initial_value": 100.0}
    assert result == expected

    tested = RegisterRequest()
    result = tested.model_dump()
    expected = {"label": "", "initial_value": 0.0}
    assert result == expected
