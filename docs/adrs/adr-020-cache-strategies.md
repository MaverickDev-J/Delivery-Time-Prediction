# ADR 020 — Cache Invalidation Strategies

**Status**: Accepted  
**Date**: 2026-08-20  
**Decision**: Five caches, five different strategies — each chosen for the specific consistency requirement.

## Context

"There are only two hard things in Computer Science: cache invalidation and naming things."

DeliverIQ uses caching at multiple layers. The key insight: **there is no single "best" cache strategy.** Each cache has different consistency requirements, and the strategy must match.

## Decision

| Cache | Strategy | TTL | Consistency | Why This Strategy |
|---|---|---|---|---|
| **Idempotency** | Write-through (Redis + DB) | 24h | **Strong** | Correctness is non-negotiable. A missed cache entry → one extra DB lookup, not a double charge. Redis is the fast path; DB is the source of truth. |
| **Degraded ETA** | Precompute + TTL | 1h | **Eventual** | Fallback value, not on critical path. Stale by up to 1 hour is acceptable because it's only used when the ML service is down. |
| **Rate Limit Counters** | Sliding window in Redis | Window-based | **Strong** | Must be accurate — can't allow over-limit requests. Redis ZSET with timestamp scores provides exact counting within the sliding window. |
| **Order Read Cache** | Cache-aside + TTL | 30s | **Eventual** | Read-heavy endpoint (order history). Orders rarely change state after confirmation. 30s staleness is invisible to users. |
| **Session/Auth** | JWT (stateless, no cache) | 15m (token TTL) | **Eventual** | JWTs are self-contained. No cache to invalidate. Role changes take effect on next token refresh. |

## Cache-Aside Pattern (Order Read Cache)

```python
def get_order(order_id: str) -> Order:
    # 1. Try cache
    cached = redis.get(f"order:{order_id}")
    if cached:
        return Order(**json.loads(cached))

    # 2. Cache miss → read from DB
    order = db.query(Order).filter(Order.order_id == order_id).first()

    # 3. Populate cache (if found)
    if order:
        redis.setex(f"order:{order_id}", 30, order.to_json())

    return order
```

## Write-Through Pattern (Idempotency)

```python
def set_idempotent_result(key: str, result: dict):
    # Write to BOTH Redis (fast path) and DB (truth) in same flow
    redis.setex(f"idem:{key}", 86400, json.dumps(result))
    db.execute("INSERT INTO idempotency_store ...")
    db.commit()

def get_idempotent_result(key: str) -> dict | None:
    # Try Redis first (fast)
    cached = redis.get(f"idem:{key}")
    if cached:
        return json.loads(cached)

    # Fallback to DB (slow but always correct)
    row = db.execute("SELECT * FROM idempotency_store WHERE key = ?", key)
    if row:
        # Repopulate Redis for next time
        redis.setex(f"idem:{key}", 86400, json.dumps(row.result))
        return row.result
    return None
```

## When NOT to Cache

1. **Writes**: Never cache writes. The order creation flow writes to the DB and outbox atomically — no cache layer.
2. **Saga state**: Saga state changes rapidly during execution. Caching would cause stale reads during the ~500ms saga lifetime.
3. **Payment status**: Financial data must always be fresh. Read from DB.

## Consequences

- Each caching decision is documented and defensible.
- No "just throw Redis in front of it" cargo cult caching.
- Monitoring: cache hit/miss ratio per cache type (Prometheus counter).
- Migration path: if any cache proves insufficient, the strategies can be upgraded independently.
