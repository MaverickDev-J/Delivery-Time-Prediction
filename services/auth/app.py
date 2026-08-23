"""
Auth Service — FastAPI application.

Endpoints:
  POST /auth/signup    — Create a new user (email + password → bcrypt hash)
  POST /auth/login     — Verify credentials → issue JWT access + refresh tokens
  POST /auth/refresh   — Exchange a valid refresh token for a new access token
  GET  /auth/me        — Return the current user's profile (requires valid JWT)

This service owns the users table and is the only service that issues JWTs.
All other services validate JWTs via core.auth_middleware (no DB lookup needed).
"""

import os

from fastapi import Depends, FastAPI, HTTPException, status

from contracts.auth import (
    AuthContext,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserProfile,
    UserRole,
)
from core.auth_middleware import get_current_user
from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics
from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_refresh_token,
)

logger = setup_logger("auth-service", service_name="auth-service")

# ── Database Setup ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("AUTH_DATABASE_URL", "sqlite:///data/auth.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)

# Import models so Base.metadata knows about them
from services.auth.models import User

# Create tables
init_tables(engine, Base)

# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(title="DeliverIQ Auth Service", version="1.0.0")
add_metrics_middleware(app, service_name="auth")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "auth-service"}


# ── Signup ───────────────────────────────────────────────────────────────────

@app.post("/auth/signup", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def signup(request: SignupRequest):
    """Register a new user.

    1. Check if email already exists → 409 Conflict
    2. Hash password with bcrypt
    3. Create user row
    4. Return user profile (no tokens — user must login separately)
    """
    with get_session(SessionFactory) as session:
        # Check for duplicate email
        existing = session.query(User).filter(User.email == request.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email {request.email} is already registered",
            )

        # Create user with bcrypt-hashed password
        user = User(
            email=request.email,
            name=request.name,
            password_hash=hash_password(request.password),
            role=request.role.value,
        )
        session.add(user)
        session.flush()  # Get the generated ID before commit

        profile = UserProfile(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=UserRole(user.role),
            created_at=user.created_at.isoformat(),
        )

    logger.info(f"User registered: {request.email} as {request.role.value}")
    return profile


# ── Login ────────────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest):
    """Authenticate a user and issue JWT tokens.

    1. Find user by email → 401 if not found
    2. Verify password against bcrypt hash → 401 if wrong
    3. Issue access token (15 min) + refresh token (7 days)
    """
    with get_session(SessionFactory) as session:
        user = session.query(User).filter(User.email == request.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not verify_password(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        access_token = create_access_token(user_id=user.id, role=user.role)
        refresh_token = create_refresh_token(user_id=user.id)

    logger.info(f"User logged in: {request.email}")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


# ── Refresh Token ────────────────────────────────────────────────────────────

@app.post("/auth/refresh", response_model=TokenResponse)
def refresh(request: RefreshRequest):
    """Exchange a valid refresh token for a new access token.

    Why re-fetch role from DB on refresh:
      If an admin changes a user's role, the new role takes effect on the next
      token refresh without requiring re-login. This is intentional.
    """
    try:
        payload = verify_refresh_token(request.refresh_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    user_id = payload["sub"]

    with get_session(SessionFactory) as session:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        access_token = create_access_token(user_id=user.id, role=user.role)
        new_refresh_token = create_refresh_token(user_id=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


# ── Profile ──────────────────────────────────────────────────────────────────

@app.get("/auth/me", response_model=UserProfile)
def get_profile(auth: AuthContext = Depends(get_current_user)):
    """Return the profile of the currently authenticated user.

    The user_id comes from the JWT — no way for a user to see another user's profile.
    This is the pattern the support agent (Phase 9) uses for authorization:
    user_id is injected server-side, never from user input.
    """
    with get_session(SessionFactory) as session:
        user = session.query(User).filter(User.id == auth.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return UserProfile(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=UserRole(user.role),
            created_at=user.created_at.isoformat(),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TENANT MANAGEMENT (Phase 3B — admin only)
# ═══════════════════════════════════════════════════════════════════════════════

from contracts.auth import CreateTenantRequest, TenantResponse
from core.auth_middleware import require_role
from core.security import generate_api_key_pair
from services.auth.models import Tenant


@app.post("/auth/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    request: CreateTenantRequest,
    auth: AuthContext = Depends(require_role(UserRole.ADMIN)),
):
    """Create a new merchant tenant. Admin only.

    Generates an API key + secret pair. The secret is shown ONCE in this response
    and stored in DB. The merchant uses:
      X-API-Key: dlvq_live_...
      X-Signature: sha256=HMAC(secret, raw_body)
    """
    api_key, api_secret = generate_api_key_pair()

    with get_session(SessionFactory) as session:
        tenant = Tenant(
            name=request.name,
            email=request.email,
            api_key=api_key,
            api_secret=api_secret,
            quota_limit_per_day=request.quota_limit_per_day,
        )
        session.add(tenant)
        session.flush()

        resp = TenantResponse(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            email=tenant.email,
            api_key=tenant.api_key,
            api_secret=api_secret,  # Only shown once!
            quota_limit_per_day=tenant.quota_limit_per_day,
            is_active=bool(tenant.is_active),
            created_at=tenant.created_at.isoformat(),
        )

    logger.info(f"Tenant created: {request.name} ({resp.tenant_id})")
    return resp


@app.get("/auth/tenants")
def list_tenants(auth: AuthContext = Depends(require_role(UserRole.ADMIN))):
    """List all tenants. Admin only. Secrets are masked."""
    with get_session(SessionFactory) as session:
        tenants = session.query(Tenant).order_by(Tenant.created_at.desc()).all()
        return [
            TenantResponse(
                tenant_id=t.tenant_id,
                name=t.name,
                email=t.email,
                api_key=t.api_key,
                api_secret=None,  # Never expose secret in list
                quota_limit_per_day=t.quota_limit_per_day,
                is_active=bool(t.is_active),
                created_at=t.created_at.isoformat(),
            )
            for t in tenants
        ]


@app.get("/auth/tenants/{tenant_id}", response_model=TenantResponse)
def get_tenant(tenant_id: str, auth: AuthContext = Depends(require_role(UserRole.ADMIN))):
    """Get tenant details. Admin only."""
    with get_session(SessionFactory) as session:
        tenant = session.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
        return TenantResponse(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            email=tenant.email,
            api_key=tenant.api_key,
            api_secret=None,
            quota_limit_per_day=tenant.quota_limit_per_day,
            is_active=bool(tenant.is_active),
            created_at=tenant.created_at.isoformat(),
        )


# ── Internal: API Key lookup (called by auth middleware) ─────────────────────

@app.get("/auth/internal/verify-api-key")
def verify_api_key(api_key: str):
    """Internal endpoint for auth middleware to resolve API key → tenant context.

    Not exposed publicly. Called over the compose network by the HMAC middleware.
    Returns tenant_id and api_secret for HMAC verification.
    """
    with get_session(SessionFactory) as session:
        tenant = session.query(Tenant).filter(
            Tenant.api_key == api_key,
            Tenant.is_active == 1,
        ).first()
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")
        return {
            "tenant_id": tenant.tenant_id,
            "api_secret": tenant.api_secret,
            "quota_limit_per_day": tenant.quota_limit_per_day,
        }

