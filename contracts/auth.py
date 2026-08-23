"""
Auth contracts — request/response schemas for authentication and authorization.

Used by:
  - services/auth/app.py (auth service endpoints)
  - core/auth_middleware.py (JWT validation → AuthContext)
  - Any service that needs to know who the caller is
"""

from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """RBAC roles — kept simple: three roles, clear boundaries."""
    CUSTOMER = "customer"
    ADMIN = "admin"
    MERCHANT = "merchant"


# ── Request Schemas ──────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    """Customer or admin signup."""
    email: EmailStr = Field(..., description="User email address", examples=["jatin@deliveriq.io"])
    password: str = Field(..., min_length=8, max_length=128, description="Password (min 8 chars)")
    name: str = Field(..., min_length=1, max_length=100, description="Display name")
    role: UserRole = Field(default=UserRole.CUSTOMER, description="User role")


class LoginRequest(BaseModel):
    """Login with email + password → JWT."""
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Refresh an expired access token using a refresh token."""
    refresh_token: str


# ── Response Schemas ─────────────────────────────────────────────────────────


class TokenResponse(BaseModel):
    """Returned on successful login or refresh."""
    access_token: str = Field(..., description="Short-lived JWT (15 min)")
    refresh_token: str = Field(..., description="Long-lived refresh token (7 days)")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(default=900, description="Access token TTL in seconds")


class UserProfile(BaseModel):
    """Returned by GET /auth/me."""
    user_id: str
    email: str
    name: str
    role: UserRole
    created_at: str


# ── Internal Auth Context (injected by middleware) ───────────────────────────


class AuthContext(BaseModel):
    """
    Injected into every request handler by the auth middleware.
    The handler never knows HOW auth happened (JWT vs API key) — it just
    gets a verified context with user_id, role, and tenant_id.
    """
    user_id: str
    role: UserRole
    tenant_id: str | None = None  # Set for merchant API key auth (Phase 3B)


# ── Tenant & API Key Schemas (Phase 3B: Merchant B2B API) ───────────────────


class CreateTenantRequest(BaseModel):
    """Admin creates a new merchant tenant."""
    name: str = Field(..., min_length=2, max_length=100, description="Merchant company/store name")
    email: EmailStr = Field(..., description="Primary contact/billing email")
    quota_limit_per_day: int = Field(default=1000, ge=1, le=100000, description="Max API requests per day")


class TenantResponse(BaseModel):
    """Merchant tenant profile."""
    tenant_id: str
    name: str
    email: str
    api_key: str
    api_secret: str | None = Field(default=None, description="Only shown once at creation time")
    quota_limit_per_day: int
    is_active: bool = True
    created_at: str

