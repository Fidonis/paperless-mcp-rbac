"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_SRC_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SRC_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OIDC / Keycloak
    oidc_issuer_url: str = Field(min_length=1)
    oidc_audience: str = "mcp-paperless"
    oidc_jwks_cache_ttl: int = Field(default=3600, ge=0)

    # Paperless-ngx
    paperless_url: str = "http://paperless:8000"
    paperless_remote_user_header: str = "X-Papaia-Remote-User"
    # Informational only; the server always reads `preferred_username` from the token.
    paperless_username_claim: str = "preferred_username"
    paperless_http_timeout: float = Field(default=30.0, gt=0)
    paperless_max_download_bytes: int = Field(default=10_485_760, gt=0)  # 10 MiB

    # MCP server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    mcp_path: str = "/mcp"

    # Logging
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()  # type: ignore[call-arg]
