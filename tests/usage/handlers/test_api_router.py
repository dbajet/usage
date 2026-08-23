from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from fastapi import APIRouter

from usage.handlers.api_message import ApiMessage
from usage.handlers.api_router import ApiRouter
from usage.handlers.auth_link_request import AuthLinkRequest
from usage.handlers.auth_link_response import AuthLinkResponse
from usage.handlers.auth_verify_link_request import AuthVerifyLinkRequest
from usage.handlers.passkey_assertion_request import PasskeyAssertionRequest
from usage.handlers.passkey_options_request import PasskeyOptionsRequest
from usage.handlers.passkey_register_request import PasskeyRegisterRequest
from usage.structures.app_exception import AppException
from usage.structures.auth_link_issue import AuthLinkIssue
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


def helper_settings(dev_auth_links: bool = True) -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=dev_auth_links,
        cookie_secure=False,
        base_url="https://usage.example",
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="the-username",
        smtp_password="the-password",
        smtp_sender="sender@example.com",
        anthropic_api_key="the-anthropic-key",
        anthropic_model="claude-haiku-4-5-20251001",
    )


def helper_user() -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane Doe", is_admin=False)


def helper_instance(settings: Settings | None = None) -> tuple[ApiRouter, MagicMock, MagicMock]:
    if settings is None:
        settings = helper_settings()
    auth_command = MagicMock()
    passkey_command = MagicMock()
    with (
        patch("usage.handlers.api_router.EmailSender") as email_sender_class,
        patch("usage.handlers.api_router.AuthCommand") as auth_command_class,
        patch("usage.handlers.api_router.PasskeyCommand") as passkey_command_class,
    ):
        email_sender_class.side_effect = [MagicMock()]
        auth_command_class.side_effect = [auth_command]
        passkey_command_class.side_effect = [passkey_command]
        tested = ApiRouter(MagicMock(), settings)
    return tested, auth_command, passkey_command


def helper_request(hostname: str = "usage.example") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(hostname=hostname), base_url="http://usage.example/")


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    email_sender = MagicMock()
    auth_command = MagicMock()
    passkey_command = MagicMock()
    with (
        patch("usage.handlers.api_router.EmailSender") as email_sender_class,
        patch("usage.handlers.api_router.AuthCommand") as auth_command_class,
        patch("usage.handlers.api_router.PasskeyCommand") as passkey_command_class,
    ):
        email_sender_class.side_effect = [email_sender]
        auth_command_class.side_effect = [auth_command]
        passkey_command_class.side_effect = [passkey_command]
        tested = ApiRouter(database, settings)
    assert tested._database is database
    assert tested._settings is settings
    assert isinstance(tested._router, APIRouter)
    assert tested._auth_command is auth_command
    assert tested._passkey_command is passkey_command
    assert email_sender_class.mock_calls == [call(settings)]
    assert auth_command_class.mock_calls == [call(database, settings, email_sender)]
    assert passkey_command_class.mock_calls == [call(database)]
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []


def test_router() -> None:
    tested, auth_command, passkey_command = helper_instance()
    result = tested.router
    assert result is tested._router
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []


def test__register() -> None:
    tested, auth_command, passkey_command = helper_instance()
    result = sorted((route.path, tuple(sorted(route.methods))) for route in tested.router.routes)
    expected = [
        ("/api/auth/logout", ("POST",)),
        ("/api/auth/passkey/options", ("POST",)),
        ("/api/auth/passkey/verify", ("POST",)),
        ("/api/auth/request-link", ("POST",)),
        ("/api/auth/verify-link", ("POST",)),
        ("/api/me", ("GET",)),
        ("/api/passkeys", ("GET",)),
        ("/api/passkeys", ("POST",)),
        ("/api/passkeys/options", ("POST",)),
        ("/api/passkeys/{passkey_id}", ("DELETE",)),
        ("/api/session", ("GET",)),
        ("/api/version", ("GET",)),
    ]
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []


