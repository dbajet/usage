from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from usage.commands.auth_command import AuthCommand
from usage.structures.app_exception import AppException
from usage.structures.auth_link_issue import AuthLinkIssue
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


def helper_settings(dev_auth_links: bool = False, base_url: str = "https://usage.example.com") -> Settings:
    return Settings(
        database_url="postgresql://localhost/usage",
        encryption_key="theEncryptionKey",
        dev_auth_links=dev_auth_links,
        cookie_secure=True,
        base_url=base_url,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="theSmtpUser",
        smtp_password="theSmtpPassword",
        smtp_sender="sender@example.com",
        anthropic_api_key="theAnthropicKey",
        anthropic_model="claude-haiku-4-5-20251001",
    )


def helper_instance(dev_auth_links: bool = False, base_url: str = "https://usage.example.com") -> AuthCommand:
    return AuthCommand(MagicMock(), helper_settings(dev_auth_links, base_url), MagicMock())


def test___init__() -> None:
    database = MagicMock()
    email_sender = MagicMock()

    def reset_mocks() -> None:
        database.reset_mock()
        email_sender.reset_mock()

    settings = helper_settings()
    tested = AuthCommand(database, settings, email_sender)
    assert tested._database is database
    assert tested._settings == settings
    assert tested._email_sender is email_sender
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()


