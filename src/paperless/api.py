"""Typed REST wrappers for the Paperless-ngx API.

All functions take an ``httpx.AsyncClient`` that already has the remote-user
header set; they never add credentials themselves. HTTP 403 and 404 are mapped
to ``ToolError`` so MCP clients receive a structured error instead of a raw
HTTP exception.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError


def _handle_response(response: httpx.Response) -> Any:
    """Check status and return parsed JSON, or raise an appropriate error."""
    if response.status_code == 403:
        raise ToolError("forbidden")
    if response.status_code == 404:
        raise ToolError("not_found")
    response.raise_for_status()
    if response.status_code == 204:
        return None
    return response.json()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def search_documents(
    client: httpx.AsyncClient,
    *,
    query: str | None,
    page: int,
    page_size: int,
    ordering: str | None,
) -> Any:
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if query:
        params["search"] = query
    if ordering:
        params["ordering"] = ordering
    response = await client.get("/api/documents/", params=params)
    return _handle_response(response)


async def get_document(client: httpx.AsyncClient, doc_id: int) -> Any:
    response = await client.get(f"/api/documents/{doc_id}/")
    return _handle_response(response)


async def get_document_metadata(client: httpx.AsyncClient, doc_id: int) -> Any:
    response = await client.get(f"/api/documents/{doc_id}/metadata/")
    return _handle_response(response)


async def get_document_content(client: httpx.AsyncClient, doc_id: int) -> Any:
    response = await client.get(f"/api/documents/{doc_id}/")
    data = _handle_response(response)
    return {"id": doc_id, "content": data.get("content")}


async def download_document(
    client: httpx.AsyncClient, doc_id: int, max_bytes: int
) -> Any:
    response = await client.get(f"/api/documents/{doc_id}/download/")
    if response.status_code == 403:
        raise ToolError("forbidden")
    if response.status_code == 404:
        raise ToolError("not_found")
    response.raise_for_status()
    content = response.content
    if len(content) > max_bytes:
        raise ToolError(
            f"download exceeds limit of {max_bytes} bytes "
            f"(got {len(content)} bytes); use get_document_content for OCR text instead"
        )
    content_type = response.headers.get("content-type", "application/octet-stream")
    return {
        "id": doc_id,
        "content_type": content_type,
        "size": len(content),
        "data_base64": content.hex(),
    }


async def list_tags(client: httpx.AsyncClient) -> Any:
    response = await client.get("/api/tags/")
    return _handle_response(response)


async def list_correspondents(client: httpx.AsyncClient) -> Any:
    response = await client.get("/api/correspondents/")
    return _handle_response(response)


async def list_document_types(client: httpx.AsyncClient) -> Any:
    response = await client.get("/api/document_types/")
    return _handle_response(response)


async def get_notes(client: httpx.AsyncClient, doc_id: int) -> Any:
    response = await client.get(f"/api/documents/{doc_id}/notes/")
    return _handle_response(response)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def upload_document(
    client: httpx.AsyncClient,
    *,
    file_bytes: bytes,
    filename: str,
    title: str | None,
    correspondent: int | None,
    document_type: int | None,
    tags: list[int] | None,
    created: str | None,
) -> Any:
    files: dict[str, Any] = {"document": (filename, file_bytes)}
    data: dict[str, Any] = {}
    if title is not None:
        data["title"] = title
    if correspondent is not None:
        data["correspondent"] = str(correspondent)
    if document_type is not None:
        data["document_type"] = str(document_type)
    if tags:
        data["tags"] = [str(t) for t in tags]
    if created is not None:
        data["created"] = created
    response = await client.post("/api/documents/post_document/", files=files, data=data)
    return _handle_response(response)


async def update_document(
    client: httpx.AsyncClient,
    doc_id: int,
    *,
    title: str | None,
    tags: list[int] | None,
    correspondent: int | None,
    document_type: int | None,
    owner: int | None,
    custom_fields: list[dict[str, Any]] | None,
) -> Any:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if tags is not None:
        body["tags"] = tags
    if correspondent is not None:
        body["correspondent"] = correspondent
    if document_type is not None:
        body["document_type"] = document_type
    if owner is not None:
        body["owner"] = owner
    if custom_fields is not None:
        body["custom_fields"] = custom_fields
    response = await client.patch(f"/api/documents/{doc_id}/", json=body)
    return _handle_response(response)


async def delete_document(client: httpx.AsyncClient, doc_id: int) -> Any:
    response = await client.delete(f"/api/documents/{doc_id}/")
    if response.status_code == 403:
        raise ToolError("forbidden")
    if response.status_code == 404:
        raise ToolError("not_found")
    response.raise_for_status()
    return {"deleted": True}


async def add_note(client: httpx.AsyncClient, doc_id: int, note: str) -> Any:
    response = await client.post(f"/api/documents/{doc_id}/notes/", json={"note": note})
    return _handle_response(response)


async def create_tag(
    client: httpx.AsyncClient, *, name: str, color: str | None
) -> Any:
    body: dict[str, Any] = {"name": name}
    if color is not None:
        body["color"] = color
    response = await client.post("/api/tags/", json=body)
    return _handle_response(response)


async def create_correspondent(client: httpx.AsyncClient, *, name: str) -> Any:
    response = await client.post("/api/correspondents/", json={"name": name})
    return _handle_response(response)
