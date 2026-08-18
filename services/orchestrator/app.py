"""
Saga Orchestrator FastAPI application.

Endpoints:
  POST /saga/start       — Start a new saga for an order
  GET  /saga/{order_id}  — Get saga status
  GET  /saga/{saga_id}/steps — Get full step log
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.database import Base, create_db_engine, create_session_factory, init_tables
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics
from services.orchestrator.models import SagaInstance, SagaStepLog  # noqa: F401
from services.orchestrator.saga_state_machine import SagaOrchestrator

logger = setup_logger("orchestrator-service", service_name="saga-orchestrator")

# Database
DATABASE_URL = os.getenv("SAGA_DATABASE_URL", "sqlite:///data/saga.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)
init_tables(engine, Base)

app = FastAPI(title="DeliverIQ Saga Orchestrator", version="1.0.0")
add_metrics_middleware(app, service_name="orchestrator")
expose_metrics(app)


# ── Request schema ───────────────────────────────────────────────────────────

class StartSagaRequest(BaseModel):
    order_id: str
    items: list[str] = Field(default_factory=lambda: ["meal"])
    total_amount: float = 499.0
    order_data: dict | None = None


# ── Orchestrator lifecycle ───────────────────────────────────────────────────

_orchestrator: SagaOrchestrator | None = None


def get_orchestrator() -> SagaOrchestrator:
    if _orchestrator is None:
        raise RuntimeError("Orchestrator not initialized. Call init_orchestrator() first.")
    return _orchestrator


def init_orchestrator(payment_service, inventory_service, eta_service=None, order_service=None):
    """Initialize the orchestrator with service adapters. Called at startup."""
    global _orchestrator
    _orchestrator = SagaOrchestrator(
        session_factory=SessionFactory,
        payment_service=payment_service,
        inventory_service=inventory_service,
        eta_service=eta_service,
        order_service=order_service,
    )
    logger.info("Saga orchestrator initialized with service adapters")


# ── Auto-init with HTTP adapters when running in Docker ──────────────────────

def _auto_init():
    """Initialize with HTTP adapters if service URLs are configured."""
    payment_url = os.getenv("PAYMENT_SERVICE_URL")
    inventory_url = os.getenv("INVENTORY_SERVICE_URL")
    eta_url = os.getenv("ETA_SERVICE_URL")
    order_url = os.getenv("ORDER_SERVICE_URL")

    if payment_url and inventory_url:
        from services.orchestrator.http_adapters import (
            HttpEtaService,
            HttpInventoryService,
            HttpOrderService,
            HttpPaymentService,
        )

        payment = HttpPaymentService(base_url=payment_url)
        inventory = HttpInventoryService(base_url=inventory_url)
        eta = HttpEtaService(base_url=eta_url) if eta_url else None
        order = HttpOrderService(base_url=order_url) if order_url else None

        init_orchestrator(payment, inventory, eta, order)
        logger.info(f"Auto-initialized with HTTP adapters: payment={payment_url}, inventory={inventory_url}")
    else:
        logger.warning("No service URLs configured — orchestrator not auto-initialized (ok for tests)")


_auto_init()


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "UP", "service": "saga-orchestrator", "initialized": _orchestrator is not None}


@app.post("/saga/start")
def start_saga(req: StartSagaRequest):
    orch = get_orchestrator()
    result = orch.start_saga(
        order_id=req.order_id,
        items=req.items,
        total_amount=req.total_amount,
        order_data=req.order_data,
    )
    return result


@app.get("/saga/{order_id}")
def get_saga_status(order_id: str):
    orch = get_orchestrator()
    result = orch.get_saga_status(order_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Saga for order {order_id} not found")
    return result
