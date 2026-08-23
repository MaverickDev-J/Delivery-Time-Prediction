# ADR 019 — Connection Pool Sizing

**Status**: Accepted  
**Date**: 2026-08-20  
**Decision**: `pool_size=3`, `max_overflow=2` per service. Rationale derived from Little's Law.

## Context

DeliverIQ has ~10 services, each running 2 uvicorn workers, each maintaining a SQLAlchemy connection pool to PostgreSQL.

PostgreSQL default `max_connections = 100`.

**The math**:
- 10 services × 2 workers × pool_size 5 = **100 connections** (at the default pool size)
- Add one more service → **110 connections → connection refused**

This is a common production failure mode.

## Decision

### Pool Configuration

```python
# core/database.py
create_engine(
    url,
    pool_size=3,        # 3 persistent connections per worker
    max_overflow=2,      # 2 additional connections allowed under burst
    pool_timeout=10,     # Wait 10s for a connection before raising
    pool_recycle=1800,   # Recycle connections every 30 min (prevents stale connections)
    pool_pre_ping=True,  # Test connection health before use
)
```

### Revised Math

- 10 services × 2 workers × (3 + 2) = **100 connections max** (but overflow connections are temporary)
- Steady state: 10 × 2 × 3 = **60 connections** (well within limit)
- Peak: up to 100, which is fine

### Little's Law Rationale

```
Pool size ≥ Concurrent queries = Request rate × Avg query duration
```

For the order service:
- Request rate: ~10 orders/second (peak)
- Avg query duration: ~5ms
- Concurrent queries: 10 × 0.005 = 0.05

So even `pool_size=1` would theoretically suffice. We use 3 for headroom:
- One connection for the active request
- One for background tasks (outbox relay)
- One spare for connection health check overlap

### Why Pool Size ≠ Worker Count

A common misconception: "I have 2 workers, so I need pool_size=2."

Wrong. A worker only holds a connection during actual database I/O. During the rest of the request lifecycle (JSON parsing, serialization, network I/O, business logic), the connection is idle in the pool.

The only exception: long-running transactions that hold connections open (which is why we keep transactions short — in/out in <10ms).

## Consequences

- Monitor pool utilization via `pool.status()` and expose as Prometheus gauge.
- If `max_overflow` connections are frequently created, increase `pool_size`.
- When adding new services, verify total connection count stays under `max_connections`.
- For production with 50+ services, consider PgBouncer (connection pooler) instead of per-service pools.
