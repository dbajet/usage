from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from usage.handlers.api_router import ApiRouter
from usage.libraries.database import Database
from usage.libraries.settings_loader import SettingsLoader
from usage.libraries.static_page import StaticPage
from usage.structures.app_exception import AppException


class AppFactory:
    def __init__(self) -> None:
        self._settings = SettingsLoader().load()
        self._database = Database(self._settings)
        self._static_dir = Path(__file__).parent / "static"
        self._static_page = StaticPage(self._static_dir)

    def create(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(application: FastAPI) -> AsyncIterator[None]:
            self._database.initialize()
            yield

        result = FastAPI(title="Usage", lifespan=lifespan)
        self._register_middleware(result)
        result.include_router(ApiRouter(self._database, self._settings).router)
        result.mount("/static", StaticFiles(directory=self._static_dir.as_posix()), name="static")
        result.add_api_route("/", self._index, methods=["GET"], response_class=HTMLResponse)
        result.add_api_route("/healthz", self._healthz, methods=["GET"])
        return result

    def _register_middleware(self, application: FastAPI) -> None:
        @application.exception_handler(AppException)
        async def app_exception_handler(request: Request, exception: AppException) -> JSONResponse:
            return JSONResponse({"detail": exception.message}, status_code=exception.status_code)

        @application.middleware("http")
        async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            if request.url.path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
            return response

    def _index(self) -> HTMLResponse:
        return self._static_page.render("index.html")

    def _healthz(self) -> dict[str, bool]:
        return {"ok": self._database.health()}


# FastAPI needs a module-level ASGI callable for uvicorn discovery.
app = AppFactory().create()