@patch.object(AuthCommand, "_pad_to_minimum")
@patch.object(AuthCommand, "_issue_link")
@patch.object(AuthCommand, "_is_valid_email")
@patch.object(AuthCommand, "_normalize_email")
def test_request_link(
    normalize_email: MagicMock,
    is_valid_email: MagicMock,
    issue_link: MagicMock,
    pad_to_minimum: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender
    tested_dev = helper_instance(dev_auth_links=True)
    database_dev = tested_dev._database
    email_sender_dev = tested_dev._email_sender
    tested_origin = helper_instance(base_url="")
    database_origin = tested_origin._database
    email_sender_origin = tested_origin._email_sender

    def reset_mocks() -> None:
        normalize_email.reset_mock()
        is_valid_email.reset_mock()
        issue_link.reset_mock()
        pad_to_minimum.reset_mock()
        database.reset_mock()
        email_sender.reset_mock()
        database_dev.reset_mock()
        email_sender_dev.reset_mock()
        database_origin.reset_mock()
        email_sender_origin.reset_mock()

    exp_user_call = call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",))
    exp_email_call = call.send(
        "user@example.com",
        "Your Usage sign-in link",
        [
            "Hello,",
            "",
            "Use this link to sign in to Usage:",
            "https://usage.example.com/?login=theToken",
            "",
            "The link works once and expires in 15 minutes.",
            "If you did not request it, you can ignore this email.",
        ],
    )
    exp_email_call_origin = call.send(
        "user@example.com",
        "Your Usage sign-in link",
        [
            "Hello,",
            "",
            "Use this link to sign in to Usage:",
            "https://origin.example.com/?login=theToken",
            "",
            "The link works once and expires in 15 minutes.",
            "If you did not request it, you can ignore this email.",
        ],
    )

    # invalid email
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [False]
    with pytest.raises(AppException) as exc_info:
        tested.request_link(" User@Example.com ", "https://origin.example.com")
    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "Enter a valid email address."
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == []
    assert pad_to_minimum.mock_calls == []
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()

    # unknown email: the same generic outcome, padded to the floor
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [None]
    result = tested.request_link(" User@Example.com ", "https://origin.example.com")
    expected = AuthLinkIssue(link="", emailed=False)
    assert result == expected
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == []
    assert pad_to_minimum.mock_calls == [call(ANY)]
    assert database.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender.mock_calls == []
    reset_mocks()

    # known email over quota: no link issued, still the generic outcome
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 7}]
    issue_link.side_effect = [""]
    result = tested.request_link(" User@Example.com ", "https://origin.example.com")
    expected = AuthLinkIssue(link="", emailed=False)
    assert result == expected
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == [call("theEmailHash")]
    assert pad_to_minimum.mock_calls == [call(ANY)]
    assert database.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender.mock_calls == []
    reset_mocks()

    # happy path, the email is sent
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 7}]
    issue_link.side_effect = ["theToken"]
    email_sender.send.side_effect = [True]
    result = tested.request_link(" User@Example.com ", "https://origin.example.com")
    expected = AuthLinkIssue(link="https://usage.example.com/?login=theToken", emailed=True)
    assert result == expected
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == [call("theEmailHash")]
    assert pad_to_minimum.mock_calls == [call(ANY)]
    assert database.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender.mock_calls == [exp_email_call]
    reset_mocks()

    # no base url configured: the request origin builds the link
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database_origin.blind_index.side_effect = ["theEmailHash"]
    database_origin.fetch_one.side_effect = [{"id": 7}]
    issue_link.side_effect = ["theToken"]
    email_sender_origin.send.side_effect = [True]
    result = tested_origin.request_link(" User@Example.com ", "https://origin.example.com")
    expected = AuthLinkIssue(link="https://origin.example.com/?login=theToken", emailed=True)
    assert result == expected
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == [call("theEmailHash")]
    assert pad_to_minimum.mock_calls == [call(ANY)]
    assert database_origin.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender_origin.mock_calls == [exp_email_call_origin]
    reset_mocks()

    # the email is not sent, dev links enabled
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database_dev.blind_index.side_effect = ["theEmailHash"]
    database_dev.fetch_one.side_effect = [{"id": 7}]
    issue_link.side_effect = ["theToken"]
    email_sender_dev.send.side_effect = [False]
    result = tested_dev.request_link(" User@Example.com ", "https://origin.example.com")
    expected = AuthLinkIssue(link="https://usage.example.com/?login=theToken", emailed=False)
    assert result == expected
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == [call("theEmailHash")]
    assert pad_to_minimum.mock_calls == [call(ANY)]
    assert database_dev.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender_dev.mock_calls == [exp_email_call]
    reset_mocks()

    # the email is not sent, dev links disabled
    normalize_email.side_effect = ["user@example.com"]
    is_valid_email.side_effect = [True]
    database.blind_index.side_effect = ["theEmailHash"]
    database.fetch_one.side_effect = [{"id": 7}]
    issue_link.side_effect = ["theToken"]
    email_sender.send.side_effect = [False]
    with pytest.raises(AppException) as exc_info:
        tested.request_link(" User@Example.com ", "https://origin.example.com")
    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "The sign-in email could not be sent. Try again later."
    assert normalize_email.mock_calls == [call(" User@Example.com ")]
    assert is_valid_email.mock_calls == [call("user@example.com")]
    assert issue_link.mock_calls == [call("theEmailHash")]
    assert pad_to_minimum.mock_calls == []
    assert database.mock_calls == [call.blind_index("user@example.com"), exp_user_call]
    assert email_sender.mock_calls == [exp_email_call]
    reset_mocks()


