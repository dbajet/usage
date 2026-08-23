from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Cookie, Request, Response

from usage.commands.auth_command import AuthCommand
from usage.commands.passkey_command import PasskeyCommand
from usage.constants.constants import Constants
from usage.handlers.api_message import ApiMessage
from usage.handlers.auth_link_request import AuthLinkRequest
from usage.handlers.auth_link_response import AuthLinkResponse
from usage.handlers.auth_verify_link_request import AuthVerifyLinkRequest
from usage.handlers.passkey_assertion_request import PasskeyAssertionRequest
from usage.handlers.passkey_options_request import PasskeyOptionsRequest
from usage.handlers.passkey_register_request import PasskeyRegisterRequest
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
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
        self._register()

    @property
    def router(self) -> APIRouter:
        return self._router

    def _register(self) -> None:
        self._router.add_api_route("/version", self._version, methods=["GET"])
        self._router.add_api_route("/session", self._session, methods=["GET"])
        self._router.add_api_route("/me", self._me, methods=["GET"])
        self._router.add_api_route("/auth/request-link", self._request_link, methods=["POST"], response_model=AuthLinkResponse)
        self._router.add_api_route("/auth/verify-link", self._verify_link, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/auth/passkey/options", self._passkey_auth_options, methods=["POST"])
        self._router.add_api_route("/auth/passkey/verify", self._passkey_auth_verify, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/auth/logout", self._logout, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/passkeys/options", self._passkey_registration_options, methods=["POST"])
        self._router.add_api_route("/passkeys", self._register_passkey, methods=["POST"], response_model=ApiMessage)
        self._router.add_api_route("/passkeys", self._list_passkeys, methods=["GET"])
        self._router.add_api_route("/passkeys/{passkey_id}", self._delete_passkey, methods=["DELETE"], response_model=ApiMessage)

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
