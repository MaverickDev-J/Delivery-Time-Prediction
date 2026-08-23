# ADR 017 — Transaction Isolation Levels

**Status**: Accepted  
**Date**: 2026-08-20  
**Decision**: Use `READ COMMITTED` everywhere, with explicit locking where needed.

## Context

PostgreSQL supports four isolation levels: READ UNCOMMITTED (treated as READ COMMITTED), READ COMMITTED, REPEATABLE READ, and SERIALIZABLE. Each trades off between correctness and throughput.

DeliverIQ has 7 microservices, each with its own database. The question is: what isolation level should each service use, and why?

## Decision

### Service-Level Isolation Choices

| Service | Isolation Level | Locking Strategy | Rationale |
|---|---|---|---|
| **Order Service** | READ COMMITTED | Idempotency constraint on `idempotency_key` | The idempotency key UNIQUE constraint prevents duplicate orders. No need for higher isolation — the constraint does the work. |
| **Payment Service** | READ COMMITTED | Idempotency constraint on `idempotency_key` | Same as order service. The payment's idempotency key ensures at-most-once charging. |
| **Inventory Service** | READ COMMITTED | Optimistic locking (version column) + `CHECK (quantity >= 0)` | See ADR 018. Version column detects concurrent modifications. CHECK constraint makes oversell impossible at the DB level. |
| **Saga Orchestrator** | READ COMMITTED | `SELECT ... FOR UPDATE` on saga row | Only one process should advance a saga at a time. FOR UPDATE takes a row-level lock. |
| **Outbox Relay** | READ COMMITTED | `SELECT ... FOR UPDATE SKIP LOCKED` | Multiple relay instances can run concurrently. SKIP LOCKED lets each instance grab a different batch without blocking. |
| **Auth Service** | READ COMMITTED | UNIQUE constraint on email | Duplicate email detection via constraint, not isolation level. |
| **Webhook Service** | READ COMMITTED | Append-only delivery log | Deliveries are insert-only. No concurrent update conflicts possible. |

### Why Not REPEATABLE READ?

REPEATABLE READ snapshots the database at transaction start. This causes problems for our use cases:

1. **Outbox Relay**: Under REPEATABLE READ, `SKIP LOCKED` doesn't work correctly. A row that was modified after the snapshot raises serialization error `40001` instead of being cleanly skipped. This defeats the purpose of concurrent relays.

2. **Saga State Machine**: Under REPEATABLE READ, a saga that was advanced by another process since our snapshot would cause a serialization failure. With READ COMMITTED + FOR UPDATE, we simply wait for the lock and see the latest state.

### Why Not SERIALIZABLE?

Serializable isolation prevents all anomalies but requires serialization failure retry loops. For our workload (moderate concurrency, explicit locking where needed), the retry overhead isn't justified.

## Consequences

- Every service uses the PostgreSQL default (READ COMMITTED), so no special configuration needed.
- Correctness relies on explicit mechanisms (constraints, version columns, row locks) rather than implicit isolation guarantees.
- This is the standard approach used by Stripe, Shopify, and most production systems.
