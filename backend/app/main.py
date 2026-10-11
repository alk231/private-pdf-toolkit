"""FastAPI application factory. Run with: uvicorn app.main:app --host 0.0.0.0 --port $PORT"""
from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import Settings
from app.errors import USER_MESSAGES, AppError
from app.jobs import JobManager
from app.middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from app.ratelimit import RateLimiter
from app.routes import router

log = logging.getLogger("pdftoolkit")

def _configure_logging() -> None:
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging()

    limiter_device = RateLimiter(settings.rate_limit_per_hour)
    # Many phones share one carrier IP, so the per-IP allowance is 4x the per-device one.
    limiter_ip = RateLimiter(settings.rate_limit_per_hour * 4)

    def housekeeping() -> None:
        limiter_device.prune()
        limiter_ip.prune()

    manager = JobManager(settings, housekeeping=housekeeping)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        previous_tmp = tempfile.tempdir
        await manager.start()
        tempfile.tempdir = str(manager.spool_dir)  # upload spool files live (and die) with the workspace
        try:
            yield
        finally:
            await manager.stop()
            tempfile.tempdir = previous_tmp

    app = FastAPI(
        title="PDF Toolkit API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    app.state.manager = manager
    app.state.limiter_device = limiter_device
    app.state.limiter_dev = limiter_device  # name used by routes
    app.state.limiter_ip = limiter_ip

    # The last middleware added is the outermost one.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes, limit_mb=settings.max_job_mb)
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origins:
        # Outermost, so even 413 answers from the body limit carry the CORS headers.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["X-Device-Id", "Content-Type"],
            expose_headers=["Content-Disposition", "X-Result-Meta"],
            allow_credentials=False,
            max_age=600,
        )

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return JSONResponse(exc.body(), status_code=exc.status, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code, message = "not_found", "This address does not exist."
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "This request method is not allowed."
        else:
            code, message = "invalid_request", USER_MESSAGES["invalid_request"]
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(AppError(400, "invalid_request").body(), status_code=400)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
        return JSONResponse(AppError(500, "internal_error").body(), status_code=500)

    app.include_router(router)
    return app

app = create_app()
