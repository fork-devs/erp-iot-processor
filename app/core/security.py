from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError, PyJWKClient

from app.core.config import get_settings

NIL_UUID = UUID("00000000-0000-0000-0000-000000000000")


@lru_cache(maxsize=4)
def get_jwk_client(jwks_url: str) -> PyJWKClient:
    """Cached PyJWKClient instance keyed by JWKS URL."""
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def parse_non_nil_uuid(raw_value: Any, detail_on_error: str) -> UUID:
    """Parse a UUID and reject the nil UUID (00000000-0000-0000-0000-000000000000)."""
    if raw_value is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail_on_error)
    try:
        parsed = UUID(str(raw_value).strip())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail_on_error)
    if parsed == NIL_UUID:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nil tenant UUID is not permitted",
        )
    return parsed


def verify_access_token_and_extract_tenant(token: str) -> str:
    """Verify RS256 JWT signature and claims against JWKS and return non-nil tenant UUID string."""
    settings = get_settings()
    try:
        jwk_client = get_jwk_client(settings.JWKS_URL)
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": {
                "require": ["exp", "sub", "tenant_id"],
                "verify_signature": True,
                "verify_exp": True,
            },
        }
        if settings.JWT_ISSUER:
            decode_kwargs["issuer"] = settings.JWT_ISSUER

        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to verify authentication token",
        )

    token_type = payload.get("type")
    if token_type is not None and token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for API access",
        )

    return str(parse_non_nil_uuid(payload.get("tenant_id"), "Token missing valid tenant_id claim"))
