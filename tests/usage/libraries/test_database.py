from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import psycopg
import pytest
from psycopg.rows import dict_row

from usage.libraries.database import Database
from usage.structures.settings import Settings


def helper_settings() -> Settings:
    return Settings(
        database_url="postgresql://localhost/usage",
        encryption_key="theEncryptionKey",
        dev_auth_links=False,
        cookie_secure=True,
        base_url="https://usage.example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="theSmtpUser",
        smtp_password="theSmtpPassword",
        smtp_sender="sender@example.com",
        anthropic_api_key="theAnthropicKey",
        anthropic_model="claude-opus-5",
    )


def helper_instance() -> Database:
    with patch("usage.libraries.database.CryptoBox", side_effect=[MagicMock()]):
        return Database(helper_settings())


@patch("usage.libraries.database.CryptoBox")
def test___init__(crypto_box: MagicMock) -> None:
    crypto = MagicMock()

    def reset_mocks() -> None:
        crypto_box.reset_mock()
        crypto.reset_mock()

    crypto_box.side_effect = [crypto]
    tested = Database(helper_settings())
    result = tested._database_url
    expected = "postgresql://localhost/usage"
    assert result == expected
    assert tested._crypto is crypto
    exp_calls = [call("theEncryptionKey")]
    assert crypto_box.mock_calls == exp_calls
    assert crypto.mock_calls == []
    reset_mocks()


def test_database_url() -> None:
    tested = helper_instance()
    result = tested.database_url
    expected = "postgresql://localhost/usage"
    assert result == expected


@patch.object(Database, "_seed")
@patch.object(Database, "_migrate")
@patch.object(Database, "_create_schema")
@patch.object(Database, "_connection")
@patch.object(Database, "transaction")
def test_initialize(
    transaction: MagicMock,
    mock_connection: MagicMock,
    create_schema: MagicMock,
    migrate: MagicMock,
    seed: MagicMock,
) -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        transaction.reset_mock()
        mock_connection.reset_mock()
        create_schema.reset_mock()
        migrate.reset_mock()
        seed.reset_mock()
        connection.reset_mock()

    tested = helper_instance()
    mock_connection.side_effect = [connection]
    result = tested.initialize()
    assert result is None
    exp_calls = [call(), call().__enter__(), call().__exit__(None, None, None)]
    assert transaction.mock_calls == exp_calls
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call(connection)]
    assert create_schema.mock_calls == exp_calls
    assert migrate.mock_calls == exp_calls
    assert seed.mock_calls == exp_calls
    assert connection.mock_calls == []
    reset_mocks()


@patch.object(Database, "fetch_one")
def test_health(fetch_one: MagicMock) -> None:
    def reset_mocks() -> None:
        fetch_one.reset_mock()

    tested = helper_instance()
    tests = [
        ({"ok": 1}, True),
        ({"ok": 0}, False),
        (None, False),
    ]
    for row, expected in tests:
        fetch_one.side_effect = [row]
        result = tested.health()
        assert result is expected
        exp_calls = [call("SELECT 1 AS ok")]
        assert fetch_one.mock_calls == exp_calls
        reset_mocks()


