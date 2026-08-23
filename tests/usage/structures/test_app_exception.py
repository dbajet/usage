from __future__ import annotations

from usage.structures.app_exception import AppException


def test_inheritance() -> None:
    tested = AppException
    result = issubclass(tested, RuntimeError)
    assert result is True


def test___init__() -> None:
    tested = AppException(404, "not found")
    result = tested.status_code
    expected = 404
    assert result == expected
    result = tested.message
    exp_message = "not found"
    assert result == exp_message
    result = str(tested)
    assert result == exp_message
