from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.meter_command import MeterCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


def helper_instance() -> MeterCommand:
    return MeterCommand(MagicMock())


def helper_user(is_admin: bool = False) -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane", is_admin=is_admin)


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = MeterCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch.object(MeterCommand, "_require_house")
def test_list_meters(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    register_rows = [{"id": 21, "meter_id": 9, "label": "sealedHC", "initial_value": 100, "position": 0, "active": True}]
    meter_rows = [{"id": 9, "house_id": 3, "kind": "electricity", "label": "sealedEDF", "unit": "kWh", "position": 0, "active": True}]
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [register_rows, meter_rows]
    database.decrypt_rows.side_effect = [
        [{"id": 21, "meter_id": 9, "label": "HC", "initial_value": 100, "position": 0, "active": True}],
        [{"id": 9, "house_id": 3, "kind": "electricity", "label": "EDF", "unit": "kWh", "position": 0, "active": True}],
    ]
    result = tested.list_meters(user, 3)
    expected = {
        "meters": [
            {
                "id": 9,
                "house_id": 3,
                "kind": "electricity",
                "label": "EDF",
                "unit": "kWh",
                "position": 0,
                "active": True,
                "registers": [{"id": 21, "label": "HC", "initial_value": 100.0, "position": 0, "active": True}],
            },
        ],
    }
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.fetch_all(
            """
                SELECT registers.id, registers.meter_id, registers.label_sealed AS label,
                       registers.initial_value, registers.position, registers.active
                FROM registers JOIN meters ON meters.id = registers.meter_id
                WHERE meters.house_id = %s ORDER BY registers.meter_id, registers.position
                """,
            (3,),
        ),
        call.decrypt_rows(register_rows, ("label",)),
        call.fetch_all(
            """
                SELECT meters.id, meters.house_id, meters.kind, meters.label_sealed AS label,
                       meters.unit, meters.position, meters.active
                FROM meters
                LEFT JOIN meter_orders ON meter_orders.meter_id = meters.id AND meter_orders.user_id = %s
                WHERE meters.house_id = %s
                ORDER BY COALESCE(meter_orders.position, meters.position), meters.position, meters.id
                """,
            (7, 3),
        ),
        call.decrypt_rows(meter_rows, ("label",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_house")
def test_set_order(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()

    # the list must be a permutation of the house meters
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[{"id": 7}, {"id": 8}, {"id": 9}]]
    with pytest.raises(AppException) as exc_info:
        tested.set_order(user, {"house_id": 3, "meter_ids": [9, 7]})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The order must include every meter of the house exactly once."
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [call.fetch_all("SELECT id FROM meters WHERE house_id = %s ORDER BY id", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path: one row per meter for this user only
    require_house.side_effect = [None]
    database.fetch_all.side_effect = [[{"id": 7}, {"id": 8}, {"id": 9}]]
    database.execute.side_effect = [0, 0, 0]
    result = tested.set_order(user, {"house_id": 3, "meter_ids": [9, 7, 8]})
    expected = {"message": "Meter order saved."}
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    exp_upsert = """
                    INSERT INTO meter_orders(user_id, meter_id, position) VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, meter_id) DO UPDATE SET position = EXCLUDED.position
                    """
    exp_calls = [
        call.fetch_all("SELECT id FROM meters WHERE house_id = %s ORDER BY id", (3,)),
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(exp_upsert, (7, 9, 0)),
        call.execute(exp_upsert, (7, 7, 1)),
        call.execute(exp_upsert, (7, 8, 2)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_house")
def test_create_meter(require_house: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_house.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_meter_insert = call.execute(
        """
                INSERT INTO meters(house_id, kind, label_sealed, unit)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
        (3, "electricity", "sealedLabel", "kWh"),
    )
    exp_register_insert_one = call.execute(
        """
                    INSERT INTO registers(meter_id, label_sealed, initial_value, position)
                    VALUES (%s, %s, %s, %s)
                    """,
        (9, "sealedRegisterOne", 100.0, 0),
    )
    exp_register_insert_two = call.execute(
        """
                    INSERT INTO registers(meter_id, label_sealed, initial_value, position)
                    VALUES (%s, %s, %s, %s)
                    """,
        (9, "sealedRegisterTwo", 200.0, 1),
    )

    # unknown kind
    with pytest.raises(AppException) as exc_info:
        tested.create_meter(user, {"house_id": 3, "kind": "coal"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Unknown meter kind."
    assert require_house.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # too many registers
    require_house.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.create_meter(user, {"house_id": 3, "kind": "electricity", "registers": [{}, {}, {}]})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "A meter has one or two registers."
    assert require_house.mock_calls == [call(user, 3)]
    assert database.mock_calls == []
    reset_mocks()

    # happy path with two registers
    require_house.side_effect = [None]
    database.encrypt.side_effect = ["sealedLabel", "sealedRegisterOne", "sealedRegisterTwo"]
    database.execute.side_effect = [9, 21, 22]
    result = tested.create_meter(
        user,
        {
            "house_id": 3,
            "kind": "electricity",
            "label": " EDF ",
            "unit": " kWh ",
            "registers": [
                {"label": " HC ", "initial_value": 100.0},
                {"label": " HP ", "initial_value": 200.0},
            ],
        },
    )
    expected = {"id": 9}
    assert result == expected
    assert require_house.mock_calls == [call(user, 3)]
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.encrypt("EDF"),
        exp_meter_insert,
        call.encrypt("HC"),
        exp_register_insert_one,
        call.encrypt("HP"),
        exp_register_insert_two,
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_meter")
def test_update_meter(require_meter: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_meter.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_meter.side_effect = [{"id": 9, "house_id": 3}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [0]
    result = tested.update_meter(user, 9, {"label": " EDF ", "unit": " kWh ", "active": True})
    expected = {"message": "Meter updated."}
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    exp_calls = [
        call.encrypt("EDF"),
        call.execute(
            "UPDATE meters SET label_sealed = %s, unit = %s, active = %s WHERE id = %s",
            ("sealedLabel", "kWh", True, 9),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_meter")
def test_delete_meter(require_meter: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_meter.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_meter.side_effect = [{"id": 9, "house_id": 3}]
    database.execute.side_effect = [0]
    result = tested.delete_meter(user, 9)
    expected = {"message": "Meter deleted, along with its readings."}
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    exp_calls = [call.execute("DELETE FROM meters WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_meter")
def test_create_register(require_meter: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_meter.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_count_call = call.fetch_one(
        "SELECT COUNT(*) AS count, COALESCE(MAX(position), -1) AS top FROM registers WHERE meter_id = %s AND active",
        (9,),
    )
    exp_insert = call.execute(
        """
            INSERT INTO registers(meter_id, label_sealed, initial_value, position)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
        (9, "sealedLabel", 100.0, 2),
    )

    # two registers already active
    require_meter.side_effect = [{"id": 9, "house_id": 3}]
    database.fetch_one.side_effect = [{"count": 2, "top": 1}]
    with pytest.raises(AppException) as exc_info:
        tested.create_register(user, 9, {"label": "HP"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "A meter has at most two active registers."
    assert require_meter.mock_calls == [call(user, 9)]
    assert database.mock_calls == [exp_count_call]
    reset_mocks()

    # happy path
    require_meter.side_effect = [{"id": 9, "house_id": 3}]
    database.fetch_one.side_effect = [{"count": 1, "top": 1}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [22]
    result = tested.create_register(user, 9, {"label": " HP ", "initial_value": 100.0})
    expected = {"id": 22}
    assert result == expected
    assert require_meter.mock_calls == [call(user, 9)]
    exp_calls = [exp_count_call, call.encrypt("HP"), exp_insert]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_register")
def test_update_register(require_register: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_register.reset_mock()
        database.reset_mock()

    user = helper_user()
    require_register.side_effect = [{"id": 22, "house_id": 3}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [0]
    result = tested.update_register(user, 22, {"label": " HP ", "initial_value": 100.0, "active": False})
    expected = {"message": "Register updated."}
    assert result == expected
    assert require_register.mock_calls == [call(user, 22)]
    exp_calls = [
        call.encrypt("HP"),
        call.execute(
            "UPDATE registers SET label_sealed = %s, initial_value = %s, active = %s WHERE id = %s",
            ("sealedLabel", 100.0, False, 22),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(MeterCommand, "_require_register")
def test_delete_register(require_register: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_register.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_values_call = call.fetch_one("SELECT COUNT(*) AS count FROM reading_values WHERE register_id = %s", (22,))

    # the register has readings
    require_register.side_effect = [{"id": 22, "house_id": 3}]
    database.fetch_one.side_effect = [{"count": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.delete_register(user, 22)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This register has readings. Deactivate it instead."
    assert require_register.mock_calls == [call(user, 22)]
    assert database.mock_calls == [exp_values_call]
    reset_mocks()

    # happy path
    require_register.side_effect = [{"id": 22, "house_id": 3}]
    database.fetch_one.side_effect = [{"count": 0}]
    database.execute.side_effect = [0]
    result = tested.delete_register(user, 22)
    expected = {"message": "Register deleted."}
    assert result == expected
    assert require_register.mock_calls == [call(user, 22)]
    exp_calls = [exp_values_call, call.execute("DELETE FROM registers WHERE id = %s", (22,))]
    assert database.mock_calls == exp_calls
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


@patch.object(MeterCommand, "_visible_house_ids")
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


@patch.object(MeterCommand, "_visible_house_ids")
def test__require_meter(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one("SELECT id, house_id FROM meters WHERE id = %s", (9,))

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
    database.fetch_one.side_effect = [{"id": 9, "house_id": 1}]
    visible_house_ids.side_effect = [[2]]
    with pytest.raises(AppException) as exc_info:
        tested._require_meter(user, 9)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9, "house_id": 1}]
    visible_house_ids.side_effect = [[1]]
    result = tested._require_meter(user, 9)
    expected = {"id": 9, "house_id": 1}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()


@patch.object(MeterCommand, "_visible_house_ids")
def test__require_register(visible_house_ids: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        visible_house_ids.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_fetch = call.fetch_one(
        """
            SELECT registers.id, meters.house_id
            FROM registers JOIN meters ON meters.id = registers.meter_id
            WHERE registers.id = %s
            """,
        (22,),
    )

    # unknown register
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested._require_register(user, 22)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The register was not found."
    assert visible_house_ids.mock_calls == []
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # no access
    database.fetch_one.side_effect = [{"id": 22, "house_id": 1}]
    visible_house_ids.side_effect = [[2]]
    with pytest.raises(AppException) as exc_info:
        tested._require_register(user, 22)
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "You do not have access to this house."
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 22, "house_id": 1}]
    visible_house_ids.side_effect = [[1]]
    result = tested._require_register(user, 22)
    expected = {"id": 22, "house_id": 1}
    assert result == expected
    assert visible_house_ids.mock_calls == [call(user)]
    assert database.mock_calls == [exp_fetch]
    reset_mocks()