@patch.object(Database, "_connection")
def test_transaction(mock_connection: MagicMock) -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        mock_connection.reset_mock()
        connection.reset_mock()

    tested = helper_instance()
    mock_connection.side_effect = [connection, connection]
    with tested.transaction():
        result = tested._transaction_depth()
        assert result == 1
        with tested.transaction():
            result = tested._transaction_depth()
            assert result == 2
        result = tested._transaction_depth()
        assert result == 1
    result = tested._transaction_depth()
    assert result == 0
    exp_calls = [call(), call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        call.transaction(),
        call.transaction().__enter__(),
        call.transaction().__exit__(None, None, None),
        call.transaction().__exit__(None, None, None),
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()


@patch("usage.libraries.database.psycopg.connect")
def test__connection(connect: MagicMock) -> None:
    connection_a = MagicMock()
    connection_b = MagicMock()

    def reset_mocks() -> None:
        connect.reset_mock()
        connection_a.reset_mock()
        connection_b.reset_mock()

    tested = helper_instance()
    connection_a.closed = False
    connection_b.closed = False
    connect.side_effect = [connection_a, connection_b]

    # first call opens a connection
    result = tested._connection()
    assert result is connection_a
    exp_calls = [call("postgresql://localhost/usage", row_factory=dict_row)]
    assert connect.mock_calls == exp_calls
    reset_mocks()

    # second call reuses the cached connection
    result = tested._connection()
    assert result is connection_a
    assert connect.mock_calls == []
    reset_mocks()

    # closed connection triggers a reconnect
    connection_a.closed = True
    result = tested._connection()
    assert result is connection_b
    exp_calls = [call("postgresql://localhost/usage", row_factory=dict_row)]
    assert connect.mock_calls == exp_calls
    assert connection_a.mock_calls == []
    assert connection_b.mock_calls == []
    reset_mocks()


def test__transaction_depth() -> None:
    tested = helper_instance()
    result = tested._transaction_depth()
    expected = 0
    assert result == expected

    tested._local.transaction_depth = 3
    result = tested._transaction_depth()
    expected = 3
    assert result == expected


@patch.object(Database, "_connection")
def test__run(mock_connection: MagicMock) -> None:
    connection = MagicMock()
    cursor = MagicMock()

    def reset_mocks() -> None:
        mock_connection.reset_mock()
        connection.reset_mock()
        cursor.reset_mock()

    tested = helper_instance()

    # happy path
    mock_connection.side_effect = [connection]
    connection.execute.side_effect = [cursor]
    result = tested._run("SELECT 1", ("theParameter",))
    assert result is cursor
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call.execute("SELECT 1", ("theParameter",))]
    assert connection.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()

    # operational error outside a transaction: reconnect and retry
    mock_connection.side_effect = [connection, connection]
    connection.execute.side_effect = [psycopg.OperationalError("down"), cursor]
    result = tested._run("SELECT 1", ("theParameter",))
    assert result is cursor
    exp_calls = [call(), call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [
        call.execute("SELECT 1", ("theParameter",)),
        call.close(),
        call.execute("SELECT 1", ("theParameter",)),
    ]
    assert connection.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()

    # operational error inside a transaction: re-raise
    tested._local.transaction_depth = 1
    mock_connection.side_effect = [connection]
    connection.execute.side_effect = [psycopg.OperationalError("down")]
    with pytest.raises(psycopg.OperationalError):
        tested._run("SELECT 1", ("theParameter",))
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call.execute("SELECT 1", ("theParameter",))]
    assert connection.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()

    # other database error outside a transaction: rollback and re-raise
    tested._local.transaction_depth = 0
    mock_connection.side_effect = [connection]
    connection.execute.side_effect = [psycopg.ProgrammingError("bad")]
    with pytest.raises(psycopg.ProgrammingError):
        tested._run("SELECT 1", ("theParameter",))
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call.execute("SELECT 1", ("theParameter",)), call.rollback()]
    assert connection.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()

    # other database error inside a transaction: re-raise without rollback
    tested._local.transaction_depth = 1
    mock_connection.side_effect = [connection]
    connection.execute.side_effect = [psycopg.ProgrammingError("bad")]
    with pytest.raises(psycopg.ProgrammingError):
        tested._run("SELECT 1", ("theParameter",))
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call.execute("SELECT 1", ("theParameter",))]
    assert connection.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()


@patch.object(Database, "_connection")
def test__finish(mock_connection: MagicMock) -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        mock_connection.reset_mock()
        connection.reset_mock()

    tested = helper_instance()

    # outside a transaction: commit
    mock_connection.side_effect = [connection]
    result = tested._finish()
    assert result is None
    exp_calls = [call()]
    assert mock_connection.mock_calls == exp_calls
    exp_calls = [call.commit()]
    assert connection.mock_calls == exp_calls
    reset_mocks()

    # inside a transaction: no commit
    tested._local.transaction_depth = 1
    mock_connection.side_effect = []
    result = tested._finish()
    assert result is None
    assert mock_connection.mock_calls == []
    assert connection.mock_calls == []
    reset_mocks()


