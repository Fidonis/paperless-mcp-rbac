"""OIDC bearer-token validator backed by JWKS and OIDC discovery."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from .models import OIDCClaims

logger = logging.getLogger(__name__)

# Asymmetric signing algorithms accepted from OIDC providers. Symmetric (HS*)
# and 'none' are explicitly excluded to prevent algorithm-confusion attacks:
# an attacker controlling only the token cannot mint an HS-signed token using
# the JWKS public key as the HMAC secret.
_ALLOWED_ALGS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})


class InvalidTokenError(Exception):
    """Raised when a token cannot be validated."""


class OIDCValidator:
    """Validates OIDC access tokens against a remote JWKS endpoint.

    Discovery and JWKS responses are cached. On unknown `kid` we refresh the
    JWKS once before failing, to handle key rotation gracefully.
    """

    def __init__(
        self,
        issuer_url: str,
        audience: str,
        jwks_cache_ttl: int = 3600,
        http_timeout: float = 10.0,
    ) -> None:
        self._issuer_url = issuer_url.rstrip("/")
        self._audience = audience
        self._jwks_cache_ttl = jwks_cache_ttl
        self._http_timeout = http_timeout

        self._discovery: dict[str, Any] | None = None
        self._discovery_fetched_at: float = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0
        # Separate locks: a JWKS refresh must not serialize unrelated
        # discovery fetches, and vice versa.
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()

    async def validate(self, token: str) -> OIDCClaims:
        """Validate signature, expiry, audience and issuer; return claims."""
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            logger.info("Rejected token with malformed header")
            raise InvalidTokenError("Malformed token header") from exc

        kid = unverified_header.get("kid")
        key = await self._resolve_key(kid)
        # Derive the algorithm from the JWK itself, not from the token header.
        # Trusting the token's `alg` enables algorithm-confusion attacks.
        alg = _algorithm_for_key(key)
        issuer = await self._issuer_for_validation()

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=self._audience,
                issuer=issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                },
            )
        except ExpiredSignatureError as exc:
            logger.info("Rejected expired token")
            raise InvalidTokenError("Token expired") from exc
        except JWTError as exc:
            # Don't leak token contents into logs.
            logger.info("Token validation failed: %s", exc.__class__.__name__)
            raise InvalidTokenError("Token validation failed") from exc

        return _extract_claims(payload)

    async def _resolve_key(self, kid: str | None) -> dict[str, Any]:
        if kid is None:
            raise InvalidTokenError("Token header missing 'kid'")

        jwks = await self._get_jwks()
        key = _find_key(jwks, kid)
        if key is None:
            # Possible key rotation; force one refresh before giving up.
            logger.info("Unknown kid %s, refreshing JWKS", kid)
            jwks = await self._get_jwks(force_refresh=True)
            key = _find_key(jwks, kid)
        if key is None:
            raise InvalidTokenError("Signing key not found in JWKS")
        return key

    async def _issuer_for_validation(self) -> str:
        discovery = await self._get_discovery()
        return discovery.get("issuer", self._issuer_url)

    async def _get_discovery(self) -> dict[str, Any]:
        now = time.monotonic()
        if (
            self._discovery is not None
            and (now - self._discovery_fetched_at) < self._jwks_cache_ttl
        ):
            return self._discovery
        async with self._discovery_lock:
            if (
                self._discovery is not None
                and (time.monotonic() - self._discovery_fetched_at) < self._jwks_cache_ttl
            ):
                return self._discovery
            url = f"{self._issuer_url}/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                self._discovery = response.json()
                self._discovery_fetched_at = time.monotonic()
        return self._discovery

    async def _get_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._jwks is not None
            and (now - self._jwks_fetched_at) < self._jwks_cache_ttl
        ):
            return self._jwks
        discovery = await self._get_discovery()
        async with self._jwks_lock:
            if (
                not force_refresh
                and self._jwks is not None
                and (time.monotonic() - self._jwks_fetched_at) < self._jwks_cache_ttl
            ):
                return self._jwks
            jwks_uri = discovery.get("jwks_uri")
            if not jwks_uri:
                raise InvalidTokenError("OIDC discovery missing 'jwks_uri'")
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                response = await client.get(jwks_uri)
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_fetched_at = time.monotonic()
        return self._jwks


def _find_key(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    for key in jwks.get("keys", []):
        if key.get("kid") != kid:
            continue
        # `use` is optional in RFC 7517; if present it must be "sig" for
        # signature verification keys. Skip encryption-only keys.
        if key.get("use") not in (None, "sig"):
            continue
        return key
    return None


def _algorithm_for_key(key: dict[str, Any]) -> str:
    """Return the signing algorithm to verify with, derived from the JWK.

    Refuses symmetric (HS*) and 'none' algorithms regardless of what the JWK
    or token header claims.
    """
    alg = key.get("alg")
    if alg is None:
        # `alg` is RECOMMENDED but not REQUIRED in RFC 7517. Fall back to a
        # sensible default per key type rather than trusting the token.
        kty = key.get("kty")
        if kty == "RSA":
            return "RS256"
        if kty == "EC":
            return "ES256"
        raise InvalidTokenError(f"Unsupported JWK key type: {kty!r}")
    if alg not in _ALLOWED_ALGS:
        raise InvalidTokenError(f"JWK algorithm not permitted: {alg!r}")
    return alg


def _extract_claims(payload: dict[str, Any]) -> OIDCClaims:
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise InvalidTokenError("Token missing required 'sub' claim")
    return OIDCClaims(
        sub=sub,
        preferred_username=payload.get("preferred_username"),
    )
