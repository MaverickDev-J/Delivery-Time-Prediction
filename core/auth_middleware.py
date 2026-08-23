"""
Auth middleware — FastAPI dependency that extracts and verifies JWT from
the Authorization header and injects an AuthContext into every handler.

Usage in any service:
    from core.auth_middleware import get_current_user, require_role

    @app.get("/orders")
    def list_orders(auth: AuthContext = Depends(get_current_user)):
        # auth.user_id, auth.role, auth.tenant_id are available
        ...

    @app.get("/admin/settings")
    def admin_settings(auth: AuthContext = Depends(require_role(UserRole.ADMIN))):
        # Only admin can access this
        ...

Design:
  - No DB lookup per request — that's the whole point of JWTs
  - The middleware resolves JWT → AuthContext uniformly
  - Handlers never know which auth mechanism was used
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contracts.auth import AuthContext, UserRole
from core.logging import setup_logger
from core.security import verify_access_token

logger = setup_logger("core.auth_middleware")

# HTTPBearer extracts the token from "Authorization: Bearer <token>"
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext:
    """Extract and verify the JWT from the Authorization header.

    Returns an AuthContext with user_id, role, and optional tenant_id.
    Raises 401 if the token is missing, expired, or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header. Send: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_access_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthContext(
        user_id=payload["sub"],
        role=UserRole(payload["role"]),
        tenant_id=payload.get("tenant_id"),
    )


def require_role(*allowed_roles: UserRole):
    """Factory that returns a dependency requiring the user to have one of the allowed roles.

    Usage:
        @app.get("/admin/panel")
        def admin_panel(auth: AuthContext = Depends(require_role(UserRole.ADMIN))):
            ...

        @app.get("/orders")
        def list_orders(auth: AuthContext = Depends(require_role(UserRole.CUSTOMER, UserRole.ADMIN))):
            ...
    """
    async def _role_checker(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
        if auth.role not in allowed_roles:
            role_names = ", ".join(r.value for r in allowed_roles)
            logger.warning(f"Access denied: user {auth.user_id} with role {auth.role.value} tried to access route requiring [{role_names}]")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {role_names}",
            )
        return auth

    return _role_checker


# ── Optional auth (for routes that work with or without auth) ────────────────


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext | None:
    """Like get_current_user, but returns None instead of 401 if no token is present.

    Useful for routes that show different data for authenticated vs anonymous users.
    """
    if credentials is None:
        return None

    try:
        payload = verify_access_token(credentials.credentials)
        return AuthContext(
            user_id=payload["sub"],
            role=UserRole(payload["role"]),
            tenant_id=payload.get("tenant_id"),
        )
    except ValueError:
        return None
