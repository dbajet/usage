from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Cookie, Request, Response

from usage.commands.admin_command import AdminCommand
from usage.commands.auth_command import AuthCommand
from usage.commands.meter_command import MeterCommand
from usage.commands.passkey_command import PasskeyCommand
from usage.commands.reading_command import ReadingCommand
from usage.commands.stats_command import StatsCommand
from usage.constants.constants import Constants
from usage.handlers.api_message import ApiMessage
from usage.handlers.auth_link_request import AuthLinkRequest
from usage.handlers.auth_link_response import AuthLinkResponse
from usage.handlers.auth_verify_link_request import AuthVerifyLinkRequest
from usage.handlers.extract_request import ExtractRequest
from usage.handlers.house_request import HouseRequest
from usage.handlers.meter_color_request import MeterColorRequest
from usage.handlers.meter_order_request import MeterOrderRequest
from usage.handlers.meter_request import MeterRequest
from usage.handlers.meter_update_request import MeterUpdateRequest
from usage.handlers.passkey_assertion_request import PasskeyAssertionRequest
from usage.handlers.passkey_options_request import PasskeyOptionsRequest
from usage.handlers.passkey_register_request import PasskeyRegisterRequest
from usage.handlers.reading_request import ReadingRequest
from usage.handlers.reading_update_request import ReadingUpdateRequest
from usage.handlers.register_request import RegisterRequest
from usage.handlers.reminder_request import ReminderRequest
from usage.handlers.register_update_request import RegisterUpdateRequest
from usage.handlers.user_house_request import UserHouseRequest
from usage.handlers.user_request import UserRequest
from usage.handlers.user_update_request import UserUpdateRequest
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.meter_reader import MeterReader
from usage.structures.app_exception import AppException
from usage.structures.settings import Settings