def test__version() -> None:
    tested, auth_command, passkey_command = helper_instance()

    # environment values
    with patch.dict("os.environ", {"APP_VERSION": "1.2.3", "BUILD_TIME": "2026-08-18T00:00:00Z"}, clear=False):
        result = tested._version()
    expected = {"version": "1.2.3", "build": "2026-08-18T00:00:00Z"}
    assert result == expected

    # default values
    with patch.dict("os.environ", {}, clear=True):
        result = tested._version()
    expected = {"version": "dev", "build": "local"}
    assert result == expected

    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []


def test__session() -> None:
    tested, auth_command, passkey_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()

    tests = [
        (user, True),
        (AppException(401, "Authentication required."), False),
    ]
    for side_effect, authenticated in tests:
        auth_command.user_from_token.side_effect = [side_effect]
        result = tested._session("the-session")
        expected = {"authenticated": authenticated}
        assert result == expected
        assert auth_command.mock_calls == [call.user_from_token("the-session")]
        assert passkey_command.mock_calls == []
        reset_mocks()


def test__me() -> None:
    tested, auth_command, passkey_command = helper_instance()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()

    auth_command.user_from_token.side_effect = [helper_user()]
    result = tested._me("the-session")
    expected = {"user_id": 7, "email": "jane@example.com", "name": "Jane Doe", "is_admin": False}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    reset_mocks()


def test__request_link() -> None:
    tested, auth_command, passkey_command = helper_instance()
    tested_prod, auth_command_prod, passkey_command_prod = helper_instance(helper_settings(dev_auth_links=False))

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        auth_command_prod.reset_mock()
        passkey_command_prod.reset_mock()

    body = AuthLinkRequest(email="jane@example.com")

    # dev links enabled: the link is echoed
    auth_command.request_link.side_effect = [AuthLinkIssue(link="https://usage.example/?login=theToken", emailed=False)]
    result = tested._request_link(body, helper_request())
    expected = AuthLinkResponse(
        message="If that email has an account, we sent it a sign-in link.",
        dev_link="https://usage.example/?login=theToken",
    )
    assert result == expected
    assert auth_command.mock_calls == [call.request_link("jane@example.com", "http://usage.example")]
    assert passkey_command.mock_calls == []
    reset_mocks()

    # dev links disabled: the link stays private
    auth_command_prod.request_link.side_effect = [AuthLinkIssue(link="https://usage.example/?login=theToken", emailed=True)]
    result = tested_prod._request_link(body, helper_request())
    expected = AuthLinkResponse(message="If that email has an account, we sent it a sign-in link.", dev_link="")
    assert result == expected
    assert auth_command_prod.mock_calls == [call.request_link("jane@example.com", "http://usage.example")]
    assert passkey_command_prod.mock_calls == []
    reset_mocks()


def test__verify_link() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    auth_command.verify_link.side_effect = ["the-session-token"]
    result = tested._verify_link(AuthVerifyLinkRequest(token="theToken"), response)
    expected = ApiMessage(message="Signed in.")
    assert result == expected
    assert auth_command.mock_calls == [call.verify_link("theToken")]
    assert passkey_command.mock_calls == []
    exp_calls = [
        call.set_cookie(
            "usage_session",
            "the-session-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=2592000,
        ),
    ]
    assert response.mock_calls == exp_calls
    reset_mocks()


def test__logout() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    # with a session cookie
    auth_command.logout.side_effect = [None]
    result = tested._logout(response, "the-session")
    expected = ApiMessage(message="Signed out.")
    assert result == expected
    assert auth_command.mock_calls == [call.logout("the-session")]
    assert passkey_command.mock_calls == []
    assert response.mock_calls == [call.delete_cookie("usage_session")]
    reset_mocks()

    # without a session cookie
    result = tested._logout(response, "")
    expected = ApiMessage(message="Signed out.")
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert response.mock_calls == [call.delete_cookie("usage_session")]
    reset_mocks()


def test__passkey_registration_options() -> None:
    tested, auth_command, passkey_command = helper_instance()
    user = helper_user()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.registration_options.side_effect = [({"challenge": "the-challenge"}, "the-challenge-token")]
    result = tested._passkey_registration_options(helper_request(), response, "the-session")
    expected = {"challenge": "the-challenge"}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.registration_options(user, "usage.example")]
    exp_calls = [
        call.set_cookie(
            "usage_webauthn",
            "the-challenge-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=300,
        ),
    ]
    assert response.mock_calls == exp_calls
    reset_mocks()