def test_encrypt() -> None:
    tested = helper_instance()
    crypto = tested._crypto

    def reset_mocks() -> None:
        crypto.reset_mock()

    crypto.encrypt.side_effect = ["theSealedValue"]
    result = tested.encrypt("theValue")
    expected = "theSealedValue"
    assert result == expected
    exp_calls = [call.encrypt("theValue")]
    assert crypto.mock_calls == exp_calls
    reset_mocks()


def test_decrypt() -> None:
    tested = helper_instance()
    crypto = tested._crypto

    def reset_mocks() -> None:
        crypto.reset_mock()

    crypto.decrypt.side_effect = ["theValue"]
    result = tested.decrypt("theSealedValue")
    expected = "theValue"
    assert result == expected
    exp_calls = [call.decrypt("theSealedValue")]
    assert crypto.mock_calls == exp_calls
    reset_mocks()


def test_blind_index() -> None:
    tested = helper_instance()
    crypto = tested._crypto

    def reset_mocks() -> None:
        crypto.reset_mock()

    crypto.blind_index.side_effect = ["theBlindIndex"]
    result = tested.blind_index("theValue")
    expected = "theBlindIndex"
    assert result == expected
    exp_calls = [call.blind_index("theValue")]
    assert crypto.mock_calls == exp_calls
    reset_mocks()


@patch.object(Database, "decrypt")
def test_decrypt_row(decrypt: MagicMock) -> None:
    def reset_mocks() -> None:
        decrypt.reset_mock()

    tested = helper_instance()
    tests = [
        (
            {"email": "theSealedEmail", "name": "theSealedName", "other": 4},
            ("email", "name", "missing"),
            ["theEmail", "theName"],
            [call("theSealedEmail"), call("theSealedName")],
            {"email": "theEmail", "name": "theName", "other": 4},
        ),
        (
            {"email": None},
            ("email",),
            [""],
            [call("")],
            {"email": ""},
        ),
    ]
    for row, fields, decrypted, exp_calls, expected in tests:
        decrypt.side_effect = decrypted
        result = tested.decrypt_row(row, fields)
        assert result == expected
        assert decrypt.mock_calls == exp_calls
        reset_mocks()


@patch.object(Database, "decrypt_row")
def test_decrypt_rows(decrypt_row: MagicMock) -> None:
    def reset_mocks() -> None:
        decrypt_row.reset_mock()

    tested = helper_instance()
    decrypt_row.side_effect = [{"email": "theEmailOne"}, {"email": "theEmailTwo"}]
    result = tested.decrypt_rows([{"email": "theSealedOne"}, {"email": "theSealedTwo"}], ("email",))
    expected = [{"email": "theEmailOne"}, {"email": "theEmailTwo"}]
    assert result == expected
    exp_calls = [
        call({"email": "theSealedOne"}, ("email",)),
        call({"email": "theSealedTwo"}, ("email",)),
    ]
    assert decrypt_row.mock_calls == exp_calls
    reset_mocks()


@patch.object(Database, "_finish")
@patch.object(Database, "_run")
def test_fetch_all(run: MagicMock, finish: MagicMock) -> None:
    cursor = MagicMock()

    def reset_mocks() -> None:
        run.reset_mock()
        finish.reset_mock()
        cursor.reset_mock()

    tested = helper_instance()
    run.side_effect = [cursor]
    cursor.fetchall.side_effect = [[{"id": 1}, {"id": 2}]]
    result = tested.fetch_all("SELECT id FROM users", ("theParameter",))
    expected = [{"id": 1}, {"id": 2}]
    assert result == expected
    exp_calls = [call("SELECT id FROM users", ("theParameter",))]
    assert run.mock_calls == exp_calls
    exp_calls = [call()]
    assert finish.mock_calls == exp_calls
    exp_calls = [call.fetchall()]
    assert cursor.mock_calls == exp_calls
    reset_mocks()


