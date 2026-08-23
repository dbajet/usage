from __future__ import annotations

from pydantic import BaseModel

from usage.handlers.reminder_request import ReminderRequest


def test_inheritance() -> None:
    tested = ReminderRequest
    result = issubclass(tested, BaseModel)
    assert result is True


def test_class() -> None:
    tested = ReminderRequest
    result = list(tested.model_fields.keys())
    expected = ["enabled"]
    assert result == expected


def test___init__() -> None:
    tested = ReminderRequest(enabled=True)
    result = tested.model_dump()
    expected = {"enabled": True}
    assert result == expected
