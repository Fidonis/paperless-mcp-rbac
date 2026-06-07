"""MCP tool definitions backed by Paperless-ngx REST API calls."""
from __future__ import annotations

import base64
import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

from auth.models import OIDCClaims
from config import Settings
from paperless import api
from paperless.client import paperless_client

from .middleware import STATE_CLAIMS

logger = logging.getLogger(__name__)


def _clamp_page_size(page_size: int) -> int:
    return min(max(page_size, 1), 100)


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    """Attach all Paperless-backed tools to the FastMCP instance."""

    paperless_url = settings.paperless_url
    remote_user_header = settings.paperless_remote_user_header
    http_timeout = settings.paperless_http_timeout
    max_download_bytes = settings.paperless_max_download_bytes

    # ---------------------------------------------------------------------------
    # Read tools
    # ---------------------------------------------------------------------------

    @mcp.tool
    async def search_documents(
        query: str | None = None,
        page: int = 1,
        page_size: int = 25,
        ordering: str | None = None,
    ) -> dict[str, Any]:
        """Search documents in Paperless-ngx.

        Returns only documents the authenticated user has access to.
        ``page_size`` is clamped to 100.
        """
        page_size = _clamp_page_size(page_size)
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.search_documents(
                client, query=query, page=page, page_size=page_size, ordering=ordering
            )

    @mcp.tool
    async def get_document(id: int) -> dict[str, Any]:
        """Retrieve a single document by ID."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.get_document(client, id)

    @mcp.tool
    async def get_document_metadata(id: int) -> dict[str, Any]:
        """Retrieve metadata for a single document."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.get_document_metadata(client, id)

    @mcp.tool
    async def get_document_content(id: int) -> dict[str, Any]:
        """Return the OCR-extracted text of a document.

        Preferred over ``download_document`` for LLM use: returns plain text
        rather than the binary file.
        """
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.get_document_content(client, id)

    @mcp.tool
    async def download_document(id: int) -> dict[str, Any]:
        """Download the original document file (size-capped).

        Response size is capped at the server's ``PAPERLESS_MAX_DOWNLOAD_BYTES``
        limit. Use ``get_document_content`` for OCR text instead.
        """
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.download_document(client, id, max_download_bytes)

    @mcp.tool
    async def list_tags() -> dict[str, Any]:
        """List all tags visible to the authenticated user."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.list_tags(client)

    @mcp.tool
    async def list_correspondents() -> dict[str, Any]:
        """List all correspondents visible to the authenticated user."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.list_correspondents(client)

    @mcp.tool
    async def list_document_types() -> dict[str, Any]:
        """List all document types visible to the authenticated user."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.list_document_types(client)

    @mcp.tool
    async def get_notes(id: int) -> dict[str, Any]:
        """List notes attached to a document."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.get_notes(client, id)

    # ---------------------------------------------------------------------------
    # Write tools — all permission-checked by Paperless; 403 → ToolError
    # ---------------------------------------------------------------------------

    @mcp.tool
    async def upload_document(
        file_base64: str,
        filename: str,
        title: str | None = None,
        correspondent: int | None = None,
        document_type: int | None = None,
        tags: list[int] | None = None,
        created: str | None = None,
    ) -> dict[str, Any]:
        """Upload a document to Paperless-ngx.

        ``file_base64`` must be a standard base64-encoded string of the file
        contents. ``created`` should be an ISO-8601 date string if provided.
        """
        try:
            file_bytes = base64.b64decode(file_base64, validate=True)
        except Exception as exc:
            raise ToolError("file_base64 is not valid base64") from exc

        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.upload_document(
                client,
                file_bytes=file_bytes,
                filename=filename,
                title=title,
                correspondent=correspondent,
                document_type=document_type,
                tags=tags,
                created=created,
            )

    @mcp.tool
    async def update_document(
        id: int,
        title: str | None = None,
        tags: list[int] | None = None,
        correspondent: int | None = None,
        document_type: int | None = None,
        owner: int | None = None,
        custom_fields: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update metadata of an existing document.

        Only the provided fields are updated (PATCH semantics). Paperless
        enforces edit permissions; insufficient rights return a ToolError.
        """
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.update_document(
                client,
                id,
                title=title,
                tags=tags,
                correspondent=correspondent,
                document_type=document_type,
                owner=owner,
                custom_fields=custom_fields,
            )

    @mcp.tool
    async def delete_document(id: int) -> dict[str, Any]:
        """Delete a document. Requires delete permission in Paperless."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.delete_document(client, id)

    @mcp.tool
    async def add_note(id: int, note: str) -> dict[str, Any]:
        """Add a note to a document."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.add_note(client, id, note)

    @mcp.tool
    async def create_tag(name: str, color: str | None = None) -> dict[str, Any]:
        """Create a new tag. ``color`` should be a hex color string (e.g. ``#ff0000``)."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.create_tag(client, name=name, color=color)

    @mcp.tool
    async def create_correspondent(name: str) -> dict[str, Any]:
        """Create a new correspondent."""
        claims = _require_claims()
        async with paperless_client(
            paperless_url,
            claims.preferred_username,  # type: ignore[arg-type]
            remote_user_header=remote_user_header,
            http_timeout=http_timeout,
        ) as client:
            return await api.create_correspondent(client, name=name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_claims() -> OIDCClaims:
    """Fetch the per-request OIDC claims placed in scope state by the auth middleware."""
    request = get_http_request()
    claims = getattr(request.state, STATE_CLAIMS, None)
    if not isinstance(claims, OIDCClaims) or not claims.preferred_username:
        logger.error("Tool invoked without valid OIDC claims in scope state")
        raise ToolError("authentication required")
    return claims
