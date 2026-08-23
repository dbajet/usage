from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from fastapi import APIRouter

from usage.handlers.api_message import ApiMessage
from usage.handlers.api_router import ApiRouter
from usage.handlers.auth_link_request import AuthLinkRequest
from usage.handlers.auth_link_response import AuthLinkResponse
from usage.handlers.auth_verify_link_request import AuthVerifyLinkRequest
from usage.handlers.extract_request import ExtractRequest
from usage.handlers.house_request import HouseRequest
from usage.handlers.meter_request import MeterRequest
from usage.handlers.meter_update_request import MeterUpdateRequest
from usage.handlers.passkey_assertion_request import PasskeyAssertionRequest
from usage.handlers.passkey_options_request import PasskeyOptionsRequest
from usage.handlers.passkey_register_request import PasskeyRegisterRequest
from usage.handlers.reading_request import ReadingRequest
from usage.handlers.reading_update_request import ReadingUpdateRequest
from usage.handlers.reading_value_input import ReadingValueInput
from usage.handlers.register_input import RegisterInput
from usage.handlers.register_request import RegisterRequest
from usage.handlers.reminder_request import ReminderRequest
from usage.handlers.register_update_request import RegisterUpdateRequest
from usage.handlers.user_house_request import UserHouseRequest
from usage.handlers.user_request import UserRequest
from usage.handlers.user_update_request import UserUpdateRequest
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
        anthropic_model="claude-opus-5",
    )


def helper_user() -> SessionUser:
    return SessionUser(user_id=7, email="jane@example.com", name="Jane Doe", is_admin=False)


def helper_instance(settings: Settings | None = None) -> tuple[ApiRouter, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    if settings is None:
        settings = helper_settings()
    auth_command = MagicMock()
    passkey_command = MagicMock()
    admin_command = MagicMock()
    meter_command = MagicMock()
    reading_command = MagicMock()
    stats_command = MagicMock()
    with (
        patch("usage.handlers.api_router.EmailSender") as email_sender_class,
        patch("usage.handlers.api_router.MeterReader") as meter_reader_class,
        patch("usage.handlers.api_router.AuthCommand") as auth_command_class,
        patch("usage.handlers.api_router.PasskeyCommand") as passkey_command_class,
        patch("usage.handlers.api_router.AdminCommand") as admin_command_class,
        patch("usage.handlers.api_router.MeterCommand") as meter_command_class,
        patch("usage.handlers.api_router.ReadingCommand") as reading_command_class,
        patch("usage.handlers.api_router.StatsCommand") as stats_command_class,
    ):
        email_sender_class.side_effect = [MagicMock()]
        meter_reader_class.side_effect = [MagicMock()]
        auth_command_class.side_effect = [auth_command]
        passkey_command_class.side_effect = [passkey_command]
        admin_command_class.side_effect = [admin_command]
        meter_command_class.side_effect = [meter_command]
        reading_command_class.side_effect = [reading_command]
        stats_command_class.side_effect = [stats_command]
        tested = ApiRouter(MagicMock(), settings)
    return tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command


def helper_request(hostname: str = "usage.example") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(hostname=hostname), base_url="http://usage.example/")


