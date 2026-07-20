"""Correlation id: one id that ties a request together across the browser, this
response, and the server logs.

The frontend sends X-Correlation-Id on every request (frontend/src/api/client.ts).
We accept it (or make one if missing), send it back on the response, and add it
to every log line written while handling the request.

Also here: OriginVerifyMiddleware, the cost guard that pins the API's cheap
path to the CDN (details on the class).
"""
from __future__ import annotations

import hmac
import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

# A ContextVar holds the id so it stays correct across `await` calls in async
# code, where a plain variable would not.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

HEADER = "X-Correlation-Id"

# Accept only a canonical UUID, the exact shape the frontend sends via
# crypto.randomUUID (frontend/src/api/client.ts). Anything else (junk, raw bytes
# decoded to text, wrong length) is ignored and we mint our own, so the id we log
# and reflect is always a clean UUID and a malformed header cannot crash the
# request or inject into the response.
_UUID = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class CorrelationIdFilter(logging.Filter):
    """Adds the current correlation id to every log record so it can be printed."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


ORIGIN_VERIFY_HEADER = "X-Origin-Verify"

# App Runner's health checker calls this path directly, not through the CDN, so
# it can never carry the secret. It stays open — it returns a tiny fixed body,
# so it cannot be abused for data-transfer cost anyway.
_HEALTH_PATH = "/api/health"


class OriginVerifyMiddleware:
    """ASGI middleware: reject requests that did not come through the CDN.

    CloudFront adds X-Origin-Verify: <secret> to every /api/* request it
    forwards to this app (infra/cdk/lib/sierra-safe-stack.ts). A request sent
    straight to the App Runner URL lacks the header and gets a minimal 403 —
    a ~100-byte response — so hammering the public service URL cannot run up
    egress costs. This is a COST guard, not authentication: the API is public
    either way; only the cheap path is pinned to the CDN (which has a
    flat-rate plan and WAF rate limiting in front of it).
    """

    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self.secret = secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == _HEALTH_PATH:
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        sent = headers.get(ORIGIN_VERIFY_HEADER.lower().encode(), b"").decode("latin-1")
        # Constant-time comparison: a timing oracle would let the secret be
        # recovered byte by byte, which would reopen the direct path.
        if not hmac.compare_digest(sent, self.secret):
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": b'{"error":"Forbidden"}'})
            return

        await self.app(scope, receive, send)


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
        # Header bytes are latin-1 by spec, so this decode never raises. Keep the
        # value only if it is a canonical UUID; otherwise mint a fresh one.
        raw = headers.get(HEADER.lower().encode(), b"").decode("latin-1")
        incoming = raw if _UUID.match(raw) else str(uuid.uuid4())
        correlation_id.set(incoming)

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (HEADER.lower().encode(), incoming.encode())
                )
            await send(message)

        await self.app(scope, receive, send_with_header)
