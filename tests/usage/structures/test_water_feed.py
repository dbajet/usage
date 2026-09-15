from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from tests.conftest import is_namedtuple
from usage.structures.water_feed import WaterFeed


def helper_instance() -> WaterFeed:
    return WaterFeed(
        feed_id=7,
        house_id=1,
        hostname="eyeonwater.com",
        username="theUsername",
        password="thePassword",
        meter_uuid="1234567890123456789",
        export_unit="Gallons",
        active=True,
        backfill_from=date(2021, 4, 1),
        backfill_done=False,
        empty_chunks=1,
        last_point_at=datetime(2026, 9, 14, 7, 14, tzinfo=UTC),
    )


def test_class() -> None:
    tested = WaterFeed
    fields = [
        "feed_id",
        "house_id",
        "hostname",
        "username",
        "password",
        "meter_uuid",
        "export_unit",
        "active",
        "backfill_from",
        "backfill_done",
        "empty_chunks",
        "last_point_at",
    ]
    result = is_namedtuple(tested, fields)
    assert result is True


def test_to_dict() -> None:
    tests: list[tuple[WaterFeed, dict[str, Any]]] = [
        (
            helper_instance(),
            {
                "feed_id": 7,
                "house_id": 1,
                "hostname": "eyeonwater.com",
                "username": "theUsername",
                "password": "thePassword",
                "meter_uuid": "1234567890123456789",
                "export_unit": "Gallons",
                "active": True,
                "backfill_from": "2021-04-01",
                "backfill_done": False,
                "empty_chunks": 1,
                "last_point_at": "2026-09-14T07:14:00+00:00",
            },
        ),
        (
            WaterFeed(
                feed_id=0,
                house_id=0,
                hostname="",
                username="",
                password="",
                meter_uuid="",
                export_unit="",
            ),
            {
                "feed_id": 0,
                "house_id": 0,
                "hostname": "",
                "username": "",
                "password": "",
                "meter_uuid": "",
                "export_unit": "",
                "active": True,
                "backfill_from": "",
                "backfill_done": False,
                "empty_chunks": 0,
                "last_point_at": "",
            },
        ),
    ]
    for tested, expected in tests:
        result = tested.to_dict()
        assert result == expected


def test_from_dict() -> None:
    tested = WaterFeed
    tests: list[tuple[dict[str, Any], WaterFeed]] = [
        (
            {
                "feed_id": "7",
                "house_id": "1",
                "hostname": "eyeonwater.com",
                "username": "theUsername",
                "password": "thePassword",
                "meter_uuid": "1234567890123456789",
                "export_unit": "Gallons",
                "active": True,
                "backfill_from": "2021-04-01",
                "backfill_done": False,
                "empty_chunks": "1",
                "last_point_at": "2026-09-14T07:14:00+00:00",
            },
            helper_instance(),
        ),
        (
            {},
            WaterFeed(
                feed_id=0,
                house_id=0,
                hostname="",
                username="",
                password="",
                meter_uuid="",
                export_unit="",
                active=False,
                backfill_from=None,
                backfill_done=False,
                empty_chunks=0,
                last_point_at=None,
            ),
        ),
    ]
    for data, expected in tests:
        result = tested.from_dict(data)
        assert result == expected
