"""Application entry point.

Run from inside ``src/`` (which is the uv project root):

    uv run python main.py
"""
from __future__ import annotations

import logging

import uvicorn

from config import get_settings
from mcp_app.server import create_app


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
    )


def main() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)
    log = logging.getLogger("paperless-rbac")
    log.info(
        "Starting paperless-mcp-rbac on %s:%d (mcp path=%s)",
        settings.mcp_host,
        settings.mcp_port,
        settings.mcp_path,
    )

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