def test___init__() -> None:
    database = MagicMock()
    settings = helper_settings()
    email_sender = MagicMock()
    meter_reader = MagicMock()
    auth_command = MagicMock()
    passkey_command = MagicMock()
    admin_command = MagicMock()
    meter_command = MagicMock()
    reading_command = MagicMock()
    stats_command = MagicMock()
    with (
        patch("usage.handlers.api_router.EmailSender") as email_sender_class,
        patch("usage.handlers.api_router.MeterReader") as meter_reader_class,
        patch("usage.handlers.api_router.AuthCommand") as auth_command_class,
        patch("usage.handlers.api_router.PasskeyCommand") as passkey_command_class,
        patch("usage.handlers.api_router.AdminCommand") as admin_command_class,
        patch("usage.handlers.api_router.MeterCommand") as meter_command_class,
        patch("usage.handlers.api_router.ReadingCommand") as reading_command_class,
        patch("usage.handlers.api_router.StatsCommand") as stats_command_class,
    ):
        email_sender_class.side_effect = [email_sender]
        meter_reader_class.side_effect = [meter_reader]
        auth_command_class.side_effect = [auth_command]
        passkey_command_class.side_effect = [passkey_command]
        admin_command_class.side_effect = [admin_command]
        meter_command_class.side_effect = [meter_command]
        reading_command_class.side_effect = [reading_command]
        stats_command_class.side_effect = [stats_command]
        tested = ApiRouter(database, settings)
    assert tested._database is database
    assert tested._settings is settings
    assert isinstance(tested._router, APIRouter)
    assert tested._auth_command is auth_command
    assert tested._passkey_command is passkey_command
    assert tested._admin_command is admin_command
    assert tested._meter_command is meter_command
    assert tested._reading_command is reading_command
    assert tested._stats_command is stats_command
    assert email_sender_class.mock_calls == [call(settings)]
    assert meter_reader_class.mock_calls == [call(settings)]
    assert auth_command_class.mock_calls == [call(database, settings, email_sender)]
    assert passkey_command_class.mock_calls == [call(database)]
    assert admin_command_class.mock_calls == [call(database)]
    assert meter_command_class.mock_calls == [call(database)]
    assert reading_command_class.mock_calls == [call(database, meter_reader)]
    assert stats_command_class.mock_calls == [call(database)]
    assert database.mock_calls == []
    assert email_sender.mock_calls == []
    assert meter_reader.mock_calls == []
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []


def test_router() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    result = tested.router
    assert result is tested._router
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []


def test__register() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    result = sorted((route.path, tuple(sorted(route.methods))) for route in tested.router.routes)
    expected = [
        ("/api/admin/overview", ("GET",)),
        ("/api/auth/logout", ("POST",)),
        ("/api/auth/passkey/options", ("POST",)),
        ("/api/auth/passkey/verify", ("POST",)),
        ("/api/auth/request-link", ("POST",)),
        ("/api/auth/verify-link", ("POST",)),
        ("/api/dashboard", ("GET",)),
        ("/api/houses", ("POST",)),
        ("/api/houses/{house_id}", ("DELETE",)),
        ("/api/houses/{house_id}", ("PUT",)),
        ("/api/me", ("GET",)),
        ("/api/me/reminders", ("GET",)),
        ("/api/me/reminders", ("POST",)),
        ("/api/meters", ("GET",)),
        ("/api/meters", ("POST",)),
        ("/api/meters/{meter_id}", ("DELETE",)),
        ("/api/meters/{meter_id}", ("PUT",)),
        ("/api/meters/{meter_id}/registers", ("POST",)),
        ("/api/passkeys", ("GET",)),
        ("/api/passkeys", ("POST",)),
        ("/api/passkeys/options", ("POST",)),
        ("/api/passkeys/{passkey_id}", ("DELETE",)),
        ("/api/readings", ("GET",)),
        ("/api/readings", ("POST",)),
        ("/api/readings/extract", ("POST",)),
        ("/api/readings/{reading_id}", ("DELETE",)),
        ("/api/readings/{reading_id}", ("PUT",)),
        ("/api/registers/{register_id}", ("DELETE",)),
        ("/api/registers/{register_id}", ("PUT",)),
        ("/api/session", ("GET",)),
        ("/api/stats/series", ("GET",)),
        ("/api/stats/tables", ("GET",)),
        ("/api/user-houses", ("POST",)),
        ("/api/users", ("POST",)),
        ("/api/users/{user_id}", ("DELETE",)),
        ("/api/users/{user_id}", ("PUT",)),
        ("/api/version", ("GET",)),
    ]
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []


def test__version() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()

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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []


def test__session() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

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
        assert admin_command.mock_calls == []
        assert meter_command.mock_calls == []
        assert reading_command.mock_calls == []
        assert stats_command.mock_calls == []
        reset_mocks()