class ApiRouter:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings
        self._router = APIRouter(prefix="/api")
        email_sender = EmailSender(settings)
        self._auth_command = AuthCommand(database, settings, email_sender)
        self._passkey_command = PasskeyCommand(database)
        self._admin_command = AdminCommand(database)
        self._meter_command = MeterCommand(database)
        self._reading_command = ReadingCommand(database, MeterReader(settings))
        self._stats_command = StatsCommand(database)
        self._register()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register(self) -> None:
        self._router.add_api_route("/version", self._version, methods=["GET"])
        self._router.add_api_route("/session", self._session, methods=["GET"])
        self._router.add_api_route("/me", self._me, methods=["GET"])
        self._router.add_api_route("/me/reminders", self._reminder_states, methods=["GET"])
        self._router.add_api_route("/me/reminders", self._set_reminder, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/auth/request-link", self._request_link, methods=["POST"], response_model=AuthLinkResponse)
        self._router.add_api_route("/auth/verify-link", self._verify_link, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/auth/passkey/options", self._passkey_auth_options, methods=["POST"])
        self._router.add_api_route("/auth/passkey/verify", self._passkey_auth_verify, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/auth/logout", self._logout, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/passkeys/options", self._passkey_registration_options, methods=["POST"])
        self._router.add_api_route("/passkeys", self._register_passkey, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/passkeys", self._list_passkeys, methods=["GET"])
        self._router.add_api_route("/passkeys/{passkey_id}", self._delete_passkey, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/admin/overview", self._admin_overview, methods=["GET"])
        self._router.add_api_route("/users", self._create_user, methods=["POST"])
        self._router.add_api_route("/users/{user_id}", self._update_user, methods=["PUT"], response_model=ApiMessage)
        self._router.add_api_route("/users/{user_id}", self._delete_user, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/houses", self._create_house, methods=["POST"])
        self._router.add_api_route("/houses/{house_id}", self._update_house, methods=["PUT"], response_model=ApiMessage)
        self._router.add_api_route("/houses/{house_id}", self._delete_house, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/user-houses", self._set_user_house, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/me/meter-color", self._set_meter_color, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/me/meter-order", self._set_meter_order, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/meters", self._list_meters, methods=["GET"])
        self._router.add_api_route("/meters", self._create_meter, methods=["POST"])
        self._router.add_api_route("/meters/{meter_id}", self._update_meter, methods=["PUT"], response_model=ApiMessage)
        self._router.add_api_route("/meters/{meter_id}", self._delete_meter, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/meters/{meter_id}/registers", self._create_register, methods=["POST"])
        self._router.add_api_route("/registers/{register_id}", self._update_register, methods=["PUT"], response_model=ApiMessage)
        self._router.add_api_route("/registers/{register_id}", self._delete_register, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/dashboard", self._dashboard, methods=["GET"])
        self._router.add_api_route("/readings", self._list_readings, methods=["GET"])
        self._router.add_api_route("/readings", self._create_reading, methods=["POST"])
        self._router.add_api_route("/readings/extract", self._extract_reading, methods=["POST"])
        self._router.add_api_route("/readings/{reading_id}", self._update_reading, methods=["PUT"], response_model=ApiMessage)
        self._router.add_api_route("/readings/{reading_id}", self._delete_reading, methods=["DELETE"], response_model=ApiMessage)
        self._router.add_api_route("/stats/tables", self._stats_tables, methods=["GET"])
        self._router.add_api_route("/stats/series", self._stats_series, methods=["GET"])

    def _version(self) -> dict[str, str]:
        return {
            "version": os.environ.get("APP_VERSION", "dev"),
            "build": os.environ.get("BUILD_TIME", "local"),
        }

    def _session(self, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> dict[str, bool]:
        try:
            self._auth_command.user_from_token(usage_session)
        except AppException:
            return {"authenticated": False}
        return {"authenticated": True}

    def _me(self, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return user.to_dict()

    def _reminder_states(self, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._reading_command.reminder_states(user)

    def _set_reminder(
        self,
        body: ReminderRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._reading_command.set_reminder(user, body.model_dump())
        return ApiMessage(message=message["message"])

    def _request_link(self, body: AuthLinkRequest, request: Request) -> AuthLinkResponse:
        issue = self._auth_command.request_link(body.email, str(request.base_url).rstrip("/"))
        dev_link = issue.link if self._settings.dev_auth_links else ""
        # One generic answer: the response never tells whether the email has
        # an account.
        return AuthLinkResponse(message="If that email has an account, we sent it a sign-in link.", dev_link=dev_link)

    def _verify_link(self, body: AuthVerifyLinkRequest, response: Response) -> ApiMessage:
        token = self._auth_command.verify_link(body.token)
        self._set_session_cookie(response, token)
        return ApiMessage(message="Signed in.")

    def _logout(self, response: Response, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> ApiMessage:
        if usage_session:
            self._auth_command.logout(usage_session)
        response.delete_cookie(Constants.cookie_name)
        return ApiMessage(message="Signed out.")

    def _passkey_registration_options(
        self,
        request: Request,
        response: Response,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        options, challenge_token = self._passkey_command.registration_options(user, self._rp_id(request))
        self._set_challenge_cookie(response, challenge_token)
        return options

    def _register_passkey(
        self,
        body: PasskeyRegisterRequest,
        request: Request,
        response: Response,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
        usage_webauthn: str = Cookie(default="", alias=Constants.webauthn_cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._passkey_command.register(user, body.model_dump(), usage_webauthn, self._rp_id(request))
        response.delete_cookie(Constants.webauthn_cookie_name)
        return ApiMessage(message=message["message"])

    def _list_passkeys(
        self,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return {"passkeys": self._passkey_command.list_passkeys(user)}

    def _delete_passkey(
        self,
        passkey_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._passkey_command.delete_passkey(user, passkey_id)
        return ApiMessage(message=message["message"])

    def _passkey_auth_options(
        self,
        body: PasskeyOptionsRequest,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        options, challenge_token = self._passkey_command.authentication_options(body.email, self._rp_id(request))
        self._set_challenge_cookie(response, challenge_token)
        return options

    def _passkey_auth_verify(
        self,
        body: PasskeyAssertionRequest,
        request: Request,
        response: Response,
        usage_webauthn: str = Cookie(default="", alias=Constants.webauthn_cookie_name),
    ) -> ApiMessage:
        token = self._passkey_command.verify_authentication(body.model_dump(), usage_webauthn, self._rp_id(request))
        response.delete_cookie(Constants.webauthn_cookie_name)
        self._set_session_cookie(response, token)
        return ApiMessage(message="Signed in.")

    def _admin_overview(self, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._admin_command.overview(user)

    def _create_user(
        self,
        body: UserRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._admin_command.create_user(user, body.model_dump())

    def _update_user(
        self,
        user_id: int,
        body: UserUpdateRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._admin_command.update_user(user, user_id, body.model_dump())
        return ApiMessage(message=message["message"])

    def _delete_user(
        self,
        user_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._admin_command.delete_user(user, user_id)
        return ApiMessage(message=message["message"])

    def _create_house(
        self,
        body: HouseRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._admin_command.create_house(user, body.model_dump())

    def _update_house(
        self,
        house_id: int,
        body: HouseRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._admin_command.update_house(user, house_id, body.model_dump())
        return ApiMessage(message=message["message"])

    def _delete_house(
        self,
        house_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._admin_command.delete_house(user, house_id)
        return ApiMessage(message=message["message"])

    def _set_user_house(
        self,
        body: UserHouseRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._admin_command.set_user_house(user, body.model_dump())
        return ApiMessage(message=message["message"])

    def _set_meter_color(
        self,
        body: MeterColorRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.set_color(user, body.model_dump())
        return ApiMessage(message=message["message"])

    def _set_meter_order(
        self,
        body: MeterOrderRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.set_order(user, body.model_dump())
        return ApiMessage(message=message["message"])

    def _list_meters(
        self,
        house_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._meter_command.list_meters(user, house_id)

    def _create_meter(
        self,
        body: MeterRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._meter_command.create_meter(user, body.model_dump())

    def _update_meter(
        self,
        meter_id: int,
        body: MeterUpdateRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.update_meter(user, meter_id, body.model_dump())
        return ApiMessage(message=message["message"])

    def _delete_meter(
        self,
        meter_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.delete_meter(user, meter_id)
        return ApiMessage(message=message["message"])

    def _create_register(
        self,
        meter_id: int,
        body: RegisterRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._meter_command.create_register(user, meter_id, body.model_dump())

    def _update_register(
        self,
        register_id: int,
        body: RegisterUpdateRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.update_register(user, register_id, body.model_dump())
        return ApiMessage(message=message["message"])

    def _delete_register(
        self,
        register_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._meter_command.delete_register(user, register_id)
        return ApiMessage(message=message["message"])

    def _dashboard(self, usage_session: str = Cookie(default="", alias=Constants.cookie_name)) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._reading_command.dashboard(user)

    def _list_readings(
        self,
        house_id: int,
        page: int = 1,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._reading_command.list_readings(user, house_id, page)

    def _create_reading(
        self,
        body: ReadingRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._reading_command.create_reading(user, body.model_dump())

    def _extract_reading(
        self,
        body: ExtractRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._reading_command.extract(user, body.model_dump())

    def _update_reading(
        self,
        reading_id: int,
        body: ReadingUpdateRequest,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._reading_command.update_reading(user, reading_id, body.model_dump())
        return ApiMessage(message=message["message"])

    def _delete_reading(
        self,
        reading_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> ApiMessage:
        user = self._auth_command.user_from_token(usage_session)
        message = self._reading_command.delete_reading(user, reading_id)
        return ApiMessage(message=message["message"])

    def _stats_tables(
        self,
        house_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._stats_command.tables(user, house_id)

    def _stats_series(
        self,
        house_id: int,
        usage_session: str = Cookie(default="", alias=Constants.cookie_name),
    ) -> dict[str, Any]:
        user = self._auth_command.user_from_token(usage_session)
        return self._stats_command.series(user, house_id)

    def _rp_id(self, request: Request) -> str:
        return request.url.hostname or "localhost"

    def _set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            Constants.cookie_name,
            token,
            httponly=True,
            secure=self._settings.cookie_secure,
            samesite="lax",
            max_age=Constants.session_days * 24 * 60 * 60,
        )

    def _set_challenge_cookie(self, response: Response, challenge_token: str) -> None:
        response.set_cookie(
            Constants.webauthn_cookie_name,
            challenge_token,
            httponly=True,
            secure=self._settings.cookie_secure,
            samesite="lax",
            max_age=Constants.webauthn_challenge_minutes * 60,
        )
