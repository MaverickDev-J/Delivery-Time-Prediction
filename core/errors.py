from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.logging import get_correlation_id


class ProblemDetails(BaseModel):
    """RFC 7807 problem details response schema."""
    type: str = Field(default="about:blank", description="URI identifying the problem type")
    title: str = Field(..., description="Short, human-readable summary of problem")
    status: int = Field(..., description="HTTP status code")
    detail: str = Field(..., description="Human-readable explanation specific to this occurrence")
    instance: str | None = Field(default=None, description="URI identifying the specific occurrence")
    correlation_id: str | None = Field(default=None, description="Request correlation ID for tracing")
    invalid_params: list | None = Field(default=None, description="List of invalid fields for 422 errors")


class DeliverIQException(Exception):
    """Base domain exception for DeliverIQ services."""
    def __init__(self, title: str, detail: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.title = title
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ModelNotReadyException(DeliverIQException):
    def __init__(self, detail: str = "Model artifacts are not loaded yet."):
        super().__init__(
            title="Model Not Ready",
            detail=detail,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class ResourceNotFoundException(DeliverIQException):
    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            title="Resource Not Found",
            detail=f"{resource_type} with ID '{resource_id}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Register RFC 7807 problem detail exception handlers with FastAPI."""

    @app.exception_handler(DeliverIQException)
    async def deliveriq_exception_handler(request: Request, exc: DeliverIQException):
        problem = ProblemDetails(
            type="https://deliveriq.io/errors/domain-error",
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            correlation_id=get_correlation_id(),
        )
        return JSONResponse(status_code=exc.status_code, content=problem.model_dump(exclude_none=True))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        problem = ProblemDetails(
            type="https://deliveriq.io/errors/validation-error",
            title="Unprocessable Entity",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request validation failed. Check invalid_params for details.",
            instance=str(request.url.path),
            correlation_id=get_correlation_id(),
            invalid_params=exc.errors(),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=problem.model_dump(exclude_none=True))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        problem = ProblemDetails(
            type="https://deliveriq.io/errors/internal-server-error",
            title="Internal Server Error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal error occurred.",
            instance=str(request.url.path),
            correlation_id=get_correlation_id(),
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=problem.model_dump(exclude_none=True))
