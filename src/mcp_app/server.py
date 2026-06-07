"""FastMCP server assembly: tools + ASGI auth middleware + Starlette app."""
from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth.oidc import OIDCValidator
from config import Settings

from .middleware import OIDCAuthMiddleware
from .tools import register_tools

logger = logging.getLogger(__name__)


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(settings: Settings) -> Starlette:
    """Build the ASGI app: MCP routes + auth middleware + /health."""
    validator = OIDCValidator(
        issuer_url=settings.oidc_issuer_url,
        audience=settings.oidc_audience,
        jwks_cache_ttl=settings.oidc_jwks_cache_ttl,
    )

    mcp: FastMCP = FastMCP(
        name="paperless-mcp-rbac",
        instructions=(
            "MCP server exposing Paperless-ngx via OIDC per-user authentication. "
            "Every request is forwarded to Paperless on behalf of the authenticated user; "
            "Paperless enforces its own permission model. "
            "Requires a valid OIDC bearer token in the Authorization header."
        ),
    )
    register_tools(mcp, settings)

    app: Starlette = mcp.http_app(path=settings.mcp_path, transport="streamable-http")
    app.add_route("/health", _health, methods=["GET"])
    app.add_middleware(OIDCAuthMiddleware, validator=validator)
    return app
