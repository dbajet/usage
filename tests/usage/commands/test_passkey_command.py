from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from usage.commands.passkey_command import PasskeyCommand
from usage.structures.app_exception import AppException
from usage.structures.passkey_registration import PasskeyRegistration
from usage.structures.session_user import SessionUser


def helper_instance() -> PasskeyCommand:
    return PasskeyCommand(MagicMock())


def helper_user(name: str = "Jane Doe") -> SessionUser:
    return SessionUser(
        user_id=7,
        email="user@example.com",
        name=name,
        is_admin=False,
    )


def test___init__() -> None:
    database = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()

    tested = PasskeyCommand(database)
    assert tested._database is database
    assert database.mock_calls == []
    reset_mocks()


@patch("usage.commands.passkey_command.secrets")
@patch("usage.commands.passkey_command.WebauthnBox")
@patch.object(PasskeyCommand, "_challenge_token")
def test_registration_options(
    challenge_token: MagicMock,
    webauthn_box: MagicMock,
    mock_secrets: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        challenge_token.reset_mock()
        webauthn_box.reset_mock()
        mock_secrets.reset_mock()
        database.reset_mock()

    tests = [
        ("Jane Doe", "Jane Doe"),
        ("", "user@example.com"),
    ]
    for name, exp_display_name in tests:
        challenge_token.side_effect = ["theChallengeToken"]
        webauthn_box.encode_base64url.side_effect = ["theChallenge", "theUserHandle"]
        mock_secrets.token_bytes.side_effect = [b"theRandomBytes"]
        database.fetch_all.side_effect = [[{"credential_id": "credOne"}, {"credential_id": "credTwo"}]]
        result = tested.registration_options(helper_user(name), "example.com")
        expected = (
            {
                "rp_id": "example.com",
                "rp_name": "Usage",
                "user_id": "theUserHandle",
                "user_name": "user@example.com",
                "user_display_name": exp_display_name,
                "challenge": "theChallenge",
                "exclude_credentials": ["credOne", "credTwo"],
            },
            "theChallengeToken",
        )
        assert result == expected
        exp_calls = [call("register", "theChallenge", 7)]
        assert challenge_token.mock_calls == exp_calls
        exp_calls = [call.encode_base64url(b"theRandomBytes"), call.encode_base64url(b"7")]
        assert webauthn_box.mock_calls == exp_calls
        exp_calls = [call.token_bytes(32)]
        assert mock_secrets.mock_calls == exp_calls
        exp_calls = [
            call.fetch_all("SELECT credential_id FROM passkeys WHERE user_id = %s ORDER BY id", (7,)),
        ]
        assert database.mock_calls == exp_calls
        reset_mocks()


@patch("usage.commands.passkey_command.WebauthnBox")
@patch.object(PasskeyCommand, "_client_data")
@patch.object(PasskeyCommand, "_challenge_payload")
def test_register(
    challenge_payload: MagicMock,
    client_data: MagicMock,
    webauthn_box: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        challenge_payload.reset_mock()
        client_data.reset_mock()
        webauthn_box.reset_mock()
        database.reset_mock()

    user = helper_user()
    data = {
        "client_data": "theClientData",
        "attestation_object": "theAttestation",
        "credential_id": "theCredentialId",
    }
    exp_execute = call.execute(
        """
            INSERT INTO passkeys(user_id, credential_id, public_key, sign_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (credential_id) DO NOTHING
            RETURNING id
            """,
        (7, "theCredentialId", "thePublicKey", 3),
    )

    # the challenge belongs to another user
    challenge_payload.side_effect = [{"purpose": "register", "challenge": "theChallenge", "user_id": 9}]
    with pytest.raises(AppException) as exc_info:
        tested.register(user, data, "theChallengeToken", "example.com")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge does not belong to this account."
    exp_calls = [call("theChallengeToken", "register")]
    assert challenge_payload.mock_calls == exp_calls
    assert client_data.mock_calls == []
    assert webauthn_box.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # the credential does not match the attestation
    challenge_payload.side_effect = [{"purpose": "register", "challenge": "theChallenge", "user_id": 7}]
    client_data.side_effect = [{"type": "webauthn.create"}]
    webauthn_box.parse_attestation.side_effect = [
        PasskeyRegistration(credential_id="theOtherCredentialId", public_key="thePublicKey", sign_count=3),
    ]
    with pytest.raises(AppException) as exc_info:
        tested.register(user, data, "theChallengeToken", "example.com")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey credential does not match its attestation."
    exp_calls = [call("theChallengeToken", "register")]
    assert challenge_payload.mock_calls == exp_calls
    exp_calls = [call("theClientData", "webauthn.create", "theChallenge", "example.com")]
    assert client_data.mock_calls == exp_calls
    exp_calls = [call.parse_attestation("theAttestation", "example.com")]
    assert webauthn_box.mock_calls == exp_calls
    assert database.mock_calls == []
    reset_mocks()

    # the credential is already registered
    challenge_payload.side_effect = [{"purpose": "register", "challenge": "theChallenge", "user_id": 7}]
    client_data.side_effect = [{"type": "webauthn.create"}]
    webauthn_box.parse_attestation.side_effect = [
        PasskeyRegistration(credential_id="theCredentialId", public_key="thePublicKey", sign_count=3),
    ]
    database.execute.side_effect = [0]
    with pytest.raises(AppException) as exc_info:
        tested.register(user, data, "theChallengeToken", "example.com")
    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "This passkey is already registered."
    exp_calls = [call("theChallengeToken", "register")]
    assert challenge_payload.mock_calls == exp_calls
    exp_calls = [call("theClientData", "webauthn.create", "theChallenge", "example.com")]
    assert client_data.mock_calls == exp_calls
    exp_calls = [call.parse_attestation("theAttestation", "example.com")]
    assert webauthn_box.mock_calls == exp_calls
    exp_calls = [exp_execute]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    challenge_payload.side_effect = [{"purpose": "register", "challenge": "theChallenge", "user_id": 7}]
    client_data.side_effect = [{"type": "webauthn.create"}]
    webauthn_box.parse_attestation.side_effect = [
        PasskeyRegistration(credential_id="theCredentialId", public_key="thePublicKey", sign_count=3),
    ]
    database.execute.side_effect = [12]
    result = tested.register(user, data, "theChallengeToken", "example.com")
    expected = {"message": "Passkey registered."}
    assert result == expected
    exp_calls = [call("theChallengeToken", "register")]
    assert challenge_payload.mock_calls == exp_calls
    exp_calls = [call("theClientData", "webauthn.create", "theChallenge", "example.com")]
    assert client_data.mock_calls == exp_calls
    exp_calls = [call.parse_attestation("theAttestation", "example.com")]
    assert webauthn_box.mock_calls == exp_calls
    exp_calls = [exp_execute]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test_list_passkeys() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    database.fetch_all.side_effect = [
        [{"id": 1, "created_at": "2026-08-01", "last_used_at": None}],
    ]
    result = tested.list_passkeys(helper_user())
    expected = [{"id": 1, "created_at": "2026-08-01", "last_used_at": None}]
    assert result == expected
    exp_calls = [
        call.fetch_all(
            "SELECT id, created_at, last_used_at FROM passkeys WHERE user_id = %s ORDER BY created_at",
            (7,),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test_delete_passkey() -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    user = helper_user()

    # the passkey does not exist
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.delete_passkey(user, 3)
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "The passkey was not found."
    exp_calls = [call.fetch_one("SELECT id FROM passkeys WHERE id = %s AND user_id = %s", (3, 7))]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.fetch_one.side_effect = [{"id": 3}]
    database.execute.side_effect = [1]
    result = tested.delete_passkey(user, 3)
    expected = {"message": "Passkey removed."}
    assert result == expected
    exp_calls = [
        call.fetch_one("SELECT id FROM passkeys WHERE id = %s AND user_id = %s", (3, 7)),
        call.execute("DELETE FROM passkeys WHERE id = %s", (3,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.passkey_command.secrets")
@patch("usage.commands.passkey_command.WebauthnBox")
@patch.object(PasskeyCommand, "_challenge_token")
def test_authentication_options(
    challenge_token: MagicMock,
    webauthn_box: MagicMock,
    mock_secrets: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        challenge_token.reset_mock()
        webauthn_box.reset_mock()
        mock_secrets.reset_mock()
        database.reset_mock()

    # unknown email
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.authentication_options(" User@Example.com ", "example.com")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "No passkey is registered for this email."
    assert challenge_token.mock_calls == []
    assert webauthn_box.mock_calls == []
    assert mock_secrets.mock_calls == []
    exp_calls = [
        call.blind_index("user@example.com"),
        call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # user without credentials
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 5}]
    database.fetch_all.side_effect = [[]]
    with pytest.raises(AppException) as exc_info:
        tested.authentication_options(" User@Example.com ", "example.com")
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "No passkey is registered for this email."
    assert challenge_token.mock_calls == []
    assert webauthn_box.mock_calls == []
    assert mock_secrets.mock_calls == []
    exp_calls = [
        call.blind_index("user@example.com"),
        call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",)),
        call.fetch_all("SELECT credential_id FROM passkeys WHERE user_id = %s ORDER BY id", (5,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    challenge_token.side_effect = ["theChallengeToken"]
    webauthn_box.encode_base64url.side_effect = ["theChallenge"]
    mock_secrets.token_bytes.side_effect = [b"theRandomBytes"]
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 5}]
    database.fetch_all.side_effect = [[{"credential_id": "credOne"}, {"credential_id": "credTwo"}]]
    result = tested.authentication_options(" User@Example.com ", "example.com")
    expected = (
        {
            "rp_id": "example.com",
            "challenge": "theChallenge",
            "allow_credentials": ["credOne", "credTwo"],
        },
        "theChallengeToken",
    )
    assert result == expected
    exp_calls = [call("auth", "theChallenge", 5)]
    assert challenge_token.mock_calls == exp_calls
    exp_calls = [call.encode_base64url(b"theRandomBytes")]
    assert webauthn_box.mock_calls == exp_calls
    exp_calls = [call.token_bytes(32)]
    assert mock_secrets.mock_calls == exp_calls
    exp_calls = [
        call.blind_index("user@example.com"),
        call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",)),
        call.fetch_all("SELECT credential_id FROM passkeys WHERE user_id = %s ORDER BY id", (5,)),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.passkey_command.secrets")
@patch("usage.commands.passkey_command.datetime", wraps=datetime)
@patch("usage.commands.passkey_command.WebauthnBox")
@patch.object(PasskeyCommand, "_hash")
@patch.object(PasskeyCommand, "_client_data")
@patch.object(PasskeyCommand, "_challenge_payload")
def test_verify_authentication(
    challenge_payload: MagicMock,
    client_data: MagicMock,
    hash_value: MagicMock,
    webauthn_box: MagicMock,
    mock_datetime: MagicMock,
    mock_secrets: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        challenge_payload.reset_mock()
        client_data.reset_mock()
        hash_value.reset_mock()
        webauthn_box.reset_mock()
        mock_datetime.reset_mock()
        mock_secrets.reset_mock()
        database.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
    data = {
        "credential_id": "theCredentialId",
        "client_data": "theClientData",
        "authenticator_data": "theAuthenticatorData",
        "signature": "theSignature",
    }

    # unknown credential
    challenge_payload.side_effect = [{"purpose": "auth", "challenge": "theChallenge", "user_id": 7}]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.verify_authentication(data, "theChallengeToken", "example.com")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The passkey is not registered for this account."
    exp_calls = [call("theChallengeToken", "auth")]
    assert challenge_payload.mock_calls == exp_calls
    assert client_data.mock_calls == []
    assert hash_value.mock_calls == []
    assert webauthn_box.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert mock_secrets.mock_calls == []
    exp_calls = [
        call.fetch_one(
            "SELECT id, public_key, sign_count FROM passkeys WHERE credential_id = %s AND user_id = %s",
            ("theCredentialId", 7),
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    challenge_payload.side_effect = [{"purpose": "auth", "challenge": "theChallenge", "user_id": 7}]
    client_data.side_effect = [{"type": "webauthn.get"}]
    hash_value.side_effect = ["theTokenHash"]
    webauthn_box.decode_base64url.side_effect = [b"theAuthenticatorBytes", b"theClientBytes", b"theSignatureBytes"]
    webauthn_box.verify_assertion.side_effect = [11]
    mock_secrets.token_urlsafe.side_effect = ["theSessionToken"]
    database.fetch_one.side_effect = [{"id": 3, "public_key": "thePublicKey", "sign_count": 10}]
    database.execute.side_effect = [1, 2, 3]
    result = tested.verify_authentication(data, "theChallengeToken", "example.com")
    expected = "theSessionToken"
    assert result == expected
    exp_calls = [call("theChallengeToken", "auth")]
    assert challenge_payload.mock_calls == exp_calls
    exp_calls = [call("theClientData", "webauthn.get", "theChallenge", "example.com")]
    assert client_data.mock_calls == exp_calls
    exp_calls = [call("theSessionToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [
        call.decode_base64url("theAuthenticatorData"),
        call.decode_base64url("theClientData"),
        call.decode_base64url("theSignature"),
        call.verify_assertion(
            "thePublicKey",
            b"theAuthenticatorBytes",
            b"theClientBytes",
            b"theSignatureBytes",
            "example.com",
        ),
    ]
    assert webauthn_box.mock_calls == exp_calls
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [call.token_urlsafe(32)]
    assert mock_secrets.mock_calls == exp_calls
    exp_calls = [
        call.fetch_one(
            "SELECT id, public_key, sign_count FROM passkeys WHERE credential_id = %s AND user_id = %s",
            ("theCredentialId", 7),
        ),
        call.transaction(),
        call.transaction().__enter__(),
        call.execute(
            "UPDATE passkeys SET sign_count = %s, last_used_at = now() WHERE id = %s",
            (11, 3),
        ),
        call.execute(
            "INSERT INTO sessions(user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (7, "theTokenHash", "2026-09-16T12:00:00+00:00"),
        ),
        call.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (7,)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.passkey_command.WebauthnBox")
def test__client_data(webauthn_box: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        webauthn_box.reset_mock()
        database.reset_mock()

    # error cases
    error_tests = [
        (b"notJson", "The passkey client data is malformed."),
        (
            b'{"type": "webauthn.get", "challenge": "theChallenge", "origin": "https://example.com"}',
            "The passkey ceremony type is unexpected.",
        ),
        (
            b'{"type": "webauthn.create", "challenge": "theOtherChallenge", "origin": "https://example.com"}',
            "The passkey challenge does not match.",
        ),
        (
            b'{"type": "webauthn.create", "challenge": "theChallenge", "origin": "https://evil.com"}',
            "The passkey origin does not match this site.",
        ),
        (
            b'{"type": "webauthn.create", "challenge": "theChallenge"}',
            "The passkey origin does not match this site.",
        ),
    ]
    for client_bytes, exp_message in error_tests:
        webauthn_box.decode_base64url.side_effect = [client_bytes]
        with pytest.raises(AppException) as exc_info:
            tested._client_data("theClientData", "webauthn.create", "theChallenge", "example.com")
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == exp_message
        exp_calls = [call.decode_base64url("theClientData")]
        assert webauthn_box.mock_calls == exp_calls
        assert database.mock_calls == []
        reset_mocks()

    # happy cases
    happy_tests = [
        (
            b'{"type": "webauthn.create", "challenge": "theChallenge", "origin": "https://example.com"}',
            {"type": "webauthn.create", "challenge": "theChallenge", "origin": "https://example.com"},
        ),
        (
            b'{"type": "webauthn.create", "challenge": "theChallenge", "origin": "https://app.example.com"}',
            {"type": "webauthn.create", "challenge": "theChallenge", "origin": "https://app.example.com"},
        ),
    ]
    for client_bytes, expected in happy_tests:
        webauthn_box.decode_base64url.side_effect = [client_bytes]
        result = tested._client_data("theClientData", "webauthn.create", "theChallenge", "example.com")
        assert result == expected
        exp_calls = [call.decode_base64url("theClientData")]
        assert webauthn_box.mock_calls == exp_calls
        assert database.mock_calls == []
        reset_mocks()


@patch("usage.commands.passkey_command.datetime", wraps=datetime)
def test__challenge_token(mock_datetime: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        database.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
    database.encrypt.side_effect = ["theSealedToken"]
    result = tested._challenge_token("register", "theChallenge", 7)
    expected = "theSealedToken"
    assert result == expected
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [
        call.encrypt(
            '{"purpose": "register", "challenge": "theChallenge", "user_id": 7,'
            ' "expires_at": "2026-08-17T12:05:00+00:00"}'
        ),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.passkey_command.datetime", wraps=datetime)
def test__challenge_payload(mock_datetime: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        mock_datetime.reset_mock()
        database.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)

    # missing token
    with pytest.raises(AppException) as exc_info:
        tested._challenge_payload("", "register")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge is missing. Start again."
    assert mock_datetime.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # the token cannot be decrypted
    database.decrypt.side_effect = [AppException(500, "boom")]
    with pytest.raises(AppException) as exc_info:
        tested._challenge_payload("theChallengeToken", "register")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge is invalid. Start again."
    assert mock_datetime.mock_calls == []
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the token is not valid json
    database.decrypt.side_effect = ["notJson"]
    with pytest.raises(AppException) as exc_info:
        tested._challenge_payload("theChallengeToken", "register")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge is invalid. Start again."
    assert mock_datetime.mock_calls == []
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # wrong purpose
    database.decrypt.side_effect = ['{"purpose": "auth", "challenge": "theChallenge", "user_id": 7}']
    with pytest.raises(AppException) as exc_info:
        tested._challenge_payload("theChallengeToken", "register")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge is invalid. Start again."
    assert mock_datetime.mock_calls == []
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # expired challenge
    database.decrypt.side_effect = [
        '{"purpose": "register", "challenge": "theChallenge", "user_id": 7,'
        ' "expires_at": "2026-08-17T11:00:00+00:00"}'
    ]
    with pytest.raises(AppException) as exc_info:
        tested._challenge_payload("theChallengeToken", "register")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "The passkey challenge has expired. Start again."
    exp_calls = [call.fromisoformat("2026-08-17T11:00:00+00:00"), call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # missing expiration defaults to now
    database.decrypt.side_effect = ['{"purpose": "register", "challenge": "theChallenge", "user_id": 7}']
    result = tested._challenge_payload("theChallengeToken", "register")
    expected = {"purpose": "register", "challenge": "theChallenge", "user_id": 7}
    assert result == expected
    exp_calls = [call.now(UTC), call.fromisoformat("2026-08-17T12:00:00+00:00"), call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    database.decrypt.side_effect = [
        '{"purpose": "register", "challenge": "theChallenge", "user_id": 7,'
        ' "expires_at": "2026-08-17T13:00:00+00:00"}'
    ]
    result = tested._challenge_payload("theChallengeToken", "register")
    expected = {
        "purpose": "register",
        "challenge": "theChallenge",
        "user_id": 7,
        "expires_at": "2026-08-17T13:00:00+00:00",
    }
    assert result == expected
    exp_calls = [call.fromisoformat("2026-08-17T13:00:00+00:00"), call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [call.decrypt("theChallengeToken")]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__hash() -> None:
    tested = helper_instance()
    result = tested._hash("theValue")
    expected = "78bfe994ef697c16140de91cdbbeee5f34136f0b50a862742d40c82578eca710"
    assert result == expected