def test__me() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [helper_user()]
    result = tested._me("the-session")
    expected = {"user_id": 7, "email": "jane@example.com", "name": "Jane Doe", "is_admin": False}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__set_reminder() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.set_reminder.side_effect = [{"message": "Monthly reminder enabled for this house."}]
    result = tested._set_reminder(ReminderRequest(house_id=3, enabled=True), "the-session")
    expected = ApiMessage(message="Monthly reminder enabled for this house.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == [call.set_reminder(user, {"house_id": 3, "enabled": True})]
    assert stats_command.mock_calls == []
    reset_mocks()


def test__reminder_states() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.reminder_states.side_effect = [{"disabled_house_ids": [3]}]
    result = tested._reminder_states("the-session")
    expected = {"disabled_house_ids": [3]}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == [call.reminder_states(user)]
    assert stats_command.mock_calls == []
    reset_mocks()


def test__request_link() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    tested_prod, auth_command_prod, passkey_command_prod, admin_command_prod, meter_command_prod, reading_command_prod, stats_command_prod = helper_instance(helper_settings(dev_auth_links=False))

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
        auth_command_prod.reset_mock()
        passkey_command_prod.reset_mock()
        admin_command_prod.reset_mock()
        meter_command_prod.reset_mock()
        reading_command_prod.reset_mock()
        stats_command_prod.reset_mock()

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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()

    # dev links disabled: the link stays private
    auth_command_prod.request_link.side_effect = [AuthLinkIssue(link="https://usage.example/?login=theToken", emailed=True)]
    result = tested_prod._request_link(body, helper_request())
    expected = AuthLinkResponse(message="If that email has an account, we sent it a sign-in link.", dev_link="")
    assert result == expected
    assert auth_command_prod.mock_calls == [call.request_link("jane@example.com", "http://usage.example")]
    assert passkey_command_prod.mock_calls == []
    assert admin_command_prod.mock_calls == []
    assert meter_command_prod.mock_calls == []
    assert reading_command_prod.mock_calls == []
    assert stats_command_prod.mock_calls == []
    reset_mocks()


def test__verify_link() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
        response.reset_mock()

    auth_command.verify_link.side_effect = ["the-session-token"]
    result = tested._verify_link(AuthVerifyLinkRequest(token="theToken"), response)
    expected = ApiMessage(message="Signed in.")
    assert result == expected
    assert auth_command.mock_calls == [call.verify_link("theToken")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
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
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
        response.reset_mock()

    # with a session cookie
    auth_command.logout.side_effect = [None]
    result = tested._logout(response, "the-session")
    expected = ApiMessage(message="Signed out.")
    assert result == expected
    assert auth_command.mock_calls == [call.logout("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    assert response.mock_calls == [call.delete_cookie("usage_session")]
    reset_mocks()

    # without a session cookie
    result = tested._logout(response, "")
    expected = ApiMessage(message="Signed out.")
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    assert response.mock_calls == [call.delete_cookie("usage_session")]
    reset_mocks()


def test__passkey_registration_options() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
        response.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.registration_options.side_effect = [({"challenge": "the-challenge"}, "the-challenge-token")]
    result = tested._passkey_registration_options(helper_request(), response, "the-session")
    expected = {"challenge": "the-challenge"}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.registration_options(user, "usage.example")]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
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
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    assert response.mock_calls == [call.delete_cookie("usage_webauthn")]
    reset_mocks()


def test__list_passkeys() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.list_passkeys.side_effect = [[{"id": 1, "created_at": "2026-08-01", "last_used_at": None}]]
    result = tested._list_passkeys("the-session")
    expected = {"passkeys": [{"id": 1, "created_at": "2026-08-01", "last_used_at": None}]}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.list_passkeys(user)]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_passkey() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    passkey_command.delete_passkey.side_effect = [{"message": "Passkey removed."}]
    result = tested._delete_passkey(3, "the-session")
    expected = ApiMessage(message="Passkey removed.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == [call.delete_passkey(user, 3)]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__admin_overview() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.overview.side_effect = [{"users": [], "houses": [], "meters": []}]
    result = tested._admin_overview("the-session")
    expected = {"users": [], "houses": [], "meters": []}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == [call.overview(user)]
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__create_user() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.create_user.side_effect = [{"id": 12}]
    body = UserRequest(email="jane@example.com", name="Jane", is_admin=True)
    result = tested._create_user(body, "the-session")
    expected = {"id": 12}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.create_user(user, {"email": "jane@example.com", "name": "Jane", "is_admin": True})]
    assert admin_command.mock_calls == exp_calls
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__update_user() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.update_user.side_effect = [{"message": "User updated."}]
    body = UserUpdateRequest(name="Jane", is_admin=False)
    result = tested._update_user(9, body, "the-session")
    expected = ApiMessage(message="User updated.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.update_user(user, 9, {"name": "Jane", "is_admin": False})]
    assert admin_command.mock_calls == exp_calls
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_user() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.delete_user.side_effect = [{"message": "User deleted."}]
    result = tested._delete_user(9, "the-session")
    expected = ApiMessage(message="User deleted.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == [call.delete_user(user, 9)]
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__create_house() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.create_house.side_effect = [{"id": 3}]
    result = tested._create_house(HouseRequest(name="Fremur"), "the-session")
    expected = {"id": 3}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == [call.create_house(user, {"name": "Fremur"})]
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__update_house() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.update_house.side_effect = [{"message": "House updated."}]
    result = tested._update_house(3, HouseRequest(name="Fremur"), "the-session")
    expected = ApiMessage(message="House updated.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == [call.update_house(user, 3, {"name": "Fremur"})]
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_house() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.delete_house.side_effect = [{"message": "House deleted."}]
    result = tested._delete_house(3, "the-session")
    expected = ApiMessage(message="House deleted.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == [call.delete_house(user, 3)]
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__set_user_house() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    admin_command.set_user_house.side_effect = [{"message": "User linked to the house."}]
    body = UserHouseRequest(user_id=9, house_id=3, linked=True)
    result = tested._set_user_house(body, "the-session")
    expected = ApiMessage(message="User linked to the house.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.set_user_house(user, {"user_id": 9, "house_id": 3, "linked": True})]
    assert admin_command.mock_calls == exp_calls
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__list_meters() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.list_meters.side_effect = [{"meters": []}]
    result = tested._list_meters(3, "the-session")
    expected = {"meters": []}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == [call.list_meters(user, 3)]
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__create_meter() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.create_meter.side_effect = [{"id": 9}]
    body = MeterRequest(
        house_id=3,
        kind="electricity",
        label="EDF",
        unit="kWh",
        registers=[RegisterInput(label="HC", initial_value=100.0)],
    )
    result = tested._create_meter(body, "the-session")
    expected = {"id": 9}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [
        call.create_meter(
            user,
            {
                "house_id": 3,
                "kind": "electricity",
                "label": "EDF",
                "unit": "kWh",
                "registers": [{"label": "HC", "initial_value": 100.0}],
            },
        ),
    ]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == exp_calls
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__update_meter() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.update_meter.side_effect = [{"message": "Meter updated."}]
    body = MeterUpdateRequest(label="EDF", unit="kWh", active=False)
    result = tested._update_meter(9, body, "the-session")
    expected = ApiMessage(message="Meter updated.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.update_meter(user, 9, {"label": "EDF", "unit": "kWh", "active": False})]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == exp_calls
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_meter() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.delete_meter.side_effect = [{"message": "Meter deleted, along with its readings."}]
    result = tested._delete_meter(9, "the-session")
    expected = ApiMessage(message="Meter deleted, along with its readings.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == [call.delete_meter(user, 9)]
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__create_register() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.create_register.side_effect = [{"id": 22}]
    body = RegisterRequest(label="HP", initial_value=100.0)
    result = tested._create_register(9, body, "the-session")
    expected = {"id": 22}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.create_register(user, 9, {"label": "HP", "initial_value": 100.0})]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == exp_calls
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__update_register() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.update_register.side_effect = [{"message": "Register updated."}]
    body = RegisterUpdateRequest(label="HP", initial_value=100.0, active=False)
    result = tested._update_register(22, body, "the-session")
    expected = ApiMessage(message="Register updated.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    exp_calls = [call.update_register(user, 22, {"label": "HP", "initial_value": 100.0, "active": False})]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == exp_calls
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_register() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    meter_command.delete_register.side_effect = [{"message": "Register deleted."}]
    result = tested._delete_register(22, "the-session")
    expected = ApiMessage(message="Register deleted.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == [call.delete_register(user, 22)]
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__dashboard() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.dashboard.side_effect = [{"houses": [], "meters": []}]
    result = tested._dashboard("the-session")
    expected = {"houses": [], "meters": []}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == [call.dashboard(user)]
    assert stats_command.mock_calls == []
    reset_mocks()


def test__list_readings() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.list_readings.side_effect = [{"readings": [], "total": 0, "page": 1, "pages": 1}]
    result = tested._list_readings(3, 2, "the-session")
    expected = {"readings": [], "total": 0, "page": 1, "pages": 1}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == [call.list_readings(user, 3, 2)]
    assert stats_command.mock_calls == []
    reset_mocks()


def test__create_reading() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.create_reading.side_effect = [{"id": 31}]
    body = ReadingRequest(
        meter_id=9,
        read_on="2026-01-15",
        source="photo",
        values=[ReadingValueInput(register_id=21, value=17273.0)],
    )
    result = tested._create_reading(body, "the-session")
    expected = {"id": 31}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    exp_calls = [
        call.create_reading(
            user,
            {
                "meter_id": 9,
                "read_on": "2026-01-15",
                "source": "photo",
                "values": [{"register_id": 21, "value": 17273.0}],
            },
        ),
    ]
    assert reading_command.mock_calls == exp_calls
    assert stats_command.mock_calls == []
    reset_mocks()


def test__extract_reading() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.extract.side_effect = [{"values": [{"register_id": 21, "label": "HC", "value": 17273.0}]}]
    body = ExtractRequest(meter_id=9, image_base64="aGVsbG8=", media_type="image/jpeg")
    result = tested._extract_reading(body, "the-session")
    expected = {"values": [{"register_id": 21, "label": "HC", "value": 17273.0}]}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    exp_calls = [
        call.extract(user, {"meter_id": 9, "image_base64": "aGVsbG8=", "media_type": "image/jpeg"}),
    ]
    assert reading_command.mock_calls == exp_calls
    assert stats_command.mock_calls == []
    reset_mocks()


def test__update_reading() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.update_reading.side_effect = [{"message": "Reading updated."}]
    body = ReadingUpdateRequest(read_on="2026-01-16", values=[ReadingValueInput(register_id=21, value=17300.0)])
    result = tested._update_reading(31, body, "the-session")
    expected = ApiMessage(message="Reading updated.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    exp_calls = [
        call.update_reading(user, 31, {"read_on": "2026-01-16", "values": [{"register_id": 21, "value": 17300.0}]}),
    ]
    assert reading_command.mock_calls == exp_calls
    assert stats_command.mock_calls == []
    reset_mocks()


def test__delete_reading() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    reading_command.delete_reading.side_effect = [{"message": "Reading deleted."}]
    result = tested._delete_reading(31, "the-session")
    expected = ApiMessage(message="Reading deleted.")
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == [call.delete_reading(user, 31)]
    assert stats_command.mock_calls == []
    reset_mocks()


def test__stats_tables() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    stats_command.tables.side_effect = [{"kinds": []}]
    result = tested._stats_tables(3, "the-session")
    expected = {"kinds": []}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == [call.tables(user, 3)]
    reset_mocks()


def test__stats_series() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    user = helper_user()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()

    auth_command.user_from_token.side_effect = [user]
    stats_command.series.side_effect = [{"series": []}]
    result = tested._stats_series(3, "the-session")
    expected = {"series": []}
    assert result == expected
    assert auth_command.mock_calls == [call.user_from_token("the-session")]
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == [call.series(user, 3)]
    reset_mocks()


def test__passkey_auth_options() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
        response.reset_mock()

    passkey_command.authentication_options.side_effect = [({"challenge": "the-challenge"}, "the-challenge-token")]
    result = tested._passkey_auth_options(PasskeyOptionsRequest(email="jane@example.com"), helper_request(), response)
    expected = {"challenge": "the-challenge"}
    assert result == expected
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == [call.authentication_options("jane@example.com", "usage.example")]
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
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
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
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
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    tests = [
        ("usage.example", "usage.example"),
        (None, "localhost"),
    ]
    for hostname, expected in tests:
        result = tested._rp_id(helper_request(hostname))
        assert result == expected, f"---> {hostname}"
    assert auth_command.mock_calls == []
    assert passkey_command.mock_calls == []
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []


def test__set_session_cookie() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()


def test__set_challenge_cookie() -> None:
    tested, auth_command, passkey_command, admin_command, meter_command, reading_command, stats_command = helper_instance()
    response = MagicMock()

    def reset_mocks() -> None:
        auth_command.reset_mock()
        passkey_command.reset_mock()
        admin_command.reset_mock()
        meter_command.reset_mock()
        reading_command.reset_mock()
        stats_command.reset_mock()
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
    assert admin_command.mock_calls == []
    assert meter_command.mock_calls == []
    assert reading_command.mock_calls == []
    assert stats_command.mock_calls == []
    reset_mocks()
