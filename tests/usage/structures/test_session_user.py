from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.session_user import SessionUser


def test_class() -> None:
    tested = SessionUser
    fields = ["user_id", "email", "name", "is_admin"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[SessionUser, dict[str, int | str | bool]]] = [
        (
            SessionUser(user_id=7, email="jane@example.com", name="Jane Doe", is_admin=True),
            {"user_id": 7, "email": "jane@example.com", "name": "Jane Doe", "is_admin": True},
        ),
        (
            SessionUser(user_id=3, email="john@example.com", name="", is_admin=False),
            {"user_id": 3, "email": "john@example.com", "name": "", "is_admin": False},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = SessionUser
    tests: list[tuple[dict[str, Any], SessionUser]] = [
        (
            {"user_id": 7, "email": "jane@example.com", "name": "Jane Doe", "is_admin": True},
            SessionUser(user_id=7, email="jane@example.com", name="Jane Doe", is_admin=True),
        ),
        (
            {},
            SessionUser(user_id=0, email="", name="", is_admin=False),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
