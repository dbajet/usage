from __future__ import annotations

from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.auth_link_issue import AuthLinkIssue


def test_class() -> None:
    tested = AuthLinkIssue
    fields = ["link", "emailed"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[AuthLinkIssue, dict[str, str | bool]]] = [
        (
            AuthLinkIssue(link="https://usage.example.com/?login=theToken", emailed=True),
            {"link": "https://usage.example.com/?login=theToken", "emailed": True},
        ),
        (
            AuthLinkIssue(link="", emailed=False),
            {"link": "", "emailed": False},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = AuthLinkIssue
    tests: list[tuple[dict[str, Any], AuthLinkIssue]] = [
        (
            {"link": "https://usage.example.com/?login=theToken", "emailed": True},
            AuthLinkIssue(link="https://usage.example.com/?login=theToken", emailed=True),
        ),
        (
            {},
            AuthLinkIssue(link="", emailed=False),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
