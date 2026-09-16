from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.enphase_feed import EnphaseFeed


def helper_feed() -> EnphaseFeed:
    return EnphaseFeed(
        feed_id=11,
        house_id=3,
        client_id="theClientId",
        client_secret="theClientSecret",
        api_key="theApiKey",
        system_id="3456789",
        access_token="theAccessToken",
        refresh_token="theRefreshToken",
        token_expires_at=datetime(2026, 9, 17, 7, 14, tzinfo=UTC),
        active=True,
        backfill_from=date(2026, 9, 16),
        backfill_done=True,
        fine_from=date(2026, 9, 10),
        fine_done=False,
        calls_used=123,
        calls_budget=1000,
        calls_month=date(2026, 9, 1),
        production_path="micro",
        last_point_at=datetime(2026, 9, 16, 7, 15, tzinfo=UTC),
    )


def test_class() -> None:
    tested = EnphaseFeed
    fields = [
        "feed_id",
        "house_id",
        "client_id",
        "client_secret",
        "api_key",
        "system_id",
        "access_token",
        "refresh_token",
        "token_expires_at",
        "active",
        "backfill_from",
        "backfill_done",
        "fine_from",
        "fine_done",
        "calls_used",
        "calls_budget",
        "calls_month",
        "production_path",
        "last_point_at",
    ]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[EnphaseFeed, dict[str, Any]]] = [
        (
            helper_feed(),
            {
                "feed_id": 11,
                "house_id": 3,
                "client_id": "theClientId",
                "client_secret": "theClientSecret",
                "api_key": "theApiKey",
                "system_id": "3456789",
                "access_token": "theAccessToken",
                "refresh_token": "theRefreshToken",
                "token_expires_at": "2026-09-17T07:14:00+00:00",
                "active": True,
                "backfill_from": "2026-09-16",
                "backfill_done": True,
                "fine_from": "2026-09-10",
                "fine_done": False,
                "calls_used": 123,
                "calls_budget": 1000,
                "calls_month": "2026-09-01",
                "production_path": "micro",
                "last_point_at": "2026-09-16T07:15:00+00:00",
            },
        ),
        (
            EnphaseFeed(
                feed_id=11,
                house_id=3,
                client_id="theClientId",
                client_secret="theClientSecret",
                api_key="theApiKey",
                system_id="3456789",
            ),
            {
                "feed_id": 11,
                "house_id": 3,
                "client_id": "theClientId",
                "client_secret": "theClientSecret",
                "api_key": "theApiKey",
                "system_id": "3456789",
                "access_token": "",
                "refresh_token": "",
                "token_expires_at": "",
                "active": True,
                "backfill_from": "",
                "backfill_done": False,
                "fine_from": "",
                "fine_done": False,
                "calls_used": 0,
                "calls_budget": 0,
                "calls_month": "",
                "production_path": "",
                "last_point_at": "",
            },
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = EnphaseFeed
    tests: list[tuple[dict[str, Any], EnphaseFeed]] = [
        (helper_feed().to_dict(), helper_feed()),
        (
            {},
            EnphaseFeed(
                feed_id=0,
                house_id=0,
                client_id="",
                client_secret="",
                api_key="",
                system_id="",
                access_token="",
                refresh_token="",
                token_expires_at=None,
                active=False,
                backfill_from=None,
                backfill_done=False,
                fine_from=None,
                fine_done=False,
                calls_used=0,
                calls_budget=0,
                calls_month=None,
                production_path="",
                last_point_at=None,
            ),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
