"""
Security Primitives

Password hashing and JWT token creation/verification. Kept dependency-free
of the database and FastAPI so it's trivial to unit test in isolation.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt truncates/rejects passwords over 72 bytes; callers should validate
# password length at the schema layer, but we guard here too so a caller
# that skips schema validation still fails safely.
_MAX_PASSWORD_BYTES = 72


class TokenType(str, Enum):
    """Distinguishes access from refresh tokens inside the JWT payload.

    Without this, a stolen refresh token (typically longer-lived) could be
    replayed directly against endpoints expecting an access token.
    """

    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    password_bytes = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its stored hash."""
    password_bytes = plain_password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format (e.g. corrupted data) — treat as
        # a failed verification rather than raising into the caller.
        return False


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta, extra_claims: Optional[dict[str, Any]] = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return str(jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM))


def create_access_token(user_id: str, role: str, restaurant_id: Optional[str]) -> str:
    """Create a short-lived access token carrying role/tenant claims."""
    return _create_token(
        subject=user_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role, "restaurant_id": restaurant_id},
    )


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token. Deliberately carries no role/tenant
    claims — those are re-derived from the database on refresh so a role
    change or deactivation takes effect immediately instead of surviving
    until the old refresh token expires."""
    return _create_token(
        subject=user_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )


class TokenPayload:
    """Decoded, validated token contents."""

    def __init__(self, user_id: str, token_type: TokenType, role: Optional[str] = None, restaurant_id: Optional[str] = None):
        self.user_id = user_id
        self.token_type = token_type
        self.role = role
        self.restaurant_id = restaurant_id


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """
    Decode and validate a JWT, enforcing it is of the expected type.

    Raises jose.JWTError (or ValueError for a type mismatch) on any
    failure — callers translate that into an HTTP 401.
    """
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

    token_type = payload.get("type")
    if token_type != expected_type.value:
        raise JWTError(f"Expected a {expected_type.value} token, got {token_type!r}")

    user_id = payload.get("sub")
    if not user_id:
        raise JWTError("Token missing 'sub' claim")

    return TokenPayload(
        user_id=user_id,
        token_type=expected_type,
        role=payload.get("role"),
        restaurant_id=payload.get("restaurant_id"),
    )
