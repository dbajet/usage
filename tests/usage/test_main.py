from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

from fastapi import FastAPI
from fastapi.routing import APIRouter

from usage.structures.app_exception import AppException
from usage.structures.settings import Settings


def helper_settings() -> Settings:
    return Settings(
        database_url="postgresql://tests",
        encryption_key="the-key",
        dev_auth_links=True,
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


def helper_module() -> ModuleType:
    environ = {"USAGE_ENCRYPTION_KEY": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="}
    with patch.dict("os.environ", environ, clear=False):
        return importlib.import_module("usage.main")


def test___init__() -> None:
    module = helper_module()
    settings = helper_settings()
    loader = MagicMock()
    database = MagicMock()
    static_page = MagicMock()
    with (
        patch("usage.main.SettingsLoader") as settings_loader_class,
        patch("usage.main.Database") as database_class,
        patch("usage.main.StaticPage") as static_page_class,
    ):
        settings_loader_class.side_effect = [loader]
        loader.load.side_effect = [settings]
        database_class.side_effect = [database]
        static_page_class.side_effect = [static_page]
        tested = module.AppFactory()
    assert tested._settings is settings
    assert tested._database is database
    assert tested._static_dir == Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static")
    assert tested._static_page is static_page
    assert settings_loader_class.mock_calls == [call()]
    assert loader.mock_calls == [call.load()]
    assert database_class.mock_calls == [call(settings)]
    assert static_page_class.mock_calls == [call(Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static"))]
    assert database.mock_calls == []
    assert static_page.mock_calls == []


def test_create() -> None:
    module = helper_module()
    settings = helper_settings()
    loader = MagicMock()
    database = MagicMock()
    static_page = MagicMock()
    api_router = MagicMock()
    api_router.router = APIRouter()
    with (
        patch("usage.main.SettingsLoader") as settings_loader_class,
        patch("usage.main.Database") as database_class,
        patch("usage.main.StaticPage") as static_page_class,
        patch("usage.main.ApiRouter") as api_router_class,
    ):
        settings_loader_class.side_effect = [loader]
        loader.load.side_effect = [settings]
        database_class.side_effect = [database]
        static_page_class.side_effect = [static_page]
        api_router_class.side_effect = [api_router]
        tested = module.AppFactory()
        result = tested.create()
    assert isinstance(result, FastAPI)
    assert result.title == "Usage"
    exp_paths = ["/", "/docs", "/docs/oauth2-redirect", "/healthz", "/openapi.json", "/redoc", "/static"]
    assert sorted(route.path for route in result.routes) == exp_paths
    assert settings_loader_class.mock_calls == [call()]
    assert loader.mock_calls == [call.load()]
    assert database_class.mock_calls == [call(settings)]
    assert static_page_class.mock_calls == [call(Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static"))]
    assert api_router_class.mock_calls == [call(database, settings)]
    assert api_router.mock_calls == []
    assert static_page.mock_calls == []
    # the database is initialized by the lifespan only
    assert database.mock_calls == []

    async def run_lifespan(application: FastAPI) -> None:
        async with application.router.lifespan_context(application):
            pass

    email_sender = MagicMock()
    reminder_command = MagicMock()
    with (
        patch("usage.main.EmailSender") as email_sender_class,
        patch("usage.main.ReminderCommand") as reminder_command_class,
    ):
        email_sender_class.side_effect = [email_sender]
        reminder_command_class.side_effect = [reminder_command]
        asyncio.run(run_lifespan(result))
    assert database.mock_calls == [call.initialize()]
    assert email_sender_class.mock_calls == [call(settings)]
    assert reminder_command_class.mock_calls == [call(database, settings, email_sender)]
    assert email_sender.mock_calls == []
    assert reminder_command.mock_calls == [call.start()]


def test__register_middleware() -> None:
    module = helper_module()
    settings = helper_settings()
    loader = MagicMock()
    database = MagicMock()
    static_page = MagicMock()
    application = MagicMock()
    with (
        patch("usage.main.SettingsLoader") as settings_loader_class,
        patch("usage.main.Database") as database_class,
        patch("usage.main.StaticPage") as static_page_class,
    ):
        settings_loader_class.side_effect = [loader]
        loader.load.side_effect = [settings]
        database_class.side_effect = [database]
        static_page_class.side_effect = [static_page]
        tested = module.AppFactory()
    captured: dict[str, Any] = {}
    application.exception_handler.side_effect = lambda exception_class: lambda function: captured.setdefault("handler", function)
    application.middleware.side_effect = lambda kind: lambda function: captured.setdefault("middleware", function)
    result = tested._register_middleware(application)
    assert result is None
    assert settings_loader_class.mock_calls == [call()]
    assert loader.mock_calls == [call.load()]
    assert database_class.mock_calls == [call(settings)]
    assert static_page_class.mock_calls == [call(Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static"))]
    assert application.mock_calls == [call.exception_handler(AppException), call.middleware("http")]

    # the exception handler renders the application exception
    request = MagicMock()
    exception_response = asyncio.run(captured["handler"](request, AppException(418, "boom")))
    assert exception_response.status_code == 418
    assert exception_response.body == b'{"detail":"boom"}'
    assert request.mock_calls == []

    # the middleware sets the security headers
    tests = [
        (
            "/api/me",
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            },
        ),
        (
            "/",
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            },
        ),
    ]
    for path, exp_headers in tests:
        inner_response = SimpleNamespace(headers={})

        async def call_next(_: Any) -> Any:
            return inner_response

        middleware_response = asyncio.run(captured["middleware"](SimpleNamespace(url=SimpleNamespace(path=path)), call_next))
        assert middleware_response is inner_response
        assert middleware_response.headers == exp_headers
    assert database.mock_calls == []
    assert static_page.mock_calls == []


def test__index() -> None:
    module = helper_module()
    settings = helper_settings()
    loader = MagicMock()
    database = MagicMock()
    static_page = MagicMock()
    with (
        patch("usage.main.SettingsLoader") as settings_loader_class,
        patch("usage.main.Database") as database_class,
        patch("usage.main.StaticPage") as static_page_class,
    ):
        settings_loader_class.side_effect = [loader]
        loader.load.side_effect = [settings]
        database_class.side_effect = [database]
        static_page_class.side_effect = [static_page]
        tested = module.AppFactory()
    page = SimpleNamespace(body="the-page")
    static_page.render.side_effect = [page]
    result = tested._index()
    assert result is page
    assert settings_loader_class.mock_calls == [call()]
    assert loader.mock_calls == [call.load()]
    assert database_class.mock_calls == [call(settings)]
    assert static_page_class.mock_calls == [call(Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static"))]
    assert static_page.mock_calls == [call.render("index.html")]
    assert database.mock_calls == []


def test__healthz() -> None:
    module = helper_module()
    settings = helper_settings()
    loader = MagicMock()
    database = MagicMock()
    static_page = MagicMock()
    with (
        patch("usage.main.SettingsLoader") as settings_loader_class,
        patch("usage.main.Database") as database_class,
        patch("usage.main.StaticPage") as static_page_class,
    ):
        settings_loader_class.side_effect = [loader]
        loader.load.side_effect = [settings]
        database_class.side_effect = [database]
        static_page_class.side_effect = [static_page]
        tested = module.AppFactory()
    assert settings_loader_class.mock_calls == [call()]
    assert loader.mock_calls == [call.load()]
    assert database_class.mock_calls == [call(settings)]
    assert static_page_class.mock_calls == [call(Path("/media/APPLICATIONS/git_dbajet/usage/app/usage/static"))]

    def reset_mocks() -> None:
        database.reset_mock()
        static_page.reset_mock()

    tests = [True, False]
    for health in tests:
        database.health.side_effect = [health]
        result = tested._healthz()
        expected = {"ok": health}
        assert result == expected
        assert database.mock_calls == [call.health()]
        assert static_page.mock_calls == []
        reset_mocks()


def test_app() -> None:
    module = helper_module()
    result = module.app
    assert isinstance(result, FastAPI)
    assert result.title == "Usage"
