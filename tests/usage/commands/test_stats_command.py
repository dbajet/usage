from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.stats_command import StatsCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


def helper_instance() -> StatsCommand:
    return StatsCommand(MagicMock())


def helper_user(is_admin: bool = False) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = StatsCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch.object(StatsCommand, "_house_consumption")
@patch.object(StatsCommand, "_require_house")
def test_tables(require_house: MagicMock, house_consumption: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        house_consumption.reset_mock()
        database.reset_mock()

    user = helper_user()
    meters = [
        {"id": 1, "kind": "electricity", "label": "EDF", "unit": "kWh"},
        {"id": 2, "kind": "electricity", "label": "Old EDF", "unit": ""},
        {"id": 3, "kind": "water", "label": "Water", "unit": "m3"},
        {"id": 4, "kind": "gas", "label": "GDF", "unit": "m3"},
    ]
    # 24311 is December 2025, 24312 is January 2026 (year * 12 + month - 1)
    consumption = {
        1: {24312: 254.0},
        2: {24311: 206.0, 24312: 100.0},
        3: {24312: 7.0},
    }
    require_house.side_effect = [None]
    house_consumption.side_effect = [(meters, consumption)]
    result = tested.tables(user, 3)
    # The kinds appear in the order of the user's meters: electricity first here.
    expected = {
        "kinds": [
            {
                "kind": "electricity",
                "unit": "kWh",
                "years": [
                    {
                        "year": 2025,
                        "months": [None, None, None, None, None, None, None, None, None, None, None, 206.0],
                        "total": 206.0,
                    },
                    {
                        "year": 2026,
                        "months": [354.0, None, None, None, None, None, None, None, None, None, None, None],
                        "total": 354.0,
                    },
                ],
            },
            {
                "kind": "water",
                "unit": "m3",
                "years": [
                    {
                        "year": 2026,
                        "months": [7.0, None, None, None, None, None, None, None, None, None, None, None],
                        "total": 7.0,
                    },
                ],
            },
        ],
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    assert house_consumption.mock_calls == [call(user, 3)]
    assert database.mock_calls == []
    reset_mocks()


@patch.object(StatsCommand, "_house_consumption")
@patch.object(StatsCommand, "_require_house")
def test_series(require_house: MagicMock, house_consumption: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        house_consumption.reset_mock()
        database.reset_mock()

    user = helper_user()
    meters = [
        {"id": 1, "kind": "electricity", "label": "EDF", "unit": "kWh", "color": "", "axis": ""},
        {"id": 3, "kind": "water", "label": "", "unit": "m3", "color": "#189aa8", "axis": "right"},
        {"id": 4, "kind": "gas", "label": "GDF", "unit": "m3", "color": "", "axis": ""},
    ]
    consumption = {
        1: {24312: 254.0, 24311: 206.0},
        3: {24312: 7.005},
    }
    require_house.side_effect = [None]
    house_consumption.side_effect = [(meters, consumption)]
    result = tested.series(user, 3)
    expected = {
        "series": [
            {
                "meter_id": 1,
                "label": "EDF",
                "kind": "electricity",
                "unit": "kWh",
                "color": "",
                "axis": "",
                "points": [
                    {"month": "2025-12", "value": 206.0},
                    {"month": "2026-01", "value": 254.0},
                ],
            },
            {
                "meter_id": 3,
                "label": "water",
                "kind": "water",
                "unit": "m3",
                "color": "#189aa8",
                "axis": "right",
                "points": [{"month": "2026-01", "value": 7.0}],
            },
        ],
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    assert house_consumption.mock_calls == [call(user, 3)]
    assert database.mock_calls == []
    reset_mocks()


@patch.object(StatsCommand, "_register_consumption")
def test__house_consumption(register_consumption: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        register_consumption.reset_mock()
        database.reset_mock()

    meter_rows = [{"id": 1, "kind": "electricity", "label": "sealedEDF", "unit": "kWh"}]
    register_rows = [
        {"id": 21, "meter_id": 1, "initial_value": 17273},
        {"id": 22, "meter_id": 1, "initial_value": 158},
    ]
    reading_rows = [
        {"meter_id": 1, "read_on": "2026-01-15", "register_id": 21, "value": 17273},
        {"meter_id": 1, "read_on": "2026-01-15", "register_id": 22, "value": 158},
        {"meter_id": 1, "read_on": "2026-02-15", "register_id": 21, "value": 17273},
        {"meter_id": 1, "read_on": "2026-02-15", "register_id": 22, "value": 291},
    ]
    database.fetch_all.side_effect = [meter_rows, register_rows, reading_rows]
    database.decrypt_rows.side_effect = [[{"id": 1, "kind": "electricity", "label": "EDF", "unit": "kWh", "color": "", "axis": ""}]]
    register_consumption.side_effect = [
        {24312: 0.0, 24313: 0.0},
        {24312: 0.0, 24313: 133.0},
    ]
    result = tested._house_consumption(helper_user(), 3)
    expected = (
        [{"id": 1, "kind": "electricity", "label": "EDF", "unit": "kWh", "color": "", "axis": ""}],
        {1: {24312: 0.0, 24313: 133.0}},
    )
    assert result == expected
    exp_calls = [
        call(17273.0, [(24312, 17273.0), (24313, 17273.0)]),
        call(158.0, [(24312, 158.0), (24313, 291.0)]),
    ]
    assert register_consumption.mock_calls == exp_calls
    exp_calls = [
        call.fetch_all(
            """
                SELECT meters.id, meters.kind, meters.label_sealed AS label, meters.unit,
                       COALESCE(meter_orders.color, '') AS color,
                       COALESCE(meter_orders.axis, '') AS axis
                FROM meters
                LEFT JOIN meter_orders ON meter_orders.meter_id = meters.id AND meter_orders.user_id = %s
                WHERE meters.house_id = %s
                ORDER BY COALESCE(meter_orders.position, meters.position), meters.position, meters.id
                """,
            (7, 3),
        ),
        call.decrypt_rows(meter_rows, ("label",)),
        call.fetch_all(
            """
            SELECT registers.id, registers.meter_id, registers.initial_value
            FROM registers JOIN meters ON meters.id = registers.meter_id
            WHERE meters.house_id = %s ORDER BY registers.id
            """,
            (3,),
        ),
        call.fetch_all(
            """
            SELECT readings.meter_id, readings.read_on, reading_values.register_id, reading_values.value
            FROM readings JOIN reading_values ON reading_values.reading_id = readings.id
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            ORDER BY readings.read_on, readings.id
            """,
            (3,),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__register_consumption() -> None:
    tested = StatsCommand
    # month indexes: Aug-2024 = 24295, Sep-2024 = 24296, ...
    tests: list[tuple[float, list[tuple[int, float]], dict[int, float]]] = [
        # no reading at all
        (0.0, [], {}),
        # the spreadsheet's EDF counter: 13443 (Aug-24), 13708 (Sep-24), 13963 (Oct-24)
        # with the July counter 13179 as the register baseline -> 264, 265, 255
        (
            13179.0,
            [(24295, 13443.0), (24296, 13708.0), (24297, 13963.0)],
            {24295: 264.0, 24296: 265.0, 24297: 255.0},
        ),
        # a skipped month spreads the delta evenly: Jan 100, Apr 160 -> 20 for Feb, Mar, Apr
        (
            100.0,
            [(24312, 100.0), (24315, 160.0)],
            {24312: 0.0, 24313: 20.0, 24314: 20.0, 24315: 20.0},
        ),
        # two readings in the same month land in that month
        (
            0.0,
            [(24312, 10.0), (24312, 15.0)],
            {24312: 15.0},
        ),
    ]
    for initial_value, points, expected in tests:
        result = tested._register_consumption(initial_value, points)
        assert result == expected, f"---> {points}"


def test__years() -> None:
    tested = StatsCommand
    # water sheet row 2024: readings across the year with a yearly total
    merged = {24299: 5.0, 24300: 2.0, 24290: 4.0}
    result = tested._years(merged)
    expected = [
        {
            "year": 2024,
            "months": [None, None, 4.0, None, None, None, None, None, None, None, None, 5.0],
            "total": 9.0,
        },
        {
            "year": 2025,
            "months": [2.0, None, None, None, None, None, None, None, None, None, None, None],
            "total": 2.0,
        },
    ]
    assert result == expected


def test__month_index() -> None:
    tested = StatsCommand
    tests = [
        ("2024-08-15", 24295),
        ("2026-01-01", 24312),
        ("2026-12-31", 24323),
    ]
    for read_on, expected in tests:
        result = tested._month_index(read_on)
        assert result == expected, f"---> {read_on}"


def test__month_key() -> None:
    tested = StatsCommand
    tests = [
        (24295, "2024-08"),
        (24312, "2026-01"),
        (24323, "2026-12"),
    ]
    for index, expected in tests:
        result = tested._month_key(index)
        assert result == expected, f"---> {index}"


def test__visible_house_ids() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # everyone, admins included, only sees the linked houses
    for is_admin in (True, False):
        database.fetch_all.side_effect = [[{"house_id": 2}]]
        result = tested._visible_house_ids(helper_user(is_admin=is_admin))
        expected = [2]
        assert result == expected, f"---> {is_admin}"
        exp_calls = [call.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (7,))]
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch.object(StatsCommand, "_visible_house_ids")
def test__require_house(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one("SELECT id FROM houses WHERE id = %s", (1,))

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 1)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # no access
    database.fetch_one.side_effect = [{"id": 1}]
    visible_house_ids.side_effect = [[2]]
    with pytest.raises(AppException) as exc_info:
        tested._require_house(user, 1)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 1}]
    visible_house_ids.side_effect = [[1]]
    result = tested._require_house(user, 1)
    assert result is None
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()
