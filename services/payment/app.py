"""
Payment Service — authorize and refund payments.

Supports injectable chaos for demo/testing:
  - PAYMENT_FAIL_RATE: Probability of random authorization failure (0.0-1.0)
  - PAYMENT_LATENCY_MS: Artificial latency injected before response
  - PAYMENT_ALWAYS_FAIL_OVER: Always decline amounts above this threshold
"""

import os
import random
import time
import uuid

from fastapi import FastAPI, HTTPException

from contracts.payment import (
    AuthorizePaymentRequest,
    PaymentResponse,
    PaymentStatus,
    RefundPaymentRequest,
)
from core.database import Base, create_db_engine, create_session_factory, get_session, init_tables
from core.idempotency import IdempotencyStore
from core.logging import setup_logger
from core.metrics import add_metrics_middleware, expose_metrics

logger = setup_logger("payment-service", service_name="payment-service")

# Database
DATABASE_URL = os.getenv("PAYMENTS_DATABASE_URL", "sqlite:///data/payments.db")
engine = create_db_engine(DATABASE_URL)
SessionFactory = create_session_factory(engine)

# Inline model — simple enough to not need a separate file
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String(64), unique=True, nullable=False)
    order_id = Column(String(64), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(32), nullable=False)
    idempotency_key = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


init_tables(engine, Base)

# Idempotency
idem_store = IdempotencyStore()

# Chaos configuration
FAIL_RATE = float(os.getenv("PAYMENT_FAIL_RATE", "0.0"))
LATENCY_MS = int(os.getenv("PAYMENT_LATENCY_MS", "0"))
ALWAYS_FAIL_OVER = float(os.getenv("PAYMENT_ALWAYS_FAIL_OVER", "999999"))

app = FastAPI(title="DeliverIQ Payment Service", version="1.0.0")
add_metrics_middleware(app, service_name="payment")
expose_metrics(app)


@app.get("/health")
def health():
    return {"status": "UP", "service": "payment-service"}


@app.post("/payments/authorize", response_model=PaymentResponse)
def authorize_payment(request: AuthorizePaymentRequest):
    """Authorize a payment. Idempotent by idempotency_key."""

    # Idempotency check
    cached = idem_store.get(request.idempotency_key)
    if cached:
        return PaymentResponse(**cached["response"])

    # Inject chaos latency
    if LATENCY_MS > 0:
        time.sleep(LATENCY_MS / 1000.0)

    payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"

    # Determine success/failure
    should_fail = (
        request.amount > ALWAYS_FAIL_OVER
        or random.random() < FAIL_RATE
    )

    payment_status = PaymentStatus.DECLINED if should_fail else PaymentStatus.AUTHORIZED
    message = "Payment declined by issuing bank" if should_fail else "Payment authorized successfully"

    with get_session(SessionFactory) as session:
        payment = Payment(
            payment_id=payment_id,
            order_id=request.order_id,
            amount=request.amount,
            status=payment_status.value,
            idempotency_key=request.idempotency_key,
        )
        session.add(payment)

    response = PaymentResponse(
        payment_id=payment_id,
        order_id=request.order_id,
        amount=request.amount,
        status=payment_status,
        idempotency_key=request.idempotency_key,
        message=message,
    )

    idem_store.set(request.idempotency_key, response.model_dump())
    logger.info(f"Payment {payment_id} for order {request.order_id}: {payment_status.value}")
    return response


@app.post("/payments/refund", response_model=PaymentResponse)
def refund_payment(request: RefundPaymentRequest):
    """Issue a compensating refund. Idempotent by idempotency_key."""

    # Idempotency check
    cached = idem_store.get(request.idempotency_key)
    if cached:
        return PaymentResponse(**cached["response"])

    with get_session(SessionFactory) as session:
        original = session.query(Payment).filter(Payment.payment_id == request.payment_id).first()
        if not original:
            raise HTTPException(status_code=404, detail=f"Payment {request.payment_id} not found")

        refund_id = f"REF-{uuid.uuid4().hex[:12].upper()}"

        refund = Payment(
            payment_id=refund_id,
            order_id=request.order_id,
            amount=-original.amount,  # Negative = refund
            status=PaymentStatus.REFUNDED.value,
            idempotency_key=request.idempotency_key,
        )
        session.add(refund)

        # Mark original as refunded
        original.status = PaymentStatus.REFUNDED.value

    response = PaymentResponse(
        payment_id=refund_id,
        order_id=request.order_id,
        amount=original.amount,
        status=PaymentStatus.REFUNDED,
        idempotency_key=request.idempotency_key,
        message=f"Refund issued for original payment {request.payment_id}",
    )

    idem_store.set(request.idempotency_key, response.model_dump())
    logger.info(f"Refund {refund_id} issued for payment {request.payment_id}")
    return response