@patch("usage.commands.auth_command.secrets")
@patch("usage.commands.auth_command.datetime", wraps=datetime)
@patch.object(AuthCommand, "_hash")
def test__issue_link(
    hash_value: MagicMock,
    mock_datetime: MagicMock,
    mock_secrets: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender

    def reset_mocks() -> None:
        hash_value.reset_mock()
        mock_datetime.reset_mock()
        mock_secrets.reset_mock()
        database.reset_mock()
        email_sender.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
    exp_cleanup_call = call.execute("DELETE FROM login_links WHERE expires_at < %s", ("2026-08-17T12:00:00+00:00",))
    exp_count_call = call.fetch_one(
        "SELECT COUNT(*) AS count FROM login_links WHERE email_hash = %s",
        ("theEmailHash",),
    )

    # too many active links: no link, the caller keeps the generic outcome
    mock_secrets.token_urlsafe.side_effect = ["theToken"]
    database.execute.side_effect = [0]
    database.fetch_one.side_effect = [{"count": 5}]
    result = tested._issue_link("theEmailHash")
    expected = ""
    assert result == expected
    assert hash_value.mock_calls == []
    assert mock_datetime.mock_calls == [call.now(UTC), call.now(UTC)]
    assert mock_secrets.mock_calls == [call.token_urlsafe(32)]
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        exp_cleanup_call,
        exp_count_call,
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    assert email_sender.mock_calls == []
    reset_mocks()

    # happy path
    mock_secrets.token_urlsafe.side_effect = ["theToken"]
    hash_value.side_effect = ["theTokenHash"]
    database.execute.side_effect = [0, 1]
    database.fetch_one.side_effect = [{"count": 2}]
    result = tested._issue_link("theEmailHash")
    expected = "theToken"
    assert result == expected
    assert hash_value.mock_calls == [call("theToken")]
    assert mock_datetime.mock_calls == [call.now(UTC), call.now(UTC)]
    assert mock_secrets.mock_calls == [call.token_urlsafe(32)]
    exp_calls = [
        call.transaction(),
        call.transaction().__enter__(),
        exp_cleanup_call,
        exp_count_call,
        call.execute(
            "INSERT INTO login_links(email_hash, token_hash, expires_at) VALUES (%s, %s, %s)",
            ("theEmailHash", "theTokenHash", "2026-08-17T12:15:00+00:00"),
        ),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    assert email_sender.mock_calls == []
    reset_mocks()


@patch("usage.commands.auth_command.time")
def test__pad_to_minimum(mock_time: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database
    email_sender = tested._email_sender

    def reset_mocks() -> None:
        mock_time.reset_mock()
        database.reset_mock()
        email_sender.reset_mock()

    # faster than the floor: sleep the difference
    mock_time.monotonic.side_effect = [100.5]
    result = tested._pad_to_minimum(100.0)
    assert result is None
    assert mock_time.mock_calls == [call.monotonic(), call.sleep(1.0)]
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()

    # already slower than the floor: no extra wait
    mock_time.monotonic.side_effect = [102.0]
    result = tested._pad_to_minimum(100.0)
    assert result is None
    assert mock_time.mock_calls == [call.monotonic()]
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    reset_mocks()


@patch("usage.commands.auth_command.secrets")
@patch("usage.commands.auth_command.datetime", wraps=datetime)
@patch.object(AuthCommand, "_hash")
def test_verify_link(
    hash_value: MagicMock,
    mock_datetime: MagicMock,
    mock_secrets: MagicMock,
) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        hash_value.reset_mock()
        mock_datetime.reset_mock()
        mock_secrets.reset_mock()
        database.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
    exp_fetch_one = call.fetch_one(
        """
            SELECT id, email_hash FROM login_links
            WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
            """,
        ("theTokenHash", "2026-08-17T12:00:00+00:00"),
    )
    exp_user_call = call.fetch_one("SELECT id FROM users WHERE email_hash = %s", ("theEmailHash",))

    # empty token
    with pytest.raises(AppException) as exc_info:
        tested.verify_link("   ")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The sign-in link is invalid or expired."
    assert hash_value.mock_calls == []
    assert mock_datetime.mock_calls == []
    assert mock_secrets.mock_calls == []
    assert database.mock_calls == []
    reset_mocks()

    # no active link
    hash_value.side_effect = ["theTokenHash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.verify_link(" theToken ")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The sign-in link is invalid or expired."
    exp_calls = [call("theToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    assert mock_secrets.mock_calls == []
    exp_calls = [exp_fetch_one]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the account vanished since the link was issued
    hash_value.side_effect = ["theTokenHash"]
    database.fetch_one.side_effect = [{"id": 4, "email_hash": "theEmailHash"}, None]
    with pytest.raises(AppException) as exc_info:
        tested.verify_link("theToken")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "The sign-in link is invalid or expired."
    exp_calls = [call("theToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    assert mock_secrets.mock_calls == []
    exp_calls = [exp_fetch_one, exp_user_call]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    hash_value.side_effect = ["theTokenHash", "theSessionHash"]
    mock_secrets.token_urlsafe.side_effect = ["theSessionToken"]
    database.fetch_one.side_effect = [{"id": 4, "email_hash": "theEmailHash"}, {"id": 33}]
    database.execute.side_effect = [1, 2, 3]
    result = tested.verify_link("theToken")
    expected = "theSessionToken"
    assert result == expected
    exp_calls = [call("theToken"), call("theSessionToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.now(UTC), call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [call.token_urlsafe(32)]
    assert mock_secrets.mock_calls == exp_calls
    exp_calls = [
        exp_fetch_one,
        exp_user_call,
        call.transaction(),
        call.transaction().__enter__(),
        call.execute("UPDATE login_links SET used_at = now() WHERE id = %s", (4,)),
        call.execute(
            "INSERT INTO sessions(user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (33, "theSessionHash", "2026-09-16T12:00:00+00:00"),
        ),
        call.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (33,)),
        call.transaction().__exit__(None, None, None),
    ]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch("usage.commands.auth_command.datetime", wraps=datetime)
@patch.object(AuthCommand, "_hash")
def test_user_from_token(hash_value: MagicMock, mock_datetime: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        hash_value.reset_mock()
        mock_datetime.reset_mock()
        database.reset_mock()

    mock_datetime.now.side_effect = lambda tz: datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)
    exp_fetch_one = call.fetch_one(
        """
            SELECT users.id AS user_id, users.email_sealed AS email,
                   users.name_sealed AS name, users.is_admin
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = %s AND sessions.expires_at > %s
            """,
        ("theTokenHash", "2026-08-17T12:00:00+00:00"),
    )

    # no matching session
    hash_value.side_effect = ["theTokenHash"]
    database.fetch_one.side_effect = [None]
    with pytest.raises(AppException) as exc_info:
        tested.user_from_token("theToken")
    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "Authentication required."
    exp_calls = [call("theToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [exp_fetch_one]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # happy path
    row = {"user_id": 7, "email": "sealedEmail", "name": "sealedName", "is_admin": True}
    hash_value.side_effect = ["theTokenHash"]
    database.fetch_one.side_effect = [row]
    database.decrypt_row.side_effect = [{"user_id": 7, "email": "jane@example.com", "name": "Jane Doe", "is_admin": True}]
    result = tested.user_from_token("theToken")
    expected = SessionUser(user_id=7, email="jane@example.com", name="Jane Doe", is_admin=True)
    assert result == expected
    exp_calls = [call("theToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.now(UTC)]
    assert mock_datetime.mock_calls == exp_calls
    exp_calls = [exp_fetch_one, call.decrypt_row(row, ("email", "name"))]
    assert database.mock_calls == exp_calls
    reset_mocks()


@patch.object(AuthCommand, "_hash")
def test_logout(hash_value: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        hash_value.reset_mock()
        database.reset_mock()

    hash_value.side_effect = ["theTokenHash"]
    database.execute.side_effect = [0]
    result = tested.logout("theToken")
    assert result is None
    exp_calls = [call("theToken")]
    assert hash_value.mock_calls == exp_calls
    exp_calls = [call.execute("DELETE FROM sessions WHERE token_hash = %s", ("theTokenHash",))]
    assert database.mock_calls == exp_calls
    reset_mocks()


def test__normalize_email() -> None:
    tested = helper_instance()
    tests = [
        (" User@Example.com ", "user@example.com"),
        ("USER@EXAMPLE.COM", "user@example.com"),
        ("", ""),
    ]
    for email, expected in tests:
        result = tested._normalize_email(email)
        assert result == expected, f"---> {email}"


def test__is_valid_email() -> None:
    tested = helper_instance()
    tests = [
        ("user@example.com", True),
        ("user@sub.example.com", True),
        ("user@example", False),
        ("userexample.com", False),
        ("", False),
    ]
    for email, expected in tests:
        result = tested._is_valid_email(email)
        assert result is expected, f"---> {email}"


def test__hash() -> None:
    tested = helper_instance()
    result = tested._hash("theValue")
    expected = "78bfe994ef697c16140de91cdbbeee5f34136f0b50a862742d40c82578eca710"
    assert result == expected