@patch.object(Database, "_finish")
@patch.object(Database, "_run")
def test_fetch_one(run: MagicMock, finish: MagicMock) -> None:
    cursor = MagicMock()

    def reset_mocks() -> None:
        run.reset_mock()
        finish.reset_mock()
        cursor.reset_mock()

    tested = helper_instance()
    tests = [
        (None, None),
        ({"id": 1}, {"id": 1}),
    ]
    for row, expected in tests:
        run.side_effect = [cursor]
        cursor.fetchone.side_effect = [row]
        result = tested.fetch_one("SELECT id FROM users", ("theParameter",))
        if expected is None:
            assert result is None
        else:
            assert result == expected
        exp_calls = [call("SELECT id FROM users", ("theParameter",))]
        assert run.mock_calls == exp_calls
        exp_calls = [call()]
        assert finish.mock_calls == exp_calls
        exp_calls = [call.fetchone()]
        assert cursor.mock_calls == exp_calls
        reset_mocks()


@patch.object(Database, "_finish")
@patch.object(Database, "_run")
def test_execute(run: MagicMock, finish: MagicMock) -> None:
    cursor = MagicMock()

    def reset_mocks() -> None:
        run.reset_mock()
        finish.reset_mock()
        cursor.reset_mock()

    tested = helper_instance()

    # no result set
    cursor.description = None
    run.side_effect = [cursor]
    result = tested.execute("DELETE FROM users", ("theParameter",))
    expected = 0
    assert result == expected
    exp_calls = [call("DELETE FROM users", ("theParameter",))]
    assert run.mock_calls == exp_calls
    exp_calls = [call()]
    assert finish.mock_calls == exp_calls
    assert cursor.mock_calls == []
    reset_mocks()

    # a returned row provides the id
    cursor.description = [("id",)]
    run.side_effect = [cursor]
    cursor.fetchone.side_effect = [{"id": "7"}]
    result = tested.execute("INSERT INTO users DEFAULT VALUES RETURNING id", ("theParameter",))
    expected = 7
    assert result == expected
    exp_calls = [call("INSERT INTO users DEFAULT VALUES RETURNING id", ("theParameter",))]
    assert run.mock_calls == exp_calls
    exp_calls = [call()]
    assert finish.mock_calls == exp_calls
    exp_calls = [call.fetchone()]
    assert cursor.mock_calls == exp_calls
    reset_mocks()

    # a result set without a row
    cursor.description = [("id",)]
    run.side_effect = [cursor]
    cursor.fetchone.side_effect = [None]
    result = tested.execute("INSERT INTO users DEFAULT VALUES RETURNING id", ("theParameter",))
    expected = 0
    assert result == expected
    exp_calls = [call("INSERT INTO users DEFAULT VALUES RETURNING id", ("theParameter",))]
    assert run.mock_calls == exp_calls
    exp_calls = [call()]
    assert finish.mock_calls == exp_calls
    exp_calls = [call.fetchone()]
    assert cursor.mock_calls == exp_calls
    reset_mocks()


