import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as aioredis

from contracts.events import EventEnvelope
from core.logging import setup_logger

logger = setup_logger("core.streams")


class RedisStreamBroker:
    """Helper for publishing and consuming events using Redis Streams."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", max_stream_len: int = 10000):
        self.redis_url = redis_url
        self.max_stream_len = max_stream_len
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        if not self._redis:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"Connected to Redis at {self.redis_url}")

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def publish(self, stream_name: str, event: EventEnvelope) -> str:
        """Publish an EventEnvelope to the specified Redis Stream."""
        if not self._redis:
            await self.connect()

        payload_dict = event.to_stream_dict()
        msg_id = await self._redis.xadd(
            name=stream_name,
            fields=payload_dict,
            maxlen=self.max_stream_len,
            approximate=True,
        )
        logger.info(f"Published event '{event.event_type}' [{event.event_id}] to stream '{stream_name}' with ID {msg_id}")
        return msg_id

    async def create_consumer_group(self, stream_name: str, group_name: str) -> None:
        """Create consumer group if it does not already exist."""
        if not self._redis:
            await self.connect()

        try:
            await self._redis.xgroup_create(name=stream_name, groupname=group_name, id="0", mkstream=True)
            logger.info(f"Created consumer group '{group_name}' for stream '{stream_name}'")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                pass  # Group already exists
            else:
                logger.error(f"Error creating consumer group: {e}")
                raise

    async def send_to_dlq(self, dlq_stream: str, raw_message: dict[str, Any], error_reason: str) -> str:
        """Send unprocessable/poison messages to a Dead-Letter Queue stream."""
        if not self._redis:
            await self.connect()

        dlq_entry = {
            "error_reason": error_reason,
            "original_message": json.dumps(raw_message),
        }
        dlq_id = await self._redis.xadd(name=dlq_stream, fields=dlq_entry, maxlen=self.max_stream_len)
        logger.warning(f"Sent message to DLQ '{dlq_stream}' with ID {dlq_id} | Reason: {error_reason}")
        return dlq_id

    async def consume_loop(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        handler: Callable[[EventEnvelope], Coroutine[Any, Any, None]],
        dlq_stream: str | None = None,
        batch_size: int = 10,
        block_ms: int = 2000,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuous consumer loop reading messages from group, handling, and acknowledging."""
        await self.create_consumer_group(stream_name, group_name)
        dlq_name = dlq_stream or f"dlq:{stream_name}"

        logger.info(f"Starting consumer '{consumer_name}' on group '{group_name}' for stream '{stream_name}'")

        while stop_event is None or not stop_event.is_set():
            try:
                # Read new messages using special '>' ID
                messages = await self._redis.xreadgroup(
                    groupname=group_name,
                    consumername=consumer_name,
                    streams={stream_name: ">"},
                    count=batch_size,
                    block=block_ms,
                )

                if not messages:
                    await asyncio.sleep(0.1)
                    continue

                for _, stream_msgs in messages:
                    for msg_id, raw_fields in stream_msgs:
                        try:
                            envelope = EventEnvelope.from_stream_dict(raw_fields)
                            await handler(envelope)
                            # Acknowledge processed message
                            await self._redis.xack(stream_name, group_name, msg_id)
                        except Exception as err:
                            logger.error(f"Failed to process message {msg_id}: {err}")
                            await self.send_to_dlq(dlq_name, raw_fields, str(err))
                            await self._redis.xack(stream_name, group_name, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in stream consume loop: {e}")
                await asyncio.sleep(1.0)
