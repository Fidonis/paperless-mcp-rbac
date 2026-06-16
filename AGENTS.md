# Developer Reference

## Project Overview

paperless-mcp-rbac is a [Model Context Protocol](https://modelcontextprotocol.io/) server that
exposes [Paperless-ngx](https://docs.paperless-ngx.com/) through OIDC per-user authentication.
Every inbound request must carry a valid Bearer token; the server validates it against the
provider's JWKS, extracts the caller's `preferred_username`, and forwards it to Paperless via
an HTTP remote-user header. Paperless then enforces its own permission model for that user.
**The server holds no admin credentials.**

Transport: FastMCP streamable-HTTP (`/mcp`). Health check: `GET /health` (auth-exempt).

---

## Architecture

```
MCP Client
  Bearer token
       │
       ▼
OIDCAuthMiddleware          ← validates token, rejects 401/403, attaches claims to scope
       │
       ▼
FastMCP tools               ← acquire claims, open per-request Paperless client
       │
       ▼
Paperless-ngx REST API      ← receives X-Papaia-Remote-User, enforces per-user ACL
```

### Key source files

| Path | Role |
|---|---|
| `src/config.py` | Pydantic settings — all tunable knobs, read from `.env` |
| `src/main.py` | Uvicorn entry point |
| `src/auth/oidc.py` | `OIDCValidator`: JWKS caching, signature/expiry/audience/issuer checks |
| `src/auth/models.py` | `OIDCClaims` Pydantic model (`sub`, `preferred_username`) |
| `src/mcp_app/middleware.py` | `OIDCAuthMiddleware`: ASGI middleware wiring auth into every request |
| `src/mcp_app/server.py` | `create_app()`: assembles middleware + FastMCP app |
| `src/mcp_app/tools.py` | `register_tools()`: `@mcp.tool` decorators for all 16 tools |
| `src/paperless/client.py` | `paperless_client()`: ephemeral `httpx.AsyncClient` factory |
| `src/paperless/api.py` | Typed async wrappers for the Paperless REST API |

---

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** package manager

---

## Development Setup

```bash
cd src
uv sync                   # resolves uv.lock → src/.venv
cp .env.example .env      # fill in OIDC_ISSUER_URL and PAPERLESS_URL at minimum
```

Run the server locally:

```bash
cd src && uv run python main.py
```

Docker:

```bash
cp docker/.env.example docker/.env   # configure
docker compose -f docker/docker-compose.yml up -d
```

---

## Testing

```bash
cd src && uv run pytest ../tests/
```

Tests are async (`pytest-asyncio`). HTTP calls are mocked with
[respx](https://github.com/lundberg/respx) — do not make real network calls in tests.

When adding a new Paperless API wrapper, add corresponding tests in `tests/` covering the
success path, 403 (forbidden), and 404 (not found).

---

## Code Style

| Tool | Command | Requirement |
|---|---|---|
| Linter | `uv run ruff check .` | must pass, no warnings |
| Type checker | `uv run mypy .` | strict mode, must pass |
| YAML | `uv run yamllint .` | must pass |

Additional rules:

- **Line endings**: LF for all `.py`, `.yml`, `.md` files (`.gitattributes` enforces this).
- **Indentation**: 4 spaces (Python), 2 spaces (YAML). No tabs outside `Makefile`s.
- **Trailing whitespace**: forbidden.
- **`# type: ignore`**: avoid. When unavoidable, include an inline comment explaining why.
- **Comments**: explain *why*, not *what*. The code says what; a comment says why it must
  be that way.

---

## Git Conventions

### Branch prefixes

```
feat/<short>        new user-facing functionality
fix/<short>         bug fix
docs/<short>        documentation only
chore/<short>       maintenance / housekeeping
ci/<short>          CI/CD configuration
refactor/<short>    refactor without behaviour change
test/<short>        tests only
```

### PR and commit titles

Titles **must** follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional-scope>): <subject>
```

- Subject: lowercase, imperative mood, no trailing period.
- Breaking changes: append `!` after type/scope.

Examples:

```
feat: add list_storage_paths tool
fix(auth): handle empty preferred_username claim
docs: document OIDC audience mapper requirement
feat!: require Python 3.13
```

### Merge strategy

PRs are **squash-merged**. The PR title becomes the sole commit on `main`.

- **Never** push directly to `main`.
- **Never** add `Co-Authored-By:` trailers to commits in this repository.
- **Never** force-push to `main` or `releases/*`.

---

## Security Constraints

1. **No secrets in the repository.** Use `.env` (gitignored). Only placeholder values in
   `.env.example` (`__GENERATED__`, `CHANGE_ME`).
2. **No admin credentials.** The server relies on remote-user impersonation. It must not
   store or proxy Paperless admin tokens.
3. **Header stripping.** The reverse proxy in front of this service **must** strip the
   remote-user header (default `X-Papaia-Remote-User`) from all inbound external traffic
   before it reaches the server. Document this requirement in any deployment example you add.
4. **Algorithm whitelist.** Only asymmetric algorithms are accepted:
   RS256, RS384, RS512, ES256, ES384, ES512. Never widen this list to include symmetric
   (HS\*) algorithms.
5. **No log leakage.** Token claims (`sub`, `preferred_username`, raw JWT) must never appear
   in log output.
6. **Pre-push audit** for changes touching secrets-adjacent files:
   ```sh
   git diff --cached | grep -iE "(password|token|secret|api[_-]?key|bearer)" || true
   ```
   Review any matches; abort if they are real values.

---

## Adding a New Tool

1. Add a typed async wrapper in `src/paperless/api.py` (follow the existing pattern).
2. Register the tool in `src/mcp_app/tools.py` with `@mcp.tool`.
3. Acquire user claims from `request.state.oidc_claims` (injected by middleware).
4. Use `paperless_client(paperless_url, remote_user_header, username)` as an async context
   manager for all HTTP calls — do not reuse clients across requests.
5. Map 403 → `ToolError("forbidden")` and 404 → `ToolError("not_found")`.
   Unexpected status codes should propagate as exceptions.
6. Write tests covering success, 403, and 404 paths.
7. Update the tool count in `README.md` if needed.

---

## Environment Variables (quick reference)

See `src/.env.example` for the full list and descriptions.

| Variable | Default | Notes |
|---|---|---|
| `OIDC_ISSUER_URL` | — | **Required.** OIDC provider base URL (JWKS auto-discovered). |
| `OIDC_AUDIENCE` | `mcp-paperless` | Must match the token's `aud` claim. |
| `OIDC_JWKS_CACHE_TTL` | `3600` | Seconds; balances key-rotation speed vs. load. |
| `PAPERLESS_URL` | `http://paperless:8000` | Internal address of the Paperless-ngx instance. |
| `PAPERLESS_REMOTE_USER_HEADER` | `X-Papaia-Remote-User` | Must be stripped by the reverse proxy. |
| `PAPERLESS_USERNAME_CLAIM` | `preferred_username` | Token claim forwarded as remote user. |
| `PAPERLESS_HTTP_TIMEOUT` | `30` | Seconds per Paperless request. |
| `PAPERLESS_MAX_DOWNLOAD_BYTES` | `10485760` | 10 MiB cap on file downloads. |
| `MCP_HOST` | `0.0.0.0` | Bind address. |
| `MCP_PORT` | `8000` | Listen port. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
