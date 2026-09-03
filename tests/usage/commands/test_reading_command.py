from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.reading_command import ReadingCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


def helper_instance() -> ReadingCommand:
    return ReadingCommand(MagicMock(), MagicMock())


def helper_user(is_admin: bool = False) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def test___init__() -> None:
    database = MagicMock()
    meter_reader = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()
        meter_reader.reset_mock()

    tested = ReadingCommand(database, meter_reader)
    assert tested._database is database
    assert tested._meter_reader is meter_reader
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_visible_house_ids")
def test_dashboard(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    house_rows = [{"id": 1, "name": "sealedFremur", "has_sensors": True}, {"id": 2, "name": "sealedDougmar", "has_sensors": False}]
    meter_rows = [{"id": 9, "house_id": 1, "kind": "electricity", "label": "sealedEDF", "unit": "kWh", "monthly": False}]
    register_rows = [{"id": 21, "meter_id": 9, "label": "sealedHC", "position": 0}]
    visible_house_ids.side_effect = [[1]]
    database.fetch_all.side_effect = [house_rows, meter_rows, register_rows]
    database.decrypt_rows.side_effect = [
        [{"id": 1, "name": "Fremur", "has_sensors": True}, {"id": 2, "name": "Dougmar", "has_sensors": False}],
        [{"id": 9, "house_id": 1, "kind": "electricity", "label": "EDF", "unit": "kWh", "monthly": False}],
        [{"id": 21, "meter_id": 9, "label": "HC", "position": 0}],
    ]
    result = tested.dashboard(user)
    expected = {
        "houses": [{"id": 1, "name": "Fremur", "has_sensors": True}],
        "meters": [
            {
                "id": 9,
                "house_id": 1,
                "kind": "electricity",
                "label": "EDF",
                "unit": "kWh",
                "monthly": False,
                "registers": [{"id": 21, "label": "HC"}],
            },
        ],
    }
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_all(
            """
                    SELECT houses.id, houses.name_sealed AS name,
                           EXISTS (SELECT 1 FROM sensors WHERE sensors.house_id = houses.id) AS has_sensors
                    FROM houses ORDER BY houses.id
                    """,
        ),
        call.decrypt_rows(house_rows, ("name",)),
        call.fetch_all(
            """
                    SELECT meters.id, meters.house_id, meters.kind, meters.label_sealed AS label, meters.unit, meters.monthly
                    FROM meters
                    LEFT JOIN meter_orders ON meter_orders.meter_id = meters.id AND meter_orders.user_id = %s
                    WHERE meters.active
                    ORDER BY meters.house_id, COALESCE(meter_orders.position, meters.position), meters.position, meters.id
                    """,
            (7,),
        ),
        call.decrypt_rows(meter_rows, ("label",)),
        call.fetch_all(
            """
                SELECT id, meter_id, label_sealed AS label, position
                FROM registers WHERE active ORDER BY meter_id, position
                """,
        ),
        call.decrypt_rows(register_rows, ("label",)),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_require_house")
def test_list_readings(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    exp_count_call = call.fetch_one(
        """
            SELECT COUNT(DISTINCT readings.read_on) AS count FROM readings
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            """,
        (1,),
    )
    exp_dates_call = call.fetch_all(
        """
            SELECT DISTINCT readings.read_on FROM readings
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            ORDER BY readings.read_on DESC
            LIMIT %s OFFSET %s
            """,
        (1, 25, 0),
    )
    exp_page_call = call.fetch_all(
        """
                SELECT readings.id, readings.meter_id, readings.read_on, readings.source,
                       meters.kind, meters.label_sealed AS meter_label, meters.unit
                FROM readings
                JOIN meters ON meters.id = readings.meter_id
                WHERE meters.house_id = %s AND readings.read_on = ANY(%s)
                ORDER BY readings.read_on DESC, readings.id DESC
                """,
        (1, ["2026-01-15"]),
    )
    exp_values_call = call.fetch_all(
        """
                SELECT reading_values.reading_id, reading_values.register_id, reading_values.value,
                       registers.label_sealed AS label, registers.position
                FROM reading_values
                JOIN registers ON registers.id = reading_values.register_id
                WHERE reading_values.reading_id = ANY(%s)
                ORDER BY reading_values.reading_id, registers.position
                """,
        ([31],),
    )

    reading_rows = [
        {"id": 31, "meter_id": 9, "read_on": "2026-01-15", "source": "manual", "kind": "electricity", "meter_label": "sealedEDF", "unit": "kWh"},
    ]
    value_rows = [
        {"reading_id": 31, "register_id": 21, "value": 17273, "label": "sealedHC", "position": 0},
    ]
    require_house.side_effect = [None]
    database.fetch_one.side_effect = [{"count": 1}]
    database.fetch_all.side_effect = [[{"read_on": "2026-01-15"}], reading_rows, value_rows]
    database.decrypt_rows.side_effect = [
        [{"id": 31, "meter_id": 9, "read_on": "2026-01-15", "source": "manual", "kind": "electricity", "meter_label": "EDF", "unit": "kWh"}],
        [{"reading_id": 31, "register_id": 21, "value": 17273, "label": "HC", "position": 0}],
    ]
    result = tested.list_readings(user, 1, 1)
    expected = {
        "readings": [
            {
                "id": 31,
                "meter_id": 9,
                "read_on": "2026-01-15",
                "source": "manual",
                "kind": "electricity",
                "meter_label": "EDF",
                "unit": "kWh",
                "values": [{"register_id": 21, "label": "HC", "value": 17273.0}],
            },
        ],
        "total": 1,
        "page": 1,
        "pages": 1,
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 1)]
    exp_calls = [
        exp_count_call,
        exp_dates_call,
        exp_page_call,
        call.decrypt_rows(reading_rows, ("meter_label",)),
        exp_values_call,
        call.decrypt_rows(value_rows, ("label",)),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()

    # an out-of-range page is clamped
    require_house.side_effect = [None]
    database.fetch_one.side_effect = [{"count": 0}]
    database.fetch_all.side_effect = [[], [], []]
    database.decrypt_rows.side_effect = [[], []]
    result = tested.list_readings(user, 1, 9)
    expected = {"readings": [], "total": 0, "page": 1, "pages": 1}
    assert result == expected
    assert require_house.mock_calls == [call(user, 1)]
    exp_calls = [
        exp_count_call,
        exp_dates_call,
        call.fetch_all(
            """
                SELECT readings.id, readings.meter_id, readings.read_on, readings.source,
                       meters.kind, meters.label_sealed AS meter_label, meters.unit
                FROM readings
                JOIN meters ON meters.id = readings.meter_id
                WHERE meters.house_id = %s AND readings.read_on = ANY(%s)
                ORDER BY readings.read_on DESC, readings.id DESC
                """,
            (1, []),
        ),
        call.decrypt_rows([], ("meter_label",)),
        call.fetch_all(
            """
                SELECT reading_values.reading_id, reading_values.register_id, reading_values.value,
                       registers.label_sealed AS label, registers.position
                FROM reading_values
                JOIN registers ON registers.id = reading_values.register_id
                WHERE reading_values.reading_id = ANY(%s)
                ORDER BY reading_values.reading_id, registers.position
                """,
            ([],),
        ),
        call.decrypt_rows([], ("label",)),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_accumulated_values")
@patch.object(ReadingCommand, "_register_values")
@patch.object(ReadingCommand, "_valid_date")
@patch.object(ReadingCommand, "_require_meter")
def test_create_reading(
    require_meter: MagicMock,
    valid_date: MagicMock,
    register_values: MagicMock,
    accumulated_values: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_meter.reset_mock()
        valid_date.reset_mock()
        register_values.reset_mock()
        accumulated_values.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    data = {
        "meter_id": 9,
        "read_on": "2026-01-15",
        "source": "photo",
        "values": [{"register_id": 21, "value": 17273.0}],
    }
    exp_duplicate_call = call.fetch_one("SELECT id FROM readings WHERE meter_id = %s AND read_on = %s", (9, "2026-01-15"))

    # unknown source
    require_meter.side_effect = [{"id": 9, "house_id": 1, "monthly": False}]
    valid_date.side_effect = ["2026-01-15"]
    with pytest.raises(AppException) as exc_info:
        tested.create_reading(user, data | {"source": "guess"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Unknown reading source."
    assert require_meter.mock_calls == [call(user, 9)]
    assert valid_date.mock_calls == [call("2026-01-15")]
    assert register_values.mock_calls == []
    assert accumulated_values.mock_calls == []
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()

    # duplicate date
    require_meter.side_effect = [{"id": 9, "house_id": 1, "monthly": False}]
    valid_date.side_effect = ["2026-01-15"]
    register_values.side_effect = [[(21, 17273.0)]]
    database.fetch_one.side_effect = [{"id": 30}]
    with pytest.raises(AppException) as exc_info:
        tested.create_reading(user, data)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "A reading already exists for this meter and date."
    assert require_meter.mock_calls == [call(user, 9)]
    assert valid_date.mock_calls == [call("2026-01-15")]
    assert register_values.mock_calls == [call(9, [{"register_id": 21, "value": 17273.0}])]
    assert accumulated_values.mock_calls == []
    assert database.mock_calls == [exp_duplicate_call]
    assert meter_reader.mock_calls == []
    reset_mocks()

    # happy path on a counter meter: the value is stored as entered
    require_meter.side_effect = [{"id": 9, "house_id": 1, "monthly": False}]
    valid_date.side_effect = ["2026-01-15"]
    register_values.side_effect = [[(21, 17273.0)]]
    database.fetch_one.side_effect = [None]
    database.execute.side_effect = [31, 41]
    result = tested.create_reading(user, data)
    expected = {"id": 31}
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    assert valid_date.mock_calls == [call("2026-01-15")]
    assert register_values.mock_calls == [call(9, [{"register_id": 21, "value": 17273.0}])]
    assert accumulated_values.mock_calls == []
    exp_calls = [
        exp_duplicate_call,
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(
            "INSERT INTO readings(meter_id, read_on, source, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (9, "2026-01-15", "photo", 7),
        ),
        call.execute(
            "INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)",
            (31, 21, 17273.0),
        ),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()

    # happy path on a monthly meter: the consumption is added to the previous total
    require_meter.side_effect = [{"id": 9, "house_id": 1, "monthly": True}]
    valid_date.side_effect = ["2026-01-15"]
    register_values.side_effect = [[(21, 45.0)]]
    accumulated_values.side_effect = [[(21, 17318.0)]]
    database.fetch_one.side_effect = [None]
    database.execute.side_effect = [31, 41]
    result = tested.create_reading(user, data | {"values": [{"register_id": 21, "value": 45.0}]})
    expected = {"id": 31}
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    assert valid_date.mock_calls == [call("2026-01-15")]
    assert register_values.mock_calls == [call(9, [{"register_id": 21, "value": 45.0}])]
    assert accumulated_values.mock_calls == [call("2026-01-15", [(21, 45.0)])]
    exp_calls = [
        exp_duplicate_call,
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(
            "INSERT INTO readings(meter_id, read_on, source, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (9, "2026-01-15", "photo", 7),
        ),
        call.execute(
            "INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)",
            (31, 21, 17318.0),
        ),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_register_values")
@patch.object(ReadingCommand, "_valid_date")
@patch.object(ReadingCommand, "_require_reading")
def test_update_reading(require_reading: MagicMock, valid_date: MagicMock, register_values: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_reading.reset_mock()
        valid_date.reset_mock()
        register_values.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    data = {"read_on": "2026-01-16", "values": [{"register_id": 21, "value": 17300.0}]}
    exp_duplicate_call = call.fetch_one(
        "SELECT id FROM readings WHERE meter_id = %s AND read_on = %s AND id != %s",
        (9, "2026-01-16", 31),
    )

    # another reading already uses the date
    require_reading.side_effect = [{"id": 31, "meter_id": 9, "house_id": 1}]
    valid_date.side_effect = ["2026-01-16"]
    register_values.side_effect = [[(21, 17300.0)]]
    database.fetch_one.side_effect = [{"id": 30}]
    with pytest.raises(AppException) as exc_info:
        tested.update_reading(user, 31, data)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "A reading already exists for this meter and date."
    assert require_reading.mock_calls == [call(user, 31)]
    assert valid_date.mock_calls == [call("2026-01-16")]
    assert register_values.mock_calls == [call(9, [{"register_id": 21, "value": 17300.0}])]
    assert database.mock_calls == [exp_duplicate_call]
    assert meter_reader.mock_calls == []
    reset_mocks()

    # happy path
    require_reading.side_effect = [{"id": 31, "meter_id": 9, "house_id": 1}]
    valid_date.side_effect = ["2026-01-16"]
    register_values.side_effect = [[(21, 17300.0)]]
    database.fetch_one.side_effect = [None]
    database.execute.side_effect = [0, 41]
    result = tested.update_reading(user, 31, data)
    expected = {"message": "Reading updated."}
    assert result == expected
    assert require_reading.mock_calls == [call(user, 31)]
    assert valid_date.mock_calls == [call("2026-01-16")]
    assert register_values.mock_calls == [call(9, [{"register_id": 21, "value": 17300.0}])]
    exp_calls = [
        exp_duplicate_call,
        call.transaction(),
        call.transaction().__enter__(),
        call.execute("UPDATE readings SET read_on = %s WHERE id = %s", ("2026-01-16", 31)),
        call.execute(
            """
                    INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)
                    ON CONFLICT (reading_id, register_id) DO UPDATE SET value = EXCLUDED.value
                    """,
            (31, 21, 17300.0),
        ),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_require_reading")
def test_delete_reading(require_reading: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_reading.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    require_reading.side_effect = [{"id": 31, "meter_id": 9, "house_id": 1}]
    database.execute.side_effect = [0]
    result = tested.delete_reading(user, 31)
    expected = {"message": "Reading deleted."}
    assert result == expected
    assert require_reading.mock_calls == [call(user, 31)]
    exp_calls = [call.execute("DELETE FROM readings WHERE id = %s", (31,))]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_active_registers")
@patch.object(ReadingCommand, "_require_meter")
def test_extract(require_meter: MagicMock, active_registers: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_meter.reset_mock()
        active_registers.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    data = {"meter_id": 9, "media_type": "image/jpeg", "image_base64": "aGVsbG8="}

    # unsupported media type
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    with pytest.raises(AppException) as exc_info:
        tested.extract(user, data | {"media_type": "application/pdf"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Unsupported photo format."
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == []
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()

    # missing photo
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    with pytest.raises(AppException) as exc_info:
        tested.extract(user, data | {"image_base64": ""})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Provide a photo."
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == []
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()

    # oversized photo
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    with pytest.raises(AppException) as exc_info:
        tested.extract(user, data | {"image_base64": "a" * 14_000_000})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The photo is too large."
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == []
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()

    # happy path
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    active_registers.side_effect = [[{"id": 21, "label": "HC"}, {"id": 22, "label": "HP"}]]
    meter_reader.read.side_effect = [[17273.0, None]]
    result = tested.extract(user, data)
    expected = {
        "values": [
            {"register_id": 21, "label": "HC", "value": 17273.0},
            {"register_id": 22, "label": "HP", "value": None},
        ],
    }
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    assert meter_reader.mock_calls == [call.read("aGVsbG8=", "image/jpeg", ["HC", "HP"])]
    reset_mocks()

    # a cycling display: one register per photo
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    active_registers.side_effect = [[{"id": 21, "label": "HC"}, {"id": 22, "label": "HP"}]]
    meter_reader.read.side_effect = [[17273.0]]
    result = tested.extract(user, data | {"register_id": 22})
    expected = {
        "values": [
            {"register_id": 22, "label": "HP", "value": 17273.0},
        ],
    }
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    assert meter_reader.mock_calls == [call.read("aGVsbG8=", "image/jpeg", ["HP"])]
    reset_mocks()

    # unknown register
    require_meter.side_effect = [{"id": 9, "house_id": 1}]
    active_registers.side_effect = [[{"id": 21, "label": "HC"}]]
    with pytest.raises(AppException) as exc_info:
        tested.extract(user, data | {"register_id": 99})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The register was not found."
    assert require_meter.mock_calls == [call(user, 9)]
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    assert meter_reader.mock_calls == []
    reset_mocks()


def test_reminder_states() -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    database.fetch_all.side_effect = [[{"house_id": 2}, {"house_id": 5}]]
    result = tested.reminder_states(user)
    expected = {"disabled_house_ids": [2, 5]}
    assert result == expected
    exp_calls = [
        call.fetch_all(
            "SELECT house_id FROM reminders WHERE user_id = %s AND NOT enabled ORDER BY house_id",
            (7,),
        ),
    ]
    assert database.mock_calls == exp_calls
    assert meter_reader.mock_calls == []
    reset_mocks()


@patch.object(ReadingCommand, "_require_house")
def test_set_reminder(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    meter_reader = tested._meter_reader

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()
        meter_reader.reset_mock()

    user = helper_user()
    tests = [
        (True, "Monthly reminder enabled for this house."),
        (False, "Monthly reminder disabled for this house."),
    ]
    for enabled, message in tests:
        require_house.side_effect = [None]
        database.execute.side_effect = [0]
        result = tested.set_reminder(user, {"house_id": 2, "enabled": enabled})
        expected = {"message": message}
        assert result == expected, f"---> {enabled}"
        assert require_house.mock_calls == [call(user, 2)]
        exp_calls = [
            call.execute(
                """
            INSERT INTO reminders(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
                (7, 2, enabled),
            ),
        ]
        assert database.mock_calls == exp_calls
        assert meter_reader.mock_calls == []
        reset_mocks()


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


@patch.object(ReadingCommand, "_visible_house_ids")
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


@patch.object(ReadingCommand, "_visible_house_ids")
def test__require_meter(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one("SELECT id, house_id, monthly FROM meters WHERE id = %s", (9,))

    # unknown meter
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_meter(user, 9)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The meter was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # no access
    database.fetch_one.side_effect = [{"id": 9, "house_id": 1, "monthly": False}]
    visible_house_ids.side_effect = [[2]]
    with pytest.raises(AppException) as exc_info:
        tested._require_meter(user, 9)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9, "house_id": 1, "monthly": False}]
    visible_house_ids.side_effect = [[1]]
    result = tested._require_meter(user, 9)
    expected = {"id": 9, "house_id": 1, "monthly": False}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()


@patch.object(ReadingCommand, "_visible_house_ids")
def test__require_reading(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one(
        """
            SELECT readings.id, readings.meter_id, meters.house_id
            FROM readings JOIN meters ON meters.id = readings.meter_id
            WHERE readings.id = %s
            """,
        (31,),
    )

    # unknown reading
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_reading(user, 31)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The reading was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # no access
    database.fetch_one.side_effect = [{"id": 31, "meter_id": 9, "house_id": 1}]
    visible_house_ids.side_effect = [[2]]
    with pytest.raises(AppException) as exc_info:
        tested._require_reading(user, 31)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 31, "meter_id": 9, "house_id": 1}]
    visible_house_ids.side_effect = [[1]]
    result = tested._require_reading(user, 31)
    expected = {"id": 31, "meter_id": 9, "house_id": 1}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()


def test__active_registers() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    rows = [{"id": 21, "label": "sealedHC"}]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [[{"id": 21, "label": "HC"}]]
    result = tested._active_registers(9)
    expected = [{"id": 21, "label": "HC"}]
    assert result == expected
    exp_calls = [
        call.fetch_all(
            "SELECT id, label_sealed AS label FROM registers WHERE meter_id = %s AND active ORDER BY position",
            (9,),
        ),
        call.decrypt_rows(rows, ("label",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(ReadingCommand, "_active_registers")
def test__register_values(active_registers: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        active_registers.reset_mock()
        database.reset_mock()

    # a register is missing
    active_registers.side_effect = [[{"id": 21, "label": "HC"}, {"id": 22, "label": "HP"}]]
    with pytest.raises(AppException) as exc_info:
        tested._register_values(9, [{"register_id": 21, "value": 17273.0}])
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Provide a value for each register of the meter."
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    reset_mocks()

    # an unknown register is provided
    active_registers.side_effect = [[{"id": 21, "label": "HC"}]]
    with pytest.raises(AppException) as exc_info:
        tested._register_values(9, [{"register_id": 99, "value": 17273.0}])
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Provide a value for each register of the meter."
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    reset_mocks()

    # happy path keeps the register order
    active_registers.side_effect = [[{"id": 21, "label": "HC"}, {"id": 22, "label": "HP"}]]
    result = tested._register_values(9, [{"register_id": 22, "value": 158.0}, {"register_id": 21, "value": 17273.0}])
    expected = [(21, 17273.0), (22, 158.0)]
    assert result == expected
    assert active_registers.mock_calls == [call(9)]
    assert database.mock_calls == []
    reset_mocks()


def test__accumulated_values() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    exp_previous_call = call.fetch_one(
        """
                SELECT reading_values.value FROM reading_values
                JOIN readings ON readings.id = reading_values.reading_id
                WHERE reading_values.register_id = %s AND readings.read_on < %s
                ORDER BY readings.read_on DESC LIMIT 1
                """,
        (21, "2026-09-15"),
    )
    exp_initial_call = call.fetch_one("SELECT initial_value AS value FROM registers WHERE id = %s", (21,))

    # a previous reading exists: the consumption is added to it
    database.fetch_one.side_effect = [{"value": 42269.0}]
    result = tested._accumulated_values("2026-09-15", [(21, 45.0)])
    expected = [(21, 42314.0)]
    assert result == expected
    assert database.mock_calls == [exp_previous_call]
    reset_mocks()

    # no previous reading: the register's initial value is the baseline
    database.fetch_one.side_effect = [None, {"value": 42000.0}]
    result = tested._accumulated_values("2026-09-15", [(21, 45.0)])
    expected = [(21, 42045.0)]
    assert result == expected
    assert database.mock_calls == [exp_previous_call, exp_initial_call]
    reset_mocks()

    # no register either: the consumption stands alone
    database.fetch_one.side_effect = [None, None]
    result = tested._accumulated_values("2026-09-15", [(21, 45.0)])
    expected = [(21, 45.0)]
    assert result == expected
    assert database.mock_calls == [exp_previous_call, exp_initial_call]
    reset_mocks()


def test__valid_date() -> None:
    tested = helper_instance()

    result = tested._valid_date("2026-01-15")
    expected = "2026-01-15"
    assert result == expected

    error_tests = ["", "not-a-date", "2026-13-01"]
    for value in error_tests:
        with pytest.raises(AppException) as exc_info:
            tested._valid_date(value)
        assert exc_info.value.status_code == 400, f"---> {value}"
        assert exc_info.value.message == "Enter a valid date.", f"---> {value}"
