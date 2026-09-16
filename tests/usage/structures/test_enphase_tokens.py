from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.enphase_tokens import EnphaseTokens


def test_class() -> None:
    tested = EnphaseTokens
    fields = ["access_token", "refresh_token", "expires_at"]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[EnphaseTokens, dict[str, str]]] = [
        (
            EnphaseTokens(
                access_token="theAccessToken",
                refresh_token="theRefreshToken",
                expires_at=datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
            ),
            {
                "access_token": "theAccessToken",
                "refresh_token": "theRefreshToken",
                "expires_at": "2026-09-16T07:14:00+00:00",
            },
        ),
        (
            EnphaseTokens(access_token="theAccessToken", refresh_token="theRefreshToken"),
            {"access_token": "theAccessToken", "refresh_token": "theRefreshToken", "expires_at": ""},
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = EnphaseTokens
    tests: list[tuple[dict[str, Any], EnphaseTokens]] = [
        (
            {
                "access_token": "theAccessToken",
                "refresh_token": "theRefreshToken",
                "expires_at": "2026-09-16T07:14:00+00:00",
            },
            EnphaseTokens(
                access_token="theAccessToken",
                refresh_token="theRefreshToken",
                expires_at=datetime(2026, 9, 16, 7, 14, tzinfo=UTC),
            ),
        ),
        ({}, EnphaseTokens(access_token="", refresh_token="", expires_at=None)),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
