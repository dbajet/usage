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


@patch.object(AdminCommand, "_houses")
@patch.object(AdminCommand, "_require_admin")
def test_overview(require_admin: MagicMock, houses: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        require_admin.reset_mock()
        houses.reset_mock()
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
    }
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    assert houses.mock_calls == [call()]
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

    # unknown time zone
    for timezone in ("", "Mars/Olympus"):
        with pytest.raises(AppException) as exc_info:
            tested.update_house(user, 3, {"name": "Fremur", "timezone": timezone})
        assert exc_info.value.status_code == 400, f"---> {timezone}"
        assert exc_info.value.message == "Unknown time zone.", f"---> {timezone}"
        assert require_admin.mock_calls == [call(user)]
        assert database.mock_calls == []
        reset_mocks()

    # unknown house
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.update_house(user, 3, {"name": "Fremur", "timezone": "Europe/Paris"})
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
    result = tested.update_house(user, 3, {"name": " Fremur ", "timezone": "America/Los_Angeles"})
    expected = {"message": "House updated."}
    assert result == expected
    assert require_admin.mock_calls == [call(user)]
    exp_calls = [
        call.fetch_one("SELECT id FROM houses WHERE id = %s", (3,)),
        call.encrypt("Fremur"),
        call.execute(
            "UPDATE houses SET name_sealed = %s, timezone = %s WHERE id = %s",
            ("sealedName", "America/Los_Angeles", 3),
        ),
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


def test__houses() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    rows = [{"id": 3, "name": "sealedName", "timezone": "Europe/Paris"}]
    database.fetch_all.side_effect = [rows]
    database.decrypt_rows.side_effect = [[{"id": 3, "name": "Fremur", "timezone": "Europe/Paris"}]]
    result = tested._houses()
    expected = [{"id": 3, "name": "Fremur", "timezone": "Europe/Paris"}]
    assert result == expected
    exp_calls = [
        call.fetch_all("SELECT id, name_sealed AS name, timezone FROM houses ORDER BY id"),
        call.decrypt_rows(rows, ("name",)),
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
