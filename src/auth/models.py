"""Pydantic models used by the auth layer."""
from __future__ import annotations

from pydantic import BaseModel


class OIDCClaims(BaseModel):
    """Subset of OIDC token claims relevant to this server."""

    sub: str
    preferred_username: str | None = None
