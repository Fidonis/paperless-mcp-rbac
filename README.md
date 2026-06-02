# paperless-mcp-rbac

A FastMCP server that exposes Paperless-ngx over **streamable HTTP** with
**OIDC-based authentication** (Keycloak-compatible) using **remote-user impersonation** —
Paperless enforces its own permission model per user.

Each request is forwarded to the Paperless REST API on behalf of the authenticated user:
no admin credentials, no server-side access filters.

```
┌──────────┐   OIDC Bearer   ┌─────────────────────┐   X-Papaia-Remote-User   ┌───────────────┐
│ MCP host │ ──────────────▶ │ paperless-mcp-rbac  │ ────────────────────────▶ │ Paperless-ngx │
│ (client) │                 │     (FastMCP)       │                           │               │
└──────────┘                 └─────────────────────┘                           └───────────────┘
                                       │
                                       ▼
                                   Keycloak
                               (JWKS, OIDC discovery)
```

## How it works

1. The MCP client sends a request with an OIDC access token (`Authorization: Bearer …`).
2. The `OIDCAuthMiddleware` validates the token against the OIDC provider's JWKS
   (signature, expiry, audience, issuer).
3. `preferred_username` is extracted from the validated claims. A missing or empty claim
   results in a 403.
4. Each MCP tool opens a short-lived `httpx` client with
   `X-Papaia-Remote-User: <username>` set on every request.
5. Paperless-ngx enforces its full permission model (ownership, sharing, group rights,
   view vs. edit) on the incoming request.
6. 403 / 404 responses from Paperless are mapped to a `ToolError`.