def test__create_schema() -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        connection.reset_mock()

    tested = helper_instance()
    result = tested._create_schema(connection)
    assert result is None
    exp_calls = [
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                email_sealed TEXT NOT NULL,
                email_hash TEXT NOT NULL UNIQUE,
                name_sealed TEXT NOT NULL DEFAULT '',
                is_admin BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_login_at TIMESTAMPTZ
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS houses (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name_sealed TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS user_houses (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                house_id BIGINT NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(user_id, house_id)
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS meters (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                house_id BIGINT NOT NULL REFERENCES houses(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                label_sealed TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS registers (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                meter_id BIGINT NOT NULL REFERENCES meters(id) ON DELETE CASCADE,
                label_sealed TEXT NOT NULL DEFAULT '',
                initial_value NUMERIC(12,2) NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS readings (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                meter_id BIGINT NOT NULL REFERENCES meters(id) ON DELETE CASCADE,
                read_on DATE NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(meter_id, read_on)
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS reading_values (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                reading_id BIGINT NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
                register_id BIGINT NOT NULL REFERENCES registers(id) ON DELETE CASCADE,
                value NUMERIC(12,2) NOT NULL,
                UNIQUE(reading_id, register_id)
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS login_links (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                email_hash TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        ),
        call.execute(
            """
            CREATE TABLE IF NOT EXISTS passkeys (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                credential_id TEXT NOT NULL UNIQUE,
                public_key TEXT NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_used_at TIMESTAMPTZ
            )
            """
        ),
        call.execute("CREATE INDEX IF NOT EXISTS ix_login_links_email_hash ON login_links(email_hash)"),
        call.execute("CREATE INDEX IF NOT EXISTS ix_sessions_token_hash ON sessions(token_hash)"),
        call.execute("CREATE INDEX IF NOT EXISTS ix_user_houses_user_id ON user_houses(user_id)"),
        call.execute("CREATE INDEX IF NOT EXISTS ix_meters_house_id ON meters(house_id)"),
        call.execute("CREATE INDEX IF NOT EXISTS ix_readings_meter_id ON readings(meter_id)"),
        call.execute("CREATE INDEX IF NOT EXISTS ix_reading_values_reading_id ON reading_values(reading_id)"),
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()


def test__migrate() -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        connection.reset_mock()

    tested = helper_instance()

    # no migration applied yet
    connection.execute.return_value.fetchone.side_effect = [None]
    result = tested._migrate(connection)
    assert result is None
    exp_calls = [
        call.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (1,)),
        call.execute().fetchone(),
        call.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (%s, %s)",
            (1, "initial encrypted usage schema"),
        ),
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()

    # all migrations already applied
    connection.execute.return_value.fetchone.side_effect = [{"?column?": 1}]
    result = tested._migrate(connection)
    assert result is None
    exp_calls = [
        call.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (1,)),
        call.execute().fetchone(),
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()


@patch.object(Database, "_seed_initial_admin")
def test__seed(seed_initial_admin: MagicMock) -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        seed_initial_admin.reset_mock()
        connection.reset_mock()

    tested = helper_instance()
    result = tested._seed(connection)
    assert result is None
    exp_calls = [call(connection)]
    assert seed_initial_admin.mock_calls == exp_calls
    assert connection.mock_calls == []
    reset_mocks()


@patch.object(Database, "encrypt")
@patch.object(Database, "blind_index")
def test__seed_initial_admin(blind_index: MagicMock, encrypt: MagicMock) -> None:
    connection = MagicMock()

    def reset_mocks() -> None:
        blind_index.reset_mock()
        encrypt.reset_mock()
        connection.reset_mock()

    tested = helper_instance()
    exp_select_call = call.execute("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",))
    exp_insert_user_call = call.execute(
        """
                INSERT INTO users(email_sealed, email_hash, name_sealed, is_admin)
                VALUES (%s, %s, %s, true)
                """,
        ("theSealedEmail", "theEmailHash", "theSealedName"),
    )

    # the user already exists: is_admin is enforced
    blind_index.side_effect = ["theEmailHash"]
    connection.execute.return_value.fetchone.side_effect = [{"id": 5}]
    result = tested._seed_initial_admin(connection)
    assert result is None
    exp_calls = [call("dbajet@gmail.com")]
    assert blind_index.mock_calls == exp_calls
    assert encrypt.mock_calls == []
    exp_calls = [
        exp_select_call,
        call.execute().fetchone(),
        call.execute("UPDATE users SET is_admin = true WHERE id = %s", (5,)),
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()

    # the user is created
    blind_index.side_effect = ["theEmailHash"]
    encrypt.side_effect = ["theSealedEmail", "theSealedName"]
    connection.execute.return_value.fetchone.side_effect = [None]
    result = tested._seed_initial_admin(connection)
    assert result is None
    exp_calls = [call("dbajet@gmail.com")]
    assert blind_index.mock_calls == exp_calls
    exp_calls = [call("dbajet@gmail.com"), call("Denis Bajet")]
    assert encrypt.mock_calls == exp_calls
    exp_calls = [
        exp_select_call,
        call.execute().fetchone(),
        exp_insert_user_call,
    ]
    assert connection.mock_calls == exp_calls
    reset_mocks()
