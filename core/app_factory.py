import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import BaseServiceSettings
from core.errors import register_exception_handlers
from core.logging import set_correlation_id, setup_logger


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every HTTP request has a trace correlation ID in context and response header."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_correlation_id(correlation_id)
        
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def create_app(
    settings: BaseServiceSettings,
    lifespan: Callable | None = None,
) -> FastAPI:
    """Create and configure a production-ready FastAPI application for a DeliverIQ service."""
    setup_logger(name=settings.service_name, service_name=settings.service_name, level=settings.log_level)

    app = FastAPI(
        title=f"DeliverIQ - {settings.service_name}",
        description=f"Microservice for {settings.service_name} in DeliverIQ fulfillment platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Middleware
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers
    register_exception_handlers(app)

    # Standard liveness probe
    @app.get("/health", tags=["Health"])
    async def health():
        return {"status": "UP", "service": settings.service_name}

    return app
