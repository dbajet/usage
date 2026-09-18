from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from usage.libraries.series_zone import SeriesZone
from usage.structures.app_exception import AppException

SQL_HOUSE = "SELECT timezone FROM houses WHERE id = %s"


def helper_instance() -> SeriesZone:
    return SeriesZone(MagicMock())


def test___init__() -> None:
    database = MagicMock()
    tested = SeriesZone(database)
    assert tested._database is database


def test_of() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # what the page asked for, and the house is never troubled about it
    tests: list[str] = ["America/Los_Angeles", "  Europe/Paris  "]
    for wanted in tests:
        result = tested.of(wanted, 3)
        assert result == wanted.strip()
        assert database.mock_calls == []
        reset_mocks()

    # a page that says nothing, or one that says something that is not a zone
    for wanted in ("", "Middle/Earth"):
        database.fetch_one.side_effect = [{"timezone": "Europe/Paris"}]
        result = tested.of(wanted, 3)
        expected = "Europe/Paris"
        assert result == expected
        assert database.mock_calls == [call.fetch_one(SQL_HOUSE, (3,))]
        reset_mocks()

    # a house that is gone, or one whose own zone is no longer a zone
    tests_rows: list[dict[str, str] | None] = [None, {"timezone": ""}, {"timezone": "Middle/Earth"}]
    for row in tests_rows:
        database.fetch_one.side_effect = [row]
        with pytest.raises(AppException) as exc_info:
            tested.of("Middle/Earth", 3)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "Neither Middle/Earth nor the house's own zone is one this server knows."
        assert database.mock_calls == [call.fetch_one(SQL_HOUSE, (3,))]
        reset_mocks()


def test_known() -> None:
    tested = helper_instance()
    tests: list[tuple[str, bool]] = [
        ("Europe/Paris", True),
        ("America/Los_Angeles", True),
        ("UTC", True),
        ("Middle/Earth", False),
        ("", False),
        ("   ", False),
    ]
    for name, expected in tests:
        result = tested.known(name)
        assert result is expected
