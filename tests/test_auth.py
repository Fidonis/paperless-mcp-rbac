"""Unit tests: OIDC claim extraction, algorithm selection, header construction,
API error mapping, and tool input validation."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp.exceptions import ToolError
from jose import jwt as jose_jwt

from auth.models import OIDCClaims
from auth.oidc import (
    InvalidTokenError,
    OIDCValidator,
    _algorithm_for_key,
    _extract_claims,
)
from mcp_app.tools import _clamp_page_size
from paperless.api import _handle_response
from paperless.client import paperless_client

# ---------------------------------------------------------------------------
# Helpers: RSA test key pair (generated once per session via pytest fixture)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rsa_key_pair():
    """Generate a test RSA-2048 key pair for JWT signing."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def signing_key_private(rsa_key_pair):
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    private_key, _ = rsa_key_pair
    return private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()


@pytest.fixture(scope="session")
def signing_key_public(rsa_key_pair):
    """Returns the cryptography RSAPublicKey object (not a PEM string)."""
    _, public_key = rsa_key_pair
    return public_key


def _make_token(
    private_key_pem: str,
    *,
    sub: str = "user-sub",
    preferred_username: str | None = "alice",
    aud: str = "mcp-paperless",
    iss: str = "https://keycloak.example.com/realms/test",
    exp_offset: int = 3600,
    kid: str = "test-key",
) -> str:
    now = int(time.time())
    payload: dict = {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_offset}
    if preferred_username is not None:
        payload["preferred_username"] = preferred_username
    return jose_jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": kid})


def _fake_jwks(public_key, kid: str = "test-key") -> dict:
    """Build a JWKS dict from a cryptography RSAPublicKey object."""
    import base64

    numbers = public_key.public_numbers()

    def _to_b64url(n: int) -> str:
        n_bytes = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": kid,
                "n": _to_b64url(numbers.n),
                "e": _to_b64url(numbers.e),
            }
        ]
    }


def _fake_discovery(issuer: str, jwks_uri: str = "https://example.com/jwks") -> dict:
    return {"issuer": issuer, "jwks_uri": jwks_uri}


# ---------------------------------------------------------------------------
# Section 1: _extract_claims (pure function)
# ---------------------------------------------------------------------------


def test_extract_claims_preferred_username_present():
    payload = {"sub": "user-id", "preferred_username": "alice"}
    claims = _extract_claims(payload)
    assert claims.preferred_username == "alice"
    assert claims.sub == "user-id"


def test_extract_claims_preferred_username_absent():
    payload = {"sub": "user-id"}
    claims = _extract_claims(payload)
    assert claims.preferred_username is None


def test_extract_claims_sub_missing_raises():
    with pytest.raises(InvalidTokenError, match="sub"):
        _extract_claims({})


def test_extract_claims_sub_empty_raises():
    with pytest.raises(InvalidTokenError, match="sub"):
        _extract_claims({"sub": ""})


def test_extract_claims_sub_not_string_raises():
    with pytest.raises(InvalidTokenError, match="sub"):
        _extract_claims({"sub": 123})


# ---------------------------------------------------------------------------
# Section 2: _algorithm_for_key (pure function)
# ---------------------------------------------------------------------------


def test_alg_rs256_from_jwk():
    assert _algorithm_for_key({"kty": "RSA", "alg": "RS256", "kid": "k"}) == "RS256"


def test_alg_es256_from_jwk():
    assert _algorithm_for_key({"kty": "EC", "alg": "ES256", "kid": "k"}) == "ES256"


def test_alg_fallback_rsa_kty():
    assert _algorithm_for_key({"kty": "RSA", "kid": "k"}) == "RS256"


def test_alg_fallback_ec_kty():
    assert _algorithm_for_key({"kty": "EC", "kid": "k"}) == "ES256"


def test_alg_hs256_rejected():
    with pytest.raises(InvalidTokenError, match="algorithm not permitted"):
        _algorithm_for_key({"kty": "oct", "alg": "HS256", "kid": "k"})


def test_alg_hs512_rejected():
    with pytest.raises(InvalidTokenError, match="algorithm not permitted"):
        _algorithm_for_key({"kty": "oct", "alg": "HS512", "kid": "k"})


def test_alg_none_rejected():
    with pytest.raises(InvalidTokenError):
        _algorithm_for_key({"kty": "RSA", "alg": "none", "kid": "k"})


def test_alg_unsupported_kty_raises():
    with pytest.raises(InvalidTokenError, match="Unsupported JWK key type"):
        _algorithm_for_key({"kty": "OKP", "kid": "k"})


# ---------------------------------------------------------------------------
# Section 3: OIDCValidator.validate() with mocked JWKS / discovery
# ---------------------------------------------------------------------------


def _make_validator(issuer: str = "https://keycloak.example.com/realms/test") -> OIDCValidator:
    return OIDCValidator(issuer_url=issuer, audience="mcp-paperless", jwks_cache_ttl=3600)


async def _patch_validator(
    validator: OIDCValidator,
    public_key,
    issuer: str = "https://keycloak.example.com/realms/test",
):
    """Patch _get_jwks and _get_discovery on an OIDCValidator instance."""
    jwks = _fake_jwks(public_key)
    discovery = _fake_discovery(issuer)
    validator._get_jwks = AsyncMock(return_value=jwks)
    validator._get_discovery = AsyncMock(return_value=discovery)


@pytest.mark.asyncio
async def test_validate_valid_token(signing_key_private, signing_key_public):
    issuer = "https://keycloak.example.com/realms/test"
    token = _make_token(signing_key_private, iss=issuer)
    validator = _make_validator(issuer)
    await _patch_validator(validator, signing_key_public, issuer)

    claims = await validator.validate(token)
    assert isinstance(claims, OIDCClaims)
    assert claims.preferred_username == "alice"
    assert claims.sub == "user-sub"


