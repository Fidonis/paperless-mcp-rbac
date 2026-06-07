"""Per-request Paperless-ngx client factory."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger(__name__)


@asynccontextmanager
async def paperless_client(
    base_url: str,
    username: str,
    *,
    remote_user_header: str,
    http_timeout: float,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a short-lived httpx client with the remote-user header set.

    Every request made through this client carries ``remote_user_header: username``
    so Paperless-ngx enforces its permission model for that user. The client
    holds no admin credentials.
    """
    client = httpx.AsyncClient(
        base_url=base_url,
        headers={remote_user_header: username, "Accept": "application/json"},
        timeout=http_timeout,
    )
    try:
        yield client
    finally:
        try:
            await client.aclose()
        except Exception:
            logger.exception("Failed to close Paperless httpx client cleanly")
