"""
Tests for Phase 3B — Merchant API, HMAC, Tenants, Webhooks.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient


def get_auth_client():
    from services.auth.app import app
    return TestClient(app)


def get_webhook_client():
    from services.webhook.app import app
    return TestClient(app)


def _create_admin_and_get_token(client):
    """Helper: signup as admin → login → return access token."""
    email = f"admin_{uuid.uuid4().hex[:6]}@deliveriq.io"
    client.post("/auth/signup", json={
        "email": email,
        "password": "adminpass123",
        "name": "Admin User",
        "role": "admin",
    })
    resp = client.post("/auth/login", json={"email": email, "password": "adminpass123"})
    return resp.json()["access_token"]


def _create_customer_and_get_token(client):
    """Helper: signup as customer → login → return access token."""
    email = f"customer_{uuid.uuid4().hex[:6]}@example.com"
    client.post("/auth/signup", json={
        "email": email,
        "password": "custpass123",
        "name": "Customer",
    })
    resp = client.post("/auth/login", json={"email": email, "password": "custpass123"})
    return resp.json()["access_token"]


class TestTenantManagement:
    def test_admin_can_create_tenant(self):
        client = get_auth_client()
        token = _create_admin_and_get_token(client)

        resp = client.post("/auth/tenants", json={
            "name": "Pizza Palace",
            "email": "pizza@palace.com",
            "quota_limit_per_day": 500,
        }, headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Pizza Palace"
        assert data["api_key"].startswith("dlvq_live_")
        assert data["api_secret"].startswith("dlvq_sec_")  # Only shown on creation
        assert data["tenant_id"].startswith("TENANT-")

    def test_customer_cannot_create_tenant(self):
        client = get_auth_client()
        token = _create_customer_and_get_token(client)

        resp = client.post("/auth/tenants", json={
            "name": "Rogue Tenant",
            "email": "rogue@example.com",
        }, headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 403  # RBAC enforcement

    def test_list_tenants_hides_secrets(self):
        client = get_auth_client()
        token = _create_admin_and_get_token(client)

        # Create a tenant first
        client.post("/auth/tenants", json={
            "name": "Burger Barn",
            "email": "burgers@barn.com",
        }, headers={"Authorization": f"Bearer {token}"})

        # List tenants
        resp = client.get("/auth/tenants", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        tenants = resp.json()
        assert len(tenants) >= 1
        assert tenants[0]["api_secret"] is None  # Secret masked in list


class TestAPIKeyVerification:
    def test_verify_valid_api_key(self):
        client = get_auth_client()
        token = _create_admin_and_get_token(client)

        # Create tenant
        resp = client.post("/auth/tenants", json={
            "name": "Test Merchant",
            "email": "test@merchant.com",
        }, headers={"Authorization": f"Bearer {token}"})

        api_key = resp.json()["api_key"]

        # Verify key via internal endpoint
        verify_resp = client.get(f"/auth/internal/verify-api-key?api_key={api_key}")
        assert verify_resp.status_code == 200
        assert "tenant_id" in verify_resp.json()
        assert "api_secret" in verify_resp.json()

    def test_verify_invalid_api_key(self):
        client = get_auth_client()
        resp = client.get("/auth/internal/verify-api-key?api_key=fake_key_12345")
        assert resp.status_code == 401


class TestHMACSignature:
    def test_hmac_compute_and_verify(self):
        from core.security import compute_hmac_signature, verify_hmac_signature

        secret = "test-secret-key"
        payload = b'{"order_id": "ORD-123", "total": 499}'

        signature = compute_hmac_signature(secret, payload)
        assert signature.startswith("sha256=")
        assert len(signature) > 10

        # Valid signature
        assert verify_hmac_signature(secret, payload, signature) is True

        # Wrong payload
        assert verify_hmac_signature(secret, b"tampered", signature) is False

        # Wrong secret
        assert verify_hmac_signature("wrong-secret", payload, signature) is False

        # Missing signature
        assert verify_hmac_signature(secret, payload, None) is False

    def test_api_key_generation(self):
        from core.security import generate_api_key_pair

        key, secret = generate_api_key_pair()
        assert key.startswith("dlvq_live_")
        assert secret.startswith("dlvq_sec_")
        assert len(key) > 20
        assert len(secret) > 20

        # Each call generates unique keys
        key2, secret2 = generate_api_key_pair()
        assert key != key2
        assert secret != secret2


class TestWebhookSubscriptions:
    def test_create_subscription(self):
        webhook_client = get_webhook_client()
        auth_client = get_auth_client()
        token = _create_admin_and_get_token(auth_client)

        resp = webhook_client.post("/webhooks/subscriptions", json={
            "url": "https://merchant.example.com/hooks",
            "event_types": ["order.confirmed", "order.cancelled"],
            "description": "Production endpoint",
        }, headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "https://merchant.example.com/hooks"
        assert "order.confirmed" in data["event_types"]
        assert len(data["secret"]) > 10  # Signing secret generated

    def test_list_subscriptions(self):
        webhook_client = get_webhook_client()
        auth_client = get_auth_client()
        token = _create_admin_and_get_token(auth_client)

        # Create one
        webhook_client.post("/webhooks/subscriptions", json={
            "url": "https://merchant2.example.com/hooks",
            "event_types": ["order.created"],
        }, headers={"Authorization": f"Bearer {token}"})

        # List
        resp = webhook_client.get("/webhooks/subscriptions", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        subs = resp.json()
        assert len(subs) >= 1
        assert subs[0]["secret"] == "••••••••"  # Masked in list


class TestWebhookDispatch:
    def test_dispatch_returns_count(self):
        webhook_client = get_webhook_client()

        # Dispatch to a tenant with no subscriptions — should dispatch 0
        resp = webhook_client.post("/webhooks/dispatch", json={
            "event_id": "EVT-001",
            "event_type": "order.confirmed",
            "tenant_id": "NONEXISTENT-TENANT",
            "payload": {"order_id": "ORD-TEST"},
        })
        assert resp.status_code == 200
        assert resp.json()["dispatched"] == 0
