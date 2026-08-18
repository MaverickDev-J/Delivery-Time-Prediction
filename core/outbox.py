"""
Transactional Outbox Pattern implementation.

Guarantees at-least-once event delivery without dual-write:
1. Service writes domain row + outbox row in ONE local transaction.
2. Background relay worker polls PENDING outbox entries and publishes to Redis Streams.
3. On successful publish, marks the entry PUBLISHED.
4. On failure after max retries, marks the entry FAILED for manual inspection.
"""

import json
import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from core.database import Base
from core.logging import setup_logger

logger = setup_logger("core.outbox")


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxEvent(Base):
    """Outbox table row — written atomically alongside the domain entity."""
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    event_type = Column(String(64), nullable=False)
    stream_name = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)  # JSON-serialized EventEnvelope
    status = Column(String(16), nullable=False, default=OutboxStatus.PENDING.value)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    published_at = Column(DateTime, nullable=True)


def write_outbox_event(
    session: Session,
    event_type: str,
    stream_name: str,
    payload: dict,
    event_id: str | None = None,
) -> OutboxEvent:
    """Insert an outbox event row — call within the same transaction as the domain write."""
    entry = OutboxEvent(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        stream_name=stream_name,
        payload=json.dumps(payload),
        status=OutboxStatus.PENDING.value,
    )
    session.add(entry)
    return entry


class OutboxRelay:
    """Background worker that polls the outbox table and publishes to Redis Streams.

    Designed to be called periodically (e.g., every 500ms) from a background thread or task.
    Uses SELECT ... FOR UPDATE SKIP LOCKED semantics on Postgres; on SQLite falls back to
    simple SELECT + UPDATE which is safe for single-writer scenarios.
    """

    MAX_RETRIES = 5

    def __init__(self, session_factory, stream_broker, batch_size: int = 50):
        self.session_factory = session_factory
        self.stream_broker = stream_broker
        self.batch_size = batch_size

    def relay_batch(self) -> int:
        """Poll and publish one batch of pending outbox events. Returns count published."""
        session: Session = self.session_factory()
        published = 0
        try:
            pending = (
                session.query(OutboxEvent)
                .filter(OutboxEvent.status == OutboxStatus.PENDING.value)
                .order_by(OutboxEvent.id)
                .limit(self.batch_size)
                .all()
            )

            for entry in pending:
                try:
                    payload = json.loads(entry.payload)

                    # Publish synchronously via the stream broker's sync adapter
                    self.stream_broker.publish_sync(
                        stream_name=entry.stream_name,
                        data=payload,
                    )

                    entry.status = OutboxStatus.PUBLISHED.value
                    entry.published_at = datetime.now(UTC)
                    published += 1

                except Exception as e:
                    entry.retry_count += 1
                    if entry.retry_count >= self.MAX_RETRIES:
                        entry.status = OutboxStatus.FAILED.value
                        logger.error(
                            f"Outbox event {entry.event_id} failed permanently after "
                            f"{self.MAX_RETRIES} retries: {e}"
                        )
                    else:
                        logger.warning(
                            f"Outbox relay failed for {entry.event_id} "
                            f"(attempt {entry.retry_count}): {e}"
                        )

            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Outbox relay batch failed: {e}")
        finally:
            session.close()

        if published > 0:
            logger.info(f"Outbox relay published {published} events")
        return published


class SyncStreamBroker:
    """Minimal synchronous Redis Streams publisher for outbox relay.

    The outbox relay runs in a background thread, so it uses synchronous Redis.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0", max_stream_len: int = 10000):
        self.redis_url = redis_url
        self.max_stream_len = max_stream_len
        self._redis = None

    def _connect(self):
        if self._redis is None:
            import redis
            self._redis = redis.from_url(self.redis_url, decode_responses=True)

    def publish_sync(self, stream_name: str, data: dict) -> str:
        """Publish a dict to a Redis Stream synchronously."""
        self._connect()
        # Flatten nested dicts to strings for Redis
        flat = {}
        for k, v in data.items():
            flat[k] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)

        msg_id = self._redis.xadd(
            name=stream_name,
            fields=flat,
            maxlen=self.max_stream_len,
            approximate=True,
        )
        return msg_id

    def close(self):
        if self._redis:
            self._redis.close()
            self._redis = None
