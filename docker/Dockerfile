# syntax=docker/dockerfile:1

# ---- builder: resolve and install dependencies into an isolated venv ----
FROM python:3.12-slim AS builder

# Pinned uv release so dependency resolution is reproducible across rebuilds.
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /usr/local/bin/uv

# UV_LINK_MODE=copy avoids hardlink warnings when the cache and target differ.
# UV_PYTHON_DOWNLOADS=never forces use of the interpreter from the base image.
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Copy only the dependency manifests first so this layer stays cached when
# application code changes but dependencies do not.
COPY src/pyproject.toml src/uv.lock ./

# --frozen fails the build if uv.lock is out of sync with pyproject.toml,
# guaranteeing the image is built against pinned, reproducible versions.
RUN uv sync --frozen --no-dev

# ---- runtime: minimal image with just the venv and the application code ----
FROM python:3.12-slim AS runtime

# PATH puts the venv first; the two PYTHON* vars keep the container quiet and
# stateless (no .pyc files, unbuffered stdout for predictable log capture).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# The MCP server needs no root capabilities; run it as an unprivileged user.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src/ /app/

USER app

# streamable-http transport default port (see MCP_PORT in docker/.env.example).
EXPOSE 8000

# /health is auth-exempt. sh -c lets the healthcheck read MCP_PORT at runtime
# so the check stays correct when the port is changed via docker/.env.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["sh", "-c", "python -c 'import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(\"http://localhost:\"+os.environ.get(\"MCP_PORT\",\"8000\")+\"/health\",timeout=3).status==200 else 1)'"]

# main.py uses relative imports, so the process must run from /app.
CMD ["python", "main.py"]
