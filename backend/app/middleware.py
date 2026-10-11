"""Small pure-ASGI middlewares (no BaseHTTPMiddleware, so streaming and background tasks stay safe)."""
from __future__ import annotations

import json

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

class BodyTooLarge(Exception):
    """Raised from receive() when an upload body exceeds the configured limit."""

async def _send_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})

class BodyLimitMiddleware:
    """Rejects oversized uploads early: by Content-Length, and by counting bytes as they arrive."""

    def __init__(self, app: ASGIApp, max_bytes: int, limit_mb: int, path_prefix: str = "/v1/tools/") -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.path_prefix = path_prefix
        self.message = f"The files together are larger than the {limit_mb} MB limit."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not str(scope.get("path", "")).startswith(self.path_prefix)
        ):
            await self.app(scope, receive, send)
            return

        declared: int | None = None
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > self.max_bytes:
            await _send_error(send, 413, "job_too_large", self.message)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await _send_error(send, 413, "job_too_large", self.message)

class SecurityHeadersMiddleware:
    """Adds Cache-Control: no-store and X-Content-Type-Options: nosniff to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, send_wrapper)
