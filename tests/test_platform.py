from contracts.events import EventEnvelope, EventType
from core.http import CircuitBreaker, CircuitState


def test_circuit_breaker_transitions():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, name="test_circuit")
    assert cb.state == CircuitState.CLOSED

    # Record 1 failure -> still CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    # Record 2nd failure -> transitions to OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Check state before recovery timeout -> still OPEN
    cb._check_state()
    assert cb.state == CircuitState.OPEN

    # Record success resets
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_event_envelope_roundtrip():
    envelope = EventEnvelope(
        event_type=EventType.ORDER_CREATED,
        correlation_id="corr-12345",
        idempotency_key="idem-999",
        payload={"order_id": "ORD-101", "total_amount": 450.0},
    )

    stream_dict = envelope.to_stream_dict()
    assert stream_dict["event_type"] == "order.created"
    assert stream_dict["correlation_id"] == "corr-12345"

    reconstructed = EventEnvelope.from_stream_dict(stream_dict)
    assert reconstructed.event_id == envelope.event_id
    assert reconstructed.event_type == EventType.ORDER_CREATED
    assert reconstructed.payload["order_id"] == "ORD-101"
    assert reconstructed.payload["total_amount"] == 450.0
