from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.admin_command import AdminCommand
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


def helper_instance() -> AdminCommand:
    return AdminCommand(MagicMock())


def helper_user(is_admin: bool = True) -> SessionUser:
    return SessionUser(user_id=7, email="admin@example.com", name="The Admin", is_admin=is_admin)


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = AdminCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch.object(AdminCommand, "_meters")
@patch.object(AdminCommand, "_houses")
@patch.object(AdminCommand, "_require_admin")
def test_overview(require_admin: MagicMock, houses: MagicMock, meters: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        houses.reset_mock()
        meters.reset_mock()
        database.reset_mock()

    user = helper_user()
    sealed_users = [
        {"id": 3, "email": "sealedJane", "name": "sealedJaneName", "is_admin": True, "last_login_at": "2026-08-01"},
        {"id": 4, "email": "sealedJohn", "name": "sealedJohnName", "is_admin": False, "last_login_at": None},
    ]
    database.fetch_all.side_effect = [
        [{"user_id": 3, "house_id": 1}, {"user_id": 3, "house_id": 2}, {"user_id": 4, "house_id": 2}],
        sealed_users,
    ]
    database.decrypt_rows.side_effect = [
        [
            {"id": 3, "email": "jane@example.com", "name": "Jane", "is_admin": True, "last_login_at": "2026-08-01"},
            {"id": 4, "email": "john@example.com", "name": "John", "is_admin": False, "last_login_at": None},
        ],
    ]
    houses.side_effect = [[{"id": 1, "name": "Fremur"}]]
    meters.side_effect = [[{"id": 9, "house_id": 1}]]
    result = tested.overview(user)
    expected = {
        "users": [
            {
                "id": 3,
                "email": "jane@example.com",
                "name": "Jane",
                "is_admin": True,
                "last_login_at": "2026-08-01",
                "house_ids": [1, 2],
            },
            {
                "id": 4,
                "email": "john@example.com",
                "name": "John",
                "is_admin": False,
                "last_login_at": "",
                "house_ids": [2],
            },
        ],
        "houses": [{"id": 1, "name": "Fremur"}],
        "meters": [{"id": 9, "house_id": 1}],
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert houses.mock_calls == [call()]
    assert meters.mock_calls == [call()]
    exp_calls = [
        call.fetch_all("SELECT user_id, house_id FROM user_houses ORDER BY id"),
        call.fetch_all(
            """
                SELECT id, email_sealed AS email, name_sealed AS name, is_admin, last_login_at
                FROM users ORDER BY id
                """,
        ),
        call.decrypt_rows(sealed_users, ("email", "name")),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_create_user(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_insert = call.execute(
        """
            INSERT INTO users(email_sealed, email_hash, name_sealed, is_admin)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
        ("sealedEmail", "theEmailHash", "sealedName", True),
    )

    # invalid email
    with pytest.raises(AppException) as exc_info:
        tested.create_user(user, {"email": "not-an-email"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter a valid email address."
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # duplicate email
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 4}]
    with pytest.raises(AppException) as exc_info:
        tested.create_user(user, {"email": " Jane@Example.com "})
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "A user with this email already exists."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.blind_index("jane@example.com"),
        call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [None]
    database.encrypt.side_effect = ["sealedEmail", "sealedName"]
    database.execute.side_effect = [12]
    result = tested.create_user(user, {"email": " Jane@Example.com ", "name": " Jane ", "is_admin": True})
    expected = {"id": 12}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.blind_index("jane@example.com"),
        call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",)),
        call.encrypt("jane@example.com"),
        call.encrypt("Jane"),
        exp_insert,
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_update_user(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # removing one's own admin flag is refused
    with pytest.raises(AppException) as exc_info:
        tested.update_user(user, 7, {"name": "The Admin", "is_admin": False})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "You cannot remove your own admin access."
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # unknown user
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.update_user(user, 9, {"name": "Jane", "is_admin": False})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The user was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM users WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9}]
    database.encrypt.side_effect = ["sealedName"]
    database.execute.side_effect = [0]
    result = tested.update_user(user, 9, {"name": " Jane ", "is_admin": True})
    expected = {"message": "User updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM users WHERE id = %s", (9,)),
        call.encrypt("Jane"),
        call.execute("UPDATE users SET name_sealed = %s, is_admin = %s WHERE id = %s", ("sealedName", True, 9)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_delete_user(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # deleting oneself is refused
    with pytest.raises(AppException) as exc_info:
        tested.delete_user(user, 7)
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "You cannot delete your own account."
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # unknown user
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.delete_user(user, 9)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The user was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM users WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9}]
    database.execute.side_effect = [0]
    result = tested.delete_user(user, 9)
    expected = {"message": "User deleted."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM users WHERE id = %s", (9,)),
        call.execute("DELETE FROM users WHERE id = %s", (9,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_create_house(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # empty name
    with pytest.raises(AppException) as exc_info:
        tested.create_house(user, {"name": "  "})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter a house name."
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # happy path
    database.encrypt.side_effect = ["sealedName"]
    database.execute.side_effect = [3]
    result = tested.create_house(user, {"name": " Fremur "})
    expected = {"id": 3}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.encrypt("Fremur"),
        call.execute("INSERT INTO houses(name_sealed) VALUES (%s) RETURNING id", ("sealedName",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_update_house(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # empty name
    with pytest.raises(AppException) as exc_info:
        tested.update_house(user, 3, {"name": ""})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter a house name."
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.update_house(user, 3, {"name": "Fremur"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 3}]
    database.encrypt.side_effect = ["sealedName"]
    database.execute.side_effect = [0]
    result = tested.update_house(user, 3, {"name": " Fremur "})
    expected = {"message": "House updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
        call.encrypt("Fremur"),
        call.execute("UPDATE houses SET name_sealed = %s WHERE id = %s", ("sealedName", 3)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_delete_house(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.delete_house(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 3}]
    database.execute.side_effect = [0]
    result = tested.delete_house(user, 3)
    expected = {"message": "House deleted."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
        call.execute("DELETE FROM houses WHERE id = %s", (3,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_set_user_house(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_lookups = [
        call.fetch_one("SELECT id FROM users WHERE id = %s", (9,)),
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
    ]

    # unknown user or house
    lookup_tests = [
        (None, {"id": 3}),
        ({"id": 9}, None),
        (None, None),
    ]
    for target_row, house_row in lookup_tests:
        database.fetch_one.side_effect = [target_row, house_row]
        with pytest.raises(AppException) as exc_info:
            tested.set_user_house(user, {"user_id": 9, "house_id": 3, "linked": True})
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "The user or house was not found."
        assert require_admin.mock_calls == [call(user)]
        assert database.mock_calls == exp_lookups
        reset_mocks()

    # link
    database.fetch_one.side_effect = [{"id": 9}, {"id": 3}]
    database.execute.side_effect = [0]
    result = tested.set_user_house(user, {"user_id": 9, "house_id": 3, "linked": True})
    expected = {"message": "User linked to the house."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = exp_lookups + [
        call.execute(
            "INSERT INTO user_houses(user_id, house_id) VALUES (%s, %s) ON CONFLICT (user_id, house_id) DO NOTHING",
            (9, 3),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # unlink
    database.fetch_one.side_effect = [{"id": 9}, {"id": 3}]
    database.execute.side_effect = [0]
    result = tested.set_user_house(user, {"user_id": 9, "house_id": 3, "linked": False})
    expected = {"message": "User unlinked from the house."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = exp_lookups + [
        call.execute("DELETE FROM user_houses WHERE user_id = %s AND house_id = %s", (9, 3)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_create_meter(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
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
    assert require_admin.mock_calls == [call(user)]
    assert database.mock_calls == []
    reset_mocks()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.create_meter(user, {"house_id": 3, "kind": "electricity"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The house was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # too many registers
    database.fetch_one.side_effect = [{"id": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.create_meter(user, {"house_id": 3, "kind": "electricity", "registers": [{}, {}, {}]})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "A meter has one or two registers."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path with two registers
    database.fetch_one.side_effect = [{"id": 3}]
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
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
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


@patch.object(AdminCommand, "_require_admin")
def test_update_meter(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown meter
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.update_meter(user, 9, {"label": "EDF"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The meter was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [0]
    result = tested.update_meter(user, 9, {"label": " EDF ", "unit": " kWh ", "active": True})
    expected = {"message": "Meter updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,)),
        call.encrypt("EDF"),
        call.execute(
            "UPDATE meters SET label_sealed = %s, unit = %s, active = %s WHERE id = %s",
            ("sealedLabel", "kWh", True, 9),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_delete_meter(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown meter
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.delete_meter(user, 9)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The meter was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9}]
    database.execute.side_effect = [0]
    result = tested.delete_meter(user, 9)
    expected = {"message": "Meter deleted, along with its readings."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,)),
        call.execute("DELETE FROM meters WHERE id = %s", (9,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_create_register(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
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

    # unknown meter
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.create_register(user, 9, {"label": "HP"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The meter was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # two registers already active
    database.fetch_one.side_effect = [{"id": 9}, {"count": 2, "top": 1}]
    with pytest.raises(AppException) as exc_info:
        tested.create_register(user, 9, {"label": "HP"})
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "A meter has at most two active registers."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,)), exp_count_call]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 9}, {"count": 1, "top": 1}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [22]
    result = tested.create_register(user, 9, {"label": " HP ", "initial_value": 100.0})
    expected = {"id": 22}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM meters WHERE id = %s", (9,)),
        exp_count_call,
        call.encrypt("HP"),
        exp_insert,
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_update_register(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()

    # unknown register
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.update_register(user, 22, {"label": "HP"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The register was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM registers WHERE id = %s", (22,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 22}]
    database.encrypt.side_effect = ["sealedLabel"]
    database.execute.side_effect = [0]
    result = tested.update_register(user, 22, {"label": " HP ", "initial_value": 100.0, "active": False})
    expected = {"message": "Register updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM registers WHERE id = %s", (22,)),
        call.encrypt("HP"),
        call.execute(
            "UPDATE registers SET label_sealed = %s, initial_value = %s, active = %s WHERE id = %s",
            ("sealedLabel", 100.0, False, 22),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AdminCommand, "_require_admin")
def test_delete_register(require_admin: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        database.reset_mock()

    user = helper_user()
    exp_values_call = call.fetch_one("SELECT COUNT(*) AS count FROM reading_values WHERE register_id = %s", (22,))

    # unknown register
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.delete_register(user, 22)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The register was not found."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM registers WHERE id = %s", (22,))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the register has readings
    database.fetch_one.side_effect = [{"id": 22}, {"count": 3}]
    with pytest.raises(AppException) as exc_info:
        tested.delete_register(user, 22)
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This register has readings. Deactivate it instead."
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [call.fetch_one("SELECT id FROM registers WHERE id = %s", (22,)), exp_values_call]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 22}, {"count": 0}]
    database.execute.side_effect = [0]
    result = tested.delete_register(user, 22)
    expected = {"message": "Register deleted."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM registers WHERE id = %s", (22,)),
        exp_values_call,
        call.execute("DELETE FROM registers WHERE id = %s", (22,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__houses() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    rows = [{"id": 3, "name": "sealedName"}]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [[{"id": 3, "name": "Fremur"}]]
    result = tested._houses()
    expected = [{"id": 3, "name": "Fremur"}]
    assert result == expected
    exp_calls = [
        call.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
        call.decrypt_rows(rows, ("name",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__meters() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    register_rows = [{"id": 21, "meter_id": 9, "label": "sealedHC", "initial_value": 100, "position": 0, "active": True}]
    meter_rows = [{"id": 9, "house_id": 3, "kind": "electricity", "label": "sealedEDF", "unit": "kWh", "position": 0, "active": True}]
    database.fetch_all.side_effect = [register_rows, meter_rows]
    database.decrypt_rows.side_effect = [
        [{"id": 21, "meter_id": 9, "label": "HC", "initial_value": 100, "position": 0, "active": True}],
        [{"id": 9, "house_id": 3, "kind": "electricity", "label": "EDF", "unit": "kWh", "position": 0, "active": True}],
    ]
    result = tested._meters()
    expected = [
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
    ]
    assert result == expected
    exp_calls = [
        call.fetch_all(
            """
                SELECT id, meter_id, label_sealed AS label, initial_value, position, active
                FROM registers ORDER BY meter_id, position
                """,
        ),
        call.decrypt_rows(register_rows, ("label",)),
        call.fetch_all(
            """
                SELECT id, house_id, kind, label_sealed AS label, unit, position, active
                FROM meters ORDER BY house_id, position, id
                """,
        ),
        call.decrypt_rows(meter_rows, ("label",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__require_admin() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # an admin passes
    result = tested._require_admin(helper_user(is_admin=True))
    assert result is None
    assert database.mock_calls == []
    reset_mocks()

    # a common user is refused
    with pytest.raises(AppException) as exc_info:
        tested._require_admin(helper_user(is_admin=False))
    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Only admins can do this."
    assert database.mock_calls == []
    reset_mocks()
