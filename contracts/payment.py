"""Payment domain contracts."""

from enum import Enum

from pydantic import BaseModel, Field


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class AuthorizePaymentRequest(BaseModel):
    order_id: str = Field(..., description="Order to authorize payment for")
    amount: float = Field(..., gt=0, description="Amount to authorize in INR")
    idempotency_key: str = Field(..., description="Client-generated idempotency key")


class RefundPaymentRequest(BaseModel):
    order_id: str = Field(..., description="Order to refund")
    payment_id: str = Field(..., description="Original payment transaction ID")
    idempotency_key: str = Field(..., description="Client-generated idempotency key")


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    amount: float
    status: PaymentStatus
    idempotency_key: str
    message: str | None = None
