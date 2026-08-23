from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.register_input import RegisterInput


def test_inheritance() -> None:
    tested = RegisterInput
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = RegisterInput
    result = list(tested.model_fields.keys())
    expected = ['label', 'initial_value']
    assert result == expected


def test___init__() -> None:
    tested = RegisterInput(label="HC", initial_value=100.0)
    result = tested.model_dump()
    expected = {"label": "HC", "initial_value": 100.0}
    assert result == expected

    tested = RegisterInput()
    result = tested.model_dump()
    expected = {"label": "", "initial_value": 0.0}
    assert result == expected
