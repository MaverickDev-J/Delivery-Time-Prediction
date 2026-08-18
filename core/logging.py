import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Context variable for request correlation ID across async coroutines
correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: str) -> None:
    correlation_id_ctx.set(correlation_id)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for DeliverIQ services."""

    def __init__(self, service_name: str = "deliveriq-service"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if provided
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "message",
            } and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry)


def setup_logger(name: str, service_name: str = "deliveriq-service", level: str = "INFO") -> logging.Logger:
    """Configure and return a structured logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter(service_name=service_name))
        logger.addHandler(handler)
        logger.propagate = False

    return logger
