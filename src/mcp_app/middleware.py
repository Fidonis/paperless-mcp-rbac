"""ASGI middleware: validate OIDC bearer, attach claims to scope.

Implemented as a low-level ASGI middleware (not Starlette's BaseHTTPMiddleware)
so that streaming responses from the streamable-HTTP transport are not buffered.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from auth.oidc import InvalidTokenError, OIDCValidator

logger = logging.getLogger(__name__)

# Key used to store OIDCClaims in scope["state"]. Also consumed by tools.py.
STATE_CLAIMS = "oidc_claims"

_PUBLIC_PATHS = frozenset({"/health", "/healthz"})


class OIDCAuthMiddleware:
    def __init__(self, app: ASGIApp, *, validator: OIDCValidator) -> None:
        self.app = app
        self._validator = validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        auth_header = _get_header(scope, b"authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            await _respond_json(send, 401, {"error": "missing_bearer_token"})
            return

        token = auth_header[7:].strip()
        try:
            claims = await self._validator.validate(token)
        except InvalidTokenError as exc:
            logger.info("OIDC validation failed: %s", exc)
            await _respond_json(send, 401, {"error": "invalid_token"})
            return
        except Exception:
            logger.exception("Unexpected error during OIDC validation")
            await _respond_json(send, 500, {"error": "auth_internal_error"})
            return

        # preferred_username is required; its absence means we cannot identify
        # the user and therefore cannot set the remote-user header safely.
        if not claims.preferred_username:
            logger.info("Token validated but preferred_username missing, sub=%s", claims.sub)
            await _respond_json(send, 403, {"error": "missing_preferred_username"})
            return

        # Starlette initializes scope["state"] as a dict on first access via
        # Request.state. Pre-populating it here is equivalent.
        state = scope.setdefault("state", {})
        state[STATE_CLAIMS] = claims

        await self.app(scope, receive, send)


def _get_header(scope: Scope, name: bytes) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return raw_value.decode("latin-1")
    return None


async def _respond_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode("ascii")),
    ]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="mcp", error="invalid_token"'))
    start: Message = {
        "type": "http.response.start",
        "status": status,
        "headers": headers,
    }
    await send(start)
    body_msg: Message = {"type": "http.response.body", "body": payload}
    await send(body_msg)
