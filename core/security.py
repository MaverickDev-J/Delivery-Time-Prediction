"""
Security utilities — JWT tokens and password hashing.

Design decisions:
  - HS256 for JWT signing (shared secret, no asymmetric key infra needed at this scale)
  - bcrypt for password hashing (adaptive work factor, salted by default)
  - Access tokens: 15 min TTL (short-lived, limits exposure if stolen)
  - Refresh tokens: 7 day TTL (long-lived, stored client-side, used to get new access tokens)

Interview talking points:
  - "Why not RS256?" → RS256 (asymmetric) is for when multiple services need to verify
    tokens independently without sharing a secret. HS256 is simpler and correct for a
    single auth service that both issues and verifies.
  - "Why can't you revoke a JWT?" → JWTs are stateless — the server doesn't track them.
    To revoke, you'd need a token blacklist in Redis, which reintroduces statefulness.
    The mitigation is short-lived access tokens + refresh token rotation.
"""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from core.logging import setup_logger

logger = setup_logger("core.security")

# ── Configuration ────────────────────────────────────────────────────────────

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "deliveriq-dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


# ── Password Hashing ────────────────────────────────────────────────────────


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt.

    bcrypt automatically:
      1. Generates a random 16-byte salt
      2. Applies the Blowfish cipher with a configurable work factor (default 12 = 2^12 rounds)
      3. Returns a string containing the algorithm, work factor, salt, and hash

    Why bcrypt over SHA-256:
      - SHA-256 is fast → brute-forceable at billions of hashes/sec on a GPU
      - bcrypt is intentionally slow → ~100ms per hash, making brute-force impractical
    """
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ── JWT Token Creation ───────────────────────────────────────────────────────


def create_access_token(user_id: str, role: str, tenant_id: str | None = None) -> str:
    """Create a short-lived JWT access token.

    Payload:
      - sub: user_id (subject — who the token is for)
      - role: RBAC role (customer / admin / merchant)
      - tenant_id: for multi-tenant scoping (Phase 3B)
      - exp: expiration timestamp
      - iat: issued-at timestamp
      - type: "access" (distinguishes from refresh tokens)
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    logger.debug(f"Access token created for user {user_id}, role={role}, expires in {ACCESS_TOKEN_EXPIRE_MINUTES}m")
    return token


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token.

    Only contains user_id — role is re-fetched from DB on refresh
    (so role changes take effect without re-login).
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# ── JWT Token Verification ──────────────────────────────────────────────────


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token.

    Raises:
      jwt.ExpiredSignatureError: token has expired
      jwt.InvalidTokenError: token is malformed or signature doesn't match
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])


def verify_access_token(token: str) -> dict:
    """Verify an access token and return the payload.

    Returns dict with: sub, role, tenant_id (optional), exp, iat
    Raises ValueError if token is invalid or not an access token.
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Access token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")


def verify_refresh_token(token: str) -> dict:
    """Verify a refresh token and return the payload.

    Returns dict with: sub, exp, iat
    Raises ValueError if token is invalid or not a refresh token.
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Refresh token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")


# ── HMAC Request Signing (Merchant API & Webhooks) ──────────────────────────


import hmac
import hashlib
import secrets


def generate_api_key_pair() -> tuple[str, str]:
    """Generate a public API key and private secret for a tenant.

    Returns:
      (api_key, secret) e.g. ('dlvq_live_a1b2c3d4...', 'dlvq_sec_9z8y7x6w...')
    """
    api_key = f"dlvq_live_{secrets.token_hex(16)}"
    api_secret = f"dlvq_sec_{secrets.token_urlsafe(32)}"
    return api_key, api_secret


def compute_hmac_signature(secret: str, payload_bytes: bytes) -> str:
    """Compute SHA-256 HMAC signature of raw request/event payload.

    Returns format: 'sha256=<hex_digest>'
    Matches Stripe / GitHub webhook signature convention.
    """
    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def verify_hmac_signature(secret: str, payload_bytes: bytes, signature_header: str | None) -> bool:
    """Verify HMAC signature using constant-time comparison to prevent timing attacks.

    Interview talking point:
      Why hmac.compare_digest?
      Regular string '==' comparison terminates early on first mismatched byte.
      An attacker measuring nanosecond latency can iteratively guess the signature byte by byte.
      compare_digest takes the same amount of time regardless of match position.
    """
    if not signature_header:
        return False

    expected_signature = compute_hmac_signature(secret, payload_bytes)
    return hmac.compare_digest(expected_signature, signature_header)