@pytest.mark.asyncio
async def test_validate_expired_token(signing_key_private, signing_key_public):
    issuer = "https://keycloak.example.com/realms/test"
    token = _make_token(signing_key_private, iss=issuer, exp_offset=-10)
    validator = _make_validator(issuer)
    await _patch_validator(validator, signing_key_public, issuer)

    with pytest.raises(InvalidTokenError, match="expired"):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_validate_wrong_audience(signing_key_private, signing_key_public):
    issuer = "https://keycloak.example.com/realms/test"
    token = _make_token(signing_key_private, iss=issuer, aud="other-service")
    validator = _make_validator(issuer)
    await _patch_validator(validator, signing_key_public, issuer)

    with pytest.raises(InvalidTokenError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_validate_wrong_issuer(signing_key_private, signing_key_public):
    issuer = "https://keycloak.example.com/realms/test"
    token = _make_token(signing_key_private, iss="https://evil.example.com/realms/hack")
    validator = _make_validator(issuer)
    await _patch_validator(validator, signing_key_public, issuer)

    with pytest.raises(InvalidTokenError):
        await validator.validate(token)


@pytest.mark.asyncio
async def test_validate_hs256_token_rejected(signing_key_public):
    """A token signed with HS256 must be rejected even if the JWKS is mocked to allow it."""
    issuer = "https://keycloak.example.com/realms/test"
    # Sign with symmetric algorithm
    hs_token = jose_jwt.encode(
        {"sub": "alice", "aud": "mcp-paperless", "iss": issuer,
         "iat": int(time.time()), "exp": int(time.time()) + 3600},
        "some-hmac-secret",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    validator = _make_validator(issuer)
    # JWKS contains an RSA key — the alg derived from it (RS256) won't match HS256 token
    await _patch_validator(validator, signing_key_public, issuer)

    with pytest.raises(InvalidTokenError):
        await validator.validate(hs_token)


# ---------------------------------------------------------------------------
# Section 4: header construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paperless_client_sets_remote_user_header():
    async with paperless_client(
        "http://localhost:8000",
        "alice",
        remote_user_header="X-Papaia-Remote-User",
        http_timeout=5.0,
    ) as client:
        assert client.headers["x-papaia-remote-user"] == "alice"


@pytest.mark.asyncio
async def test_paperless_client_no_admin_credentials():
    async with paperless_client(
        "http://localhost:8000",
        "alice",
        remote_user_header="X-Papaia-Remote-User",
        http_timeout=5.0,
    ) as client:
        header_names = {k.lower() for k in dict(client.headers)}
        assert "authorization" not in header_names
        assert "x-api-key" not in header_names


@pytest.mark.asyncio
async def test_paperless_client_accept_json():
    async with paperless_client(
        "http://localhost:8000",
        "alice",
        remote_user_header="X-Papaia-Remote-User",
        http_timeout=5.0,
    ) as client:
        assert "application/json" in client.headers.get("accept", "")


# ---------------------------------------------------------------------------
# Section 5: API error mapping
# ---------------------------------------------------------------------------


def _mock_response(status: int, content: bytes = b"{}") -> httpx.Response:
    request = httpx.Request("GET", "http://paperless.test/api/")
    return httpx.Response(status, content=content, request=request)


def test_handle_response_403_raises_forbidden():
    with pytest.raises(ToolError, match="forbidden"):
        _handle_response(_mock_response(403))


def test_handle_response_404_raises_not_found():
    with pytest.raises(ToolError, match="not_found"):
        _handle_response(_mock_response(404))


def test_handle_response_200_returns_json():
    result = _handle_response(_mock_response(200, b'{"id": 1}'))
    assert result == {"id": 1}


def test_handle_response_204_returns_none():
    result = _handle_response(_mock_response(204, b""))
    assert result is None


def test_handle_response_500_raises_http_error():
    with pytest.raises(httpx.HTTPStatusError):
        _handle_response(_mock_response(500))


# ---------------------------------------------------------------------------
# Section 6: tool input validation
# ---------------------------------------------------------------------------


def test_clamp_page_size_minimum():
    assert _clamp_page_size(0) == 1
    assert _clamp_page_size(-5) == 1


def test_clamp_page_size_maximum():
    assert _clamp_page_size(200) == 100
    assert _clamp_page_size(101) == 100


def test_clamp_page_size_in_range():
    assert _clamp_page_size(25) == 25
    assert _clamp_page_size(100) == 100
    assert _clamp_page_size(1) == 1


@pytest.mark.asyncio
async def test_download_cap_enforced():
    """download_document raises ToolError when response exceeds max_bytes."""
    import respx

    from paperless import api as paperless_api

    large_body = b"x" * 200

    with respx.mock:
        respx.get("http://paperless:8000/api/documents/1/download/").mock(
            return_value=httpx.Response(200, content=large_body)
        )
        async with paperless_client(
            "http://paperless:8000",
            "alice",
            remote_user_header="X-Papaia-Remote-User",
            http_timeout=5.0,
        ) as client:
            with pytest.raises(ToolError, match="download exceeds limit"):
                await paperless_api.download_document(client, 1, max_bytes=10)


@pytest.mark.asyncio
async def test_upload_rejects_invalid_base64():
    """Malformed base64 raises binascii.Error, which upload_document maps to ToolError."""
    import base64 as b64_mod
    import binascii

    with pytest.raises(binascii.Error):
        b64_mod.b64decode("not-valid-base64!!!", validate=True)
