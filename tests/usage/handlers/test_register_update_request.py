from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.register_update_request import RegisterUpdateRequest


def test_inheritance() -> None:
    tested = RegisterUpdateRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = RegisterUpdateRequest
    result = list(tested.model_fields.keys())
    expected = ['label', 'initial_value', 'active']
    assert result == expected


def test___init__() -> None:
    tested = RegisterUpdateRequest(label="HP", initial_value=100.0, active=False)
    result = tested.model_dump()
    expected = {"label": "HP", "initial_value": 100.0, "active": False}
    assert result == expected

    tested = RegisterUpdateRequest()
    result = tested.model_dump()
    expected = {"label": "", "initial_value": 0.0, "active": True}
    assert result == expected