def test__register_passkey() -> None:
    tested, auth_command, passkey_command = helper_instance()
    user = helper_user()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.register.side_effect = [{"message": "Passkey registered."}]
    body = PasskeyRegisterRequest(
        credential_id="the-credential",
        attestation_object="the-attestation",
        client_data="the-client-data",
    )
    result = tested._register_passkey(body, helper_request(), response, "the-session", "the-webauthn")
    expected = ApiMessage(message="Passkey registered.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    exp_calls = [
        call.register(
            user,
            {
                "credential_id": "the-credential",
                "attestation_object": "the-attestation",
                "client_data": "the-client-data",
            },
            "the-webauthn",
            "usage.example",
        ),
    ]
    assert passkey_command.mock_calls == exp_calls
    assert response.mock_calls == [call.delete_cookie("usage_webauthn")]
    reset_mocks()


def test__list_passkeys() -> None:
    tested, auth_command, passkey_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.list_passkeys.side_effect = [[{"id": 1, "created_at": "2026-08-01", "last_used_at": None}]]
    result = tested._list_passkeys("the-session")
    expected = {"passkeys": [{"id": 1, "created_at": "2026-08-01", "last_used_at": None}]}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.list_passkeys(user)]
    reset_mocks()


def test__delete_passkey() -> None:
    tested, auth_command, passkey_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.delete_passkey.side_effect = [{"message": "Passkey removed."}]
    result = tested._delete_passkey(3, "the-session")
    expected = ApiMessage(message="Passkey removed.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.delete_passkey(user, 3)]
    reset_mocks()


def test__passkey_auth_options() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    passkey_command.authentication_options.side_effect = [({"challenge": "the-challenge"}, "the-challenge-token")]
    result = tested._passkey_auth_options(PasskeyOptionsRequest(email="jane@example.com"), helper_request(), response)
    expected = {"challenge": "the-challenge"}
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == [call.authentication_options("jane@example.com", "usage.example")]
    exp_calls = [
        call.set_cookie(
            "usage_webauthn",
            "the-challenge-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=300,
        ),
    ]
    assert response.mock_calls == exp_calls
    reset_mocks()


def test__passkey_auth_verify() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    passkey_command.verify_authentication.side_effect = ["the-session-token"]
    body = PasskeyAssertionRequest(
        credential_id="the-credential",
        authenticator_data="the-authenticator-data",
        client_data="the-client-data",
        signature="the-signature",
    )
    result = tested._passkey_auth_verify(body, helper_request(), response, "the-webauthn")
    expected = ApiMessage(message="Signed in.")
    assert result == expected
    assert auth_command.mock_calls == []
    exp_calls = [
        call.verify_authentication(
            {
                "credential_id": "the-credential",
                "authenticator_data": "the-authenticator-data",
                "client_data": "the-client-data",
                "signature": "the-signature",
            },
            "the-webauthn",
            "usage.example",
        ),
    ]
    assert passkey_command.mock_calls == exp_calls
    exp_calls = [
        call.delete_cookie("usage_webauthn"),
        call.set_cookie(
            "usage_session",
            "the-session-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=2592000,
        ),
    ]
    assert response.mock_calls == exp_calls
    reset_mocks()


def test__rp_id() -> None:
    tested, auth_command, passkey_command = helper_instance()
    tests = [
        ("usage.example", "usage.example"),
        (None, "localhost"),
    ]
    for hostname, expected in tests:
        result = tested._rp_id(helper_request(hostname))
        assert result == expected, f"---> {hostname}"
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []


def test__set_session_cookie() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    result = tested._set_session_cookie(response, "the-session-token")
    assert result is None
    exp_calls = [
        call.set_cookie(
            "usage_session",
            "the-session-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=2592000,
        ),
    ]
    assert response.mock_calls == exp_calls
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    reset_mocks()


def test__set_challenge_cookie() -> None:
    tested, auth_command, passkey_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        response.reset_mock()

    result = tested._set_challenge_cookie(response, "the-challenge-token")
    assert result is None
    exp_calls = [
        call.set_cookie(
            "usage_webauthn",
            "the-challenge-token",
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=300,
        ),
    ]
    assert response.mock_calls == exp_calls
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    reset_mocks()
