"""
Saga Orchestrator FastAPI application.

Endpoints:
  POST /saga/start       — Start a new saga for an order
  GET  /saga/{order_id}  — Get saga status
  GET  /saga/{saga_id}/steps — Get full step log
"""

import os

from fastapi import FastAPI, HTTPException

from core.database import Base, create_db_engine, create_session_factory, init_tables
from core.logging import setup_logger
from services.orchestrator.models import SagaInstance, SagaStepLog  # noqa: F401
from services.orchestrator.saga_state_machine import SagaOrchestrator

logger = setup_logger("orchestrator-service", service_name="saga-orchestrator")

# Database
DATABASE_URL = os.getenv("SAGA_DATABASE_URL", "sqlite:///data/saga.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)
init_tables(engine, Base)

app = FastAPI(title="DeliverIQ Saga Orchestrator", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "UP", "service": "saga-orchestrator"}


# The orchestrator instance is created at module level with None services.
# In production, these are replaced with HTTP-backed service adapters.
# In tests, they are injected directly.
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


@app.post("/saga/start")
def start_saga(order_id: str, items: list[str], total_amount: float):
    orch = get_orchestrator()
    result = orch.start_saga(order_id=order_id, items=items, total_amount=total_amount)
    return result


@app.get("/saga/{order_id}")
def get_saga_status(order_id: str):
    orch = get_orchestrator()
    result = orch.get_saga_status(order_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Saga for order {order_id} not found")
    return result
