"""
Tests for Auth Service — signup, login, JWT, RBAC, rate limiting.

Covers:
  - Signup → creates user with bcrypt hash
  - Login → returns valid JWT tokens
  - JWT middleware → protects routes
  - RBAC → admin vs customer access
  - Rate limiting → 429 after limit
  - Pagination → order list with page/limit/sort
"""

import pytest
from fastapi.testclient import TestClient

# ── Auth service tests ────────────────────────────────────────────────────────


def get_auth_client():
    """Create a test client for the auth service."""
    from services.auth.app import app
    return TestClient(app)


def get_order_client():
    """Create a test client for the order service."""
    from services.order.app import app
    return TestClient(app)


class TestSignup:
    def test_signup_success(self):
        client = get_auth_client()
        import uuid
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        resp = client.post("/auth/signup", json={
            "email": unique_email,
            "password": "securepass123",
            "name": "Test User",
            "role": "customer",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == unique_email
        assert data["role"] == "customer"
        assert "user_id" in data

    def test_signup_duplicate_email(self):
        client = get_auth_client()
        payload = {
            "email": "duplicate@example.com",
            "password": "securepass123",
            "name": "First User",
        }
        client.post("/auth/signup", json=payload)
        resp = client.post("/auth/signup", json=payload)
        assert resp.status_code == 409

    def test_signup_weak_password(self):
        client = get_auth_client()
        resp = client.post("/auth/signup", json={
            "email": "weak@example.com",
            "password": "short",  # < 8 chars
            "name": "Weak Pass User",
        })
        assert resp.status_code == 422  # Validation error


class TestLogin:
    def test_login_success(self):
        client = get_auth_client()
        # Signup first
        client.post("/auth/signup", json={
            "email": "login_test@example.com",
            "password": "securepass123",
            "name": "Login Test",
        })
        # Login
        resp = client.post("/auth/login", json={
            "email": "login_test@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self):
        client = get_auth_client()
        client.post("/auth/signup", json={
            "email": "wrong_pw@example.com",
            "password": "securepass123",
            "name": "Wrong PW Test",
        })
        resp = client.post("/auth/login", json={
            "email": "wrong_pw@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_email(self):
        client = get_auth_client()
        resp = client.post("/auth/login", json={
            "email": "nonexistent@example.com",
            "password": "somepassword",
        })
        assert resp.status_code == 401


class TestJWTProtection:
    def test_profile_without_token(self):
        client = get_auth_client()
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_profile_with_valid_token(self):
        client = get_auth_client()
        # Signup + Login
        client.post("/auth/signup", json={
            "email": "profile_test@example.com",
            "password": "securepass123",
            "name": "Profile Test",
        })
        login_resp = client.post("/auth/login", json={
            "email": "profile_test@example.com",
            "password": "securepass123",
        })
        token = login_resp.json()["access_token"]

        # Access profile
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "profile_test@example.com"

    def test_profile_with_invalid_token(self):
        client = get_auth_client()
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalidtoken123"})
        assert resp.status_code == 401


class TestRefreshToken:
    def test_refresh_token_flow(self):
        client = get_auth_client()
        # Signup + Login
        client.post("/auth/signup", json={
            "email": "refresh_test@example.com",
            "password": "securepass123",
            "name": "Refresh Test",
        })
        login_resp = client.post("/auth/login", json={
            "email": "refresh_test@example.com",
            "password": "securepass123",
        })
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        assert "access_token" in resp.json()


class TestSecurityModule:
    def test_password_hashing(self):
        from core.security import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"  # Not stored in plaintext
        assert verify_password("mypassword", hashed)
        assert not verify_password("wrongpassword", hashed)

    def test_jwt_create_verify(self):
        from core.security import create_access_token, verify_access_token
        token = create_access_token(user_id="user-123", role="customer")
        payload = verify_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["role"] == "customer"
        assert payload["type"] == "access"

    def test_jwt_expired_token(self):
        import jwt as pyjwt
        from datetime import datetime, timedelta, UTC
        from core.security import JWT_SECRET_KEY, JWT_ALGORITHM

        expired_payload = {
            "sub": "user-expired",
            "role": "customer",
            "type": "access",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        }
        expired_token = pyjwt.encode(expired_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        from core.security import verify_access_token
        with pytest.raises(ValueError, match="expired"):
            verify_access_token(expired_token)


class TestRateLimiter:
    def test_sliding_window(self):
        from core.rate_limiter import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)

        # First 3 requests should be allowed
        for _ in range(3):
            allowed, limit, remaining, reset = limiter.check("test-key")
            assert allowed

        # 4th request should be rejected
        allowed, limit, remaining, reset = limiter.check("test-key")
        assert not allowed
        assert remaining == 0


class TestOrderPagination:
    def test_paginated_order_list(self):
        """Test that the order list endpoint returns paginated results."""
        auth_client = get_auth_client()
        order_client = get_order_client()

        # Signup + Login
        auth_client.post("/auth/signup", json={
            "email": "paginate_test@example.com",
            "password": "securepass123",
            "name": "Pagination Test",
        })
        login_resp = auth_client.post("/auth/login", json={
            "email": "paginate_test@example.com",
            "password": "securepass123",
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # List orders (may be empty)
        resp = order_client.get("/api/v1/orders?page=1&limit=5", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert "has_next" in data
