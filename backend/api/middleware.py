"""Correlation id: one id that ties a request together across the browser, this
response, and the server logs.

The frontend sends X-Correlation-Id on every request (frontend/src/api/client.ts).
We accept it (or make one if missing), send it back on the response, and add it
to every log line written while handling the request.
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

# A ContextVar holds the id so it stays correct across `await` calls in async
# code, where a plain variable would not.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

HEADER = "X-Correlation-Id"


class CorrelationIdFilter(logging.Filter):
    """Adds the current correlation id to every log record so it can be printed."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


class CorrelationIdMiddleware:
    """ASGI middleware: read the id on the way in, add it to the response header
    on the way out."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        incoming = headers.get(HEADER.lower().encode(), b"").decode() or str(uuid.uuid4())
        correlation_id.set(incoming)

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (HEADER.lower().encode(), incoming.encode())
                )
            await send(message)

        await self.app(scope, receive, send_with_header)
