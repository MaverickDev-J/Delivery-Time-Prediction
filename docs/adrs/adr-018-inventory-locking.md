# ADR 018 — Inventory Locking Strategy (Optimistic Locking + CHECK Constraint)

**Status**: Accepted  
**Date**: 2026-08-20  
**Decision**: Optimistic locking with version column + DB-level `CHECK (quantity >= 0)`.

## Context

The problem: two concurrent orders for the last unit of stock create a lost-update race condition.

```
Time   Thread A (Order 1)              Thread B (Order 2)
─────  ──────────────────              ──────────────────
T1     SELECT quantity → 1
T2                                     SELECT quantity → 1
T3     UPDATE quantity = 0 ✓
T4                                     UPDATE quantity = 0 ✓ ← OVERSOLD!
```

Both threads read quantity=1, both decrement to 0, and the item is "reserved" twice despite only having 1 unit.

## Options Considered

### Option A: Pessimistic Locking (`SELECT ... FOR UPDATE`)
```sql
SELECT quantity FROM stock WHERE item_id = 'X' FOR UPDATE;
-- Holds a row-level lock until commit
UPDATE stock SET quantity = quantity - 1 WHERE item_id = 'X';
```

**Pros**: Simple, correct.  
**Cons**: Under contention, all orders for the same item serialize through a single lock. If 100 orders for "burger" arrive simultaneously, 99 wait. Throughput drops.

### Option B: Optimistic Locking (version column) ← **CHOSEN**
```sql
UPDATE stock
SET quantity = quantity - 1, version = version + 1
WHERE item_id = 'X' AND version = 42 AND quantity > 0;
-- If rowcount == 0 → conflict or out of stock → retry or reject
```

**Pros**: No lock held during the "think time." Concurrent reads don't block. Only conflicts at write time.  
**Cons**: Under high contention, retries increase. But for food delivery (not stock trading), contention is low.

### Option C: Database CHECK constraint as the safety net
```sql
ALTER TABLE stock ADD CONSTRAINT stock_qty_positive CHECK (quantity >= 0);
```

This is not an alternative to optimistic locking — it's an **additional safety net**. Even if the application has a bug that skips the version check, the DB will refuse to set quantity below zero.

## Decision

**Use Option B + Option C together.**

The version column detects concurrent modifications at the application level. The CHECK constraint makes oversell impossible at the database level. Belt and suspenders.

### Implementation

```python
# services/inventory/app.py
def reserve_stock(item_id: str, quantity: int, expected_version: int):
    result = session.execute(text("""
        UPDATE stock
        SET quantity = quantity - :qty,
            version = version + 1
        WHERE item_id = :item_id
          AND version = :expected_version
          AND quantity >= :qty
    """), {"qty": quantity, "item_id": item_id, "expected_version": expected_version})

    if result.rowcount == 0:
        raise StockConflictError("Version conflict or insufficient stock")
```

### Why This Is the Best Interview Answer

1. **You know both pessimistic and optimistic locking** — and can explain when each is appropriate.
2. **You added a DB-level safety net** — showing defense-in-depth thinking.
3. **You can quantify the tradeoff** — "pessimistic serializes under contention, optimistic retries under contention, and for our workload (food delivery, not stock exchange), contention is low enough that optimistic wins."

## Consequences

- Application must handle `rowcount == 0` (version conflict or out of stock).
- Retries are needed under contention (with exponential backoff).
- CHECK constraint prevents data corruption even if application code has bugs.
- This is the pattern used by Shopify's inventory system.