Paperless-ngx must be configured with `PAPERLESS_ENABLE_HTTP_REMOTE_USER=true` and
`PAPERLESS_ENABLE_HTTP_REMOTE_USER_API=true`. The reverse proxy **must** strip the
remote-user header from all external traffic — see [Security](#security).

## Layout

```
src/                       # uv project: the FastMCP server
  pyproject.toml
  uv.lock
  .venv/                   # created by `uv sync` (gitignored)
  .env                     # local config (gitignored)
  .env.example             # template for `.env`
  main.py                  # entry point (uvicorn)
  config.py                # settings (pydantic-settings, .env)
  auth/
    models.py              # OIDCClaims
    oidc.py                # JWKS-based OIDC token validator
  paperless/
    client.py              # per-request httpx.AsyncClient with remote-user header
    api.py                 # typed REST wrappers + error mapping
  mcp_app/                 # named `mcp_app` to avoid shadowing the installed `mcp` SDK
    server.py              # FastMCP instance + Starlette app wiring
    middleware.py          # ASGI auth middleware: validate OIDC, attach claims
    tools.py               # MCP tools (read + write)

docker/
  Dockerfile               # multi-stage uv-builder → python:3.12-slim
  docker-compose.yml       # mcp-server service
  .env.example

tests/
  test_auth.py             # unit tests: OIDC claims, header construction, error mapping
```

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed
- A reachable OIDC provider (e.g. Keycloak)
- A reachable Paperless-ngx instance with remote-user authentication enabled

### Install

```bash
cd src
uv sync
```

This creates `src/.venv` with all dependencies. There is no virtual environment at the
repository root.

### Configure

Copy the example env file and adjust values:

```bash
cp src/.env.example src/.env
```

The server reads `src/.env` (resolved relative to `config.py`), so keep it inside `src/`
regardless of the working directory you run from.

Important variables:

| Variable | Default | Purpose |
|---|---|---|
| `OIDC_ISSUER_URL` | — | Keycloak realm URL, e.g. `https://kc.example.com/realms/myrealm` |
| `OIDC_AUDIENCE` | `mcp-paperless` | Expected `aud` claim — must match the Keycloak audience mapper |
| `OIDC_JWKS_CACHE_TTL` | `3600` | JWKS key cache TTL in seconds |
| `PAPERLESS_URL` | `http://paperless:8000` | Paperless-ngx base URL reachable from the server |
| `PAPERLESS_REMOTE_USER_HEADER` | `X-Papaia-Remote-User` | Wire header name forwarded to Paperless |
| `PAPERLESS_USERNAME_CLAIM` | `preferred_username` | JWT claim used as the remote-user value |
| `PAPERLESS_HTTP_TIMEOUT` | `30` | HTTP timeout for Paperless calls in seconds |
| `PAPERLESS_MAX_DOWNLOAD_BYTES` | `10485760` | Maximum response size for `download_document` |
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8000` | Listen port |
| `MCP_PATH` | `/mcp` | MCP endpoint path |
| `LOG_LEVEL` | `INFO` | Logging level |

### Run

```bash
cd src
uv run python main.py
```

### Run with Docker

```bash
cp docker/.env.example docker/.env   # then edit OIDC_ISSUER_URL and PAPERLESS_URL
docker compose -f docker/docker-compose.yml up -d
```

This builds the image from `docker/Dockerfile` and starts the `mcp-server` container
on port 8000 with a `/health` health-check. Every variable is documented in
`docker/.env.example`.

## Tools

### Read tools

| Tool | Paperless endpoint |
|---|---|
| `search_documents(query, page, page_size, ordering)` | `GET /api/documents/` |
| `get_document(id)` | `GET /api/documents/{id}/` |
| `get_document_metadata(id)` | `GET /api/documents/{id}/metadata/` |
| `get_document_content(id)` | `GET /api/documents/{id}/` — returns `content` field (OCR text) |
| `download_document(id)` | `GET /api/documents/{id}/download/` (size-capped) |
| `list_tags()` | `GET /api/tags/` |
| `list_correspondents()` | `GET /api/correspondents/` |
| `list_document_types()` | `GET /api/document_types/` |
| `get_notes(id)` | `GET /api/documents/{id}/notes/` |

`page_size` is clamped to 100. For LLM use, prefer `get_document_content` over
`download_document` — it returns the extracted OCR text rather than the binary file.

### Write tools

All write operations are permission-checked by Paperless. Insufficient rights return
a `ToolError` with the Paperless status code.

| Tool | Paperless endpoint |
|---|---|
| `upload_document(file_base64, filename, title?, correspondent?, document_type?, tags?, created?)` | `POST /api/documents/post_document/` |
| `update_document(id, title?, tags?, correspondent?, document_type?, owner?, custom_fields?)` | `PATCH /api/documents/{id}/` |
| `delete_document(id)` | `DELETE /api/documents/{id}/` |
| `add_note(id, note)` | `POST /api/documents/{id}/notes/` |
| `create_tag(name, color?)` | `POST /api/tags/` |
| `create_correspondent(name)` | `POST /api/correspondents/` |

## Security

### Remote-user header isolation (mandatory)

The remote-user mechanism trusts the `X-Papaia-Remote-User` header value without further
authentication. Any request reaching Paperless with this header set is treated as that
user. Two controls are required:

1. **Strip at the reverse proxy (required).** The reverse proxy (e.g. Nginx Proxy
   Manager) must strip the header from all external traffic before it reaches Paperless.
   In NPM → the Paperless proxy host → Advanced → Custom Nginx Configuration:
   ```nginx
   proxy_set_header X-Papaia-Remote-User "";
   ```
2. **Custom header name (defense in depth).** `PAPERLESS_REMOTE_USER_HEADER` defaults
   to `X-Papaia-Remote-User`. Changing it to a value not guessable by external clients
   reduces the blast radius if the reverse proxy strip is ever misconfigured.

Network isolation: the MCP server reaches Paperless directly over the internal Docker
network (`paperless:8000`). The MCP port must not be exposed to external traffic except
through the OIDC-authenticated path.

### Token handling

- `/health` is open; every other path requires a valid Bearer token.
- Token claims (including `preferred_username`) are never written to logs.
- The server holds no Paperless admin credentials. A missing or invalid OIDC token
  results in a 401 before any Paperless call is made.

## Keycloak setup

Add an audience mapper to the Keycloak client whose access token LibreChat forwards to
this server:

- **Mapper type**: Audience
- **Included client audience**: `mcp-paperless`
- **Add to access token**: on

The `preferred_username` claim is included in Keycloak access tokens by default.
Username values must match between Keycloak and Paperless (`PAPERLESS_SOCIAL_ACCOUNT_GROUPS_SYNC`
syncs group membership on interactive OIDC login; a first interactive login is required
before the groups become active for a given user).

## Calling from an MCP client

Pass the OIDC access token in the `Authorization` header:

```bash
TOKEN=$(curl -s -X POST \
  -d "client_id=mcp-cli" -d "username=alice" -d "password=…" \
  -d "grant_type=password" \
  https://kc.example.com/realms/myrealm/protocol/openid-connect/token | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" \
     -H "Accept: text/event-stream" \
     http://localhost:8000/mcp
```
