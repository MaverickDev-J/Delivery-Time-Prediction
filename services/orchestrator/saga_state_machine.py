"""
Saga State Machine — orchestration-based distributed transaction coordinator.

State transitions:
  CREATED → PAYMENT_PENDING → PAYMENT_OK → INVENTORY_PENDING → INVENTORY_OK
  → ETA_PENDING → CONFIRMED | CONFIRMED_DEGRADED

Compensation:
  INVENTORY_FAILED (after PAYMENT_OK) → REFUNDING → REFUNDED → CANCELLED
  PAYMENT_FAILED → CANCELLED (nothing to undo)
  ETA_FAILED → CONFIRMED_DEGRADED (non-critical, degrade not cancel)

Design:
  - Every state transition is persisted to saga_db before the next step executes.
  - Each step is idempotent (idempotency keys derived from saga_id + step).
  - The orchestrator calls downstream services via direct function calls (in-process)
    for testability. In production Docker Compose, these would be HTTP calls via
    the ResilientHttpClient.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy.orm import Session

from core.idempotency import generate_idempotency_key
from core.logging import setup_logger
from services.orchestrator.models import SagaInstance, SagaStepLog

logger = setup_logger("saga-state-machine", service_name="saga-orchestrator")


class SagaState(str, Enum):
    CREATED = "CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_OK = "PAYMENT_OK"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    INVENTORY_PENDING = "INVENTORY_PENDING"
    INVENTORY_OK = "INVENTORY_OK"
    INVENTORY_FAILED = "INVENTORY_FAILED"
    ETA_PENDING = "ETA_PENDING"
    ETA_OK = "ETA_OK"
    ETA_FAILED = "ETA_FAILED"
    CONFIRMED = "CONFIRMED"
    CONFIRMED_DEGRADED = "CONFIRMED_DEGRADED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


def _log_step(session: Session, saga_id: str, step_name: str, from_state: str, to_state: str, step_type: str = "FORWARD", detail: str | None = None):
    """Append an immutable step log entry."""
    log = SagaStepLog(
        saga_id=saga_id,
        step_name=step_name,
        from_state=from_state,
        to_state=to_state,
        step_type=step_type,
        detail=detail,
    )
    session.add(log)


def _transition(session: Session, saga: SagaInstance, new_state: SagaState, step_name: str, step_type: str = "FORWARD", detail: str | None = None):
    """Atomically transition saga state and log the step."""
    old_state = saga.current_state
    saga.current_state = new_state.value
    saga.updated_at = datetime.now(UTC)
    _log_step(session, saga.saga_id, step_name, old_state, new_state.value, step_type, detail)
    logger.info(f"Saga {saga.saga_id}: {old_state} → {new_state.value} [{step_name}]")


class SagaOrchestrator:
    """
    Drives an order through the saga steps using injected service callables.

    Service callables are functions (or TestClient wrappers) that simulate
    inter-service communication. This allows the orchestrator to be tested
    end-to-end without network calls.
    """

    def __init__(self, session_factory, payment_service, inventory_service, eta_service=None, order_service=None):
        """
        Args:
            session_factory: SQLAlchemy session factory for saga_db
            payment_service: Object with .authorize(order_id, amount, idem_key) and .refund(order_id, payment_id, idem_key)
            inventory_service: Object with .reserve(order_id, items, idem_key) and .release(order_id, reservation_id, idem_key)
            eta_service: Object with .predict(order_data) -> dict or None
            order_service: Object with .update_status(order_id, status, ...) or None
        """
        self.session_factory = session_factory
        self.payment = payment_service
        self.inventory = inventory_service
        self.eta = eta_service
        self.order = order_service

    def start_saga(self, order_id: str, items: list[str], total_amount: float, order_data: dict | None = None) -> dict:
        """Execute the full saga for an order. Returns the final saga state."""

        saga_id = f"SAGA-{uuid.uuid4().hex[:12].upper()}"
        correlation_id = order_id

        # --- Create saga instance ---
        session: Session = self.session_factory()
        try:
            saga = SagaInstance(
                saga_id=saga_id,
                order_id=order_id,
                correlation_id=correlation_id,
                current_state=SagaState.CREATED.value,
            )
            session.add(saga)
            _transition(session, saga, SagaState.PAYMENT_PENDING, "saga_started")
            session.commit()

            # --- Step 1: Authorize Payment ---
            pay_idem_key = generate_idempotency_key(saga_id, "payment", "authorize")
            try:
                pay_result = self.payment.authorize(order_id, total_amount, pay_idem_key)
            except Exception as e:
                _transition(session, saga, SagaState.PAYMENT_FAILED, "payment_error", detail=str(e))
                _transition(session, saga, SagaState.CANCELLED, "cancelled_payment_error")
                saga.error_reason = str(e)
                saga.completed_at = datetime.now(UTC)
                session.commit()
                return self._saga_result(saga)

            if pay_result.get("status") != "AUTHORIZED":
                _transition(session, saga, SagaState.PAYMENT_FAILED, "payment_declined", detail=pay_result.get("message"))
                _transition(session, saga, SagaState.CANCELLED, "cancelled_payment_declined")
                saga.error_reason = pay_result.get("message", "Payment declined")
                saga.completed_at = datetime.now(UTC)
                session.commit()
                return self._saga_result(saga)

            saga.payment_id = pay_result["payment_id"]
            _transition(session, saga, SagaState.PAYMENT_OK, "payment_authorized", detail=pay_result["payment_id"])
            session.commit()

            # --- Step 2: Reserve Inventory ---
            _transition(session, saga, SagaState.INVENTORY_PENDING, "inventory_reserve_start")
            session.commit()

            inv_idem_key = generate_idempotency_key(saga_id, "inventory", "reserve")
            try:
                inv_result = self.inventory.reserve(order_id, items, inv_idem_key)
            except Exception as e:
                _transition(session, saga, SagaState.INVENTORY_FAILED, "inventory_error", detail=str(e))
                session.commit()
                return self._compensate(session, saga, reason=str(e))

            if inv_result.get("status") != "RESERVED":
                _transition(session, saga, SagaState.INVENTORY_FAILED, "inventory_out_of_stock", detail=inv_result.get("message"))
                session.commit()
                return self._compensate(session, saga, reason=inv_result.get("message", "Out of stock"))

            saga.reservation_id = inv_result["reservation_id"]
            _transition(session, saga, SagaState.INVENTORY_OK, "inventory_reserved", detail=inv_result["reservation_id"])
            session.commit()

            # --- Step 3: Request ETA (non-critical) ---
            _transition(session, saga, SagaState.ETA_PENDING, "eta_request_start")
            session.commit()

            eta_result = None
            is_degraded = True

            if self.eta:
                try:
                    eta_result = self.eta.predict(order_data or {})
                    if eta_result and "eta_minutes" in eta_result:
                        is_degraded = eta_result.get("degraded", False)
                except Exception as e:
                    logger.warning(f"ETA service failed (non-critical): {e}")
                    eta_result = None

            if eta_result and not is_degraded:
                saga.eta_minutes = eta_result.get("eta_minutes")
                saga.eta_lower = eta_result.get("lower_bound")
                saga.eta_upper = eta_result.get("upper_bound")
                saga.degraded = 0
                _transition(session, saga, SagaState.CONFIRMED, "eta_received_confirmed", detail=f"ETA: {saga.eta_minutes} min")
            else:
                # Degrade, NEVER cancel for ETA failure
                saga.eta_minutes = 32.0  # Historical median fallback
                saga.eta_lower = 25.0
                saga.eta_upper = 40.0
                saga.degraded = 1
                detail = "ETA unavailable, using fallback"
                if eta_result and is_degraded:
                    saga.eta_minutes = eta_result.get("eta_minutes", 32.0)
                    saga.eta_lower = eta_result.get("lower_bound", 25.0)
                    saga.eta_upper = eta_result.get("upper_bound", 40.0)
                    detail = "ETA returned in degraded mode"
                _transition(session, saga, SagaState.CONFIRMED_DEGRADED, "eta_degraded_confirmed", detail=detail)

            saga.completed_at = datetime.now(UTC)
            session.commit()

            # Update order service if available
            if self.order:
                try:
                    self.order.update_status(
                        order_id=order_id,
                        new_status=saga.current_state,
                        eta_minutes=saga.eta_minutes,
                        eta_lower=saga.eta_lower,
                        eta_upper=saga.eta_upper,
                        degraded=bool(saga.degraded),
                    )
                except Exception as e:
                    logger.warning(f"Failed to update order service: {e}")

            return self._saga_result(saga)

        except Exception as e:
            session.rollback()
            logger.error(f"Saga {saga_id} failed unexpectedly: {e}")
            raise
        finally:
            session.close()

    def _compensate(self, session: Session, saga: SagaInstance, reason: str) -> dict:
        """Execute compensating transactions when a forward step fails after payment."""

        logger.info(f"Saga {saga.saga_id}: starting compensation — {reason}")

        # Compensate: refund payment
        if saga.payment_id:
            _transition(session, saga, SagaState.REFUNDING, "compensate_refund_start", step_type="COMPENSATE")
            session.commit()

            refund_idem_key = generate_idempotency_key(saga.saga_id, "payment", "refund")
            try:
                refund_result = self.payment.refund(saga.order_id, saga.payment_id, refund_idem_key)
                saga.refund_id = refund_result.get("payment_id")
                _transition(session, saga, SagaState.REFUNDED, "compensate_refund_done", step_type="COMPENSATE", detail=saga.refund_id)
            except Exception as e:
                logger.error(f"Refund failed for saga {saga.saga_id}: {e}")
                _transition(session, saga, SagaState.MANUAL_REVIEW, "compensate_refund_failed", step_type="COMPENSATE", detail=str(e))
                saga.error_reason = f"Compensation failed: {e}"
                saga.completed_at = datetime.now(UTC)
                session.commit()
                return self._saga_result(saga)

        _transition(session, saga, SagaState.CANCELLED, "saga_cancelled", step_type="COMPENSATE", detail=reason)
        saga.error_reason = reason
        saga.completed_at = datetime.now(UTC)
        session.commit()

        # Update order service
        if self.order:
            try:
                self.order.update_status(order_id=saga.order_id, new_status=SagaState.CANCELLED.value)
            except Exception as e:
                logger.warning(f"Failed to update order to CANCELLED: {e}")

        return self._saga_result(saga)

    def _saga_result(self, saga: SagaInstance) -> dict:
        """Build a result dict from the saga instance."""
        return {
            "saga_id": saga.saga_id,
            "order_id": saga.order_id,
            "state": saga.current_state,
            "payment_id": saga.payment_id,
            "reservation_id": saga.reservation_id,
            "refund_id": saga.refund_id,
            "eta_minutes": saga.eta_minutes,
            "eta_lower": saga.eta_lower,
            "eta_upper": saga.eta_upper,
            "degraded": bool(saga.degraded),
            "error_reason": saga.error_reason,
        }

    def get_saga_status(self, order_id: str) -> dict | None:
        """Look up saga state by order ID."""
        session = self.session_factory()
        try:
            saga = session.query(SagaInstance).filter(SagaInstance.order_id == order_id).first()
            if not saga:
                return None
            return self._saga_result(saga)
        finally:
            session.close()

    def get_saga_steps(self, saga_id: str) -> list[dict]:
        """Retrieve the full step log for a saga."""
        session = self.session_factory()
        try:
            logs = (
                session.query(SagaStepLog)
                .filter(SagaStepLog.saga_id == saga_id)
                .order_by(SagaStepLog.id)
                .all()
            )
            return [
                {
                    "step": log.step_name,
                    "from": log.from_state,
                    "to": log.to_state,
                    "type": log.step_type,
                    "detail": log.detail,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                }
                for log in logs
            ]
        finally:
            session.close()
