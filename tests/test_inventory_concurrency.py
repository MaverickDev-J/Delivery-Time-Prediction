"""
High-Concurrency Flash Sale Stress Test.

Simulates 20 to 50 concurrent customer requests hitting the inventory service
at the exact same millisecond racing for the very last item of stock (Stock = 1).

Guarantees:
  1. Exactly 1 request acquires the stock reservation (200 OK).
  2. All other requests are safely rejected (409 Conflict / Out of Stock).
  3. Database stock invariant holds: final stock is exactly 0 (NEVER negative).
  4. Optimistic locking / atomic updates prevent race conditions and overselling.
"""

import asyncio
import os
import uuid
import pytest
import httpx
from core.database import create_db_engine, create_session_factory
from services.inventory.app import InventoryItem, Reservation

INVENTORY_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8003")
DB_URL = os.getenv("INVENTORY_DATABASE_URL", "postgresql://deliveriq:deliveriq_password@localhost:5432/inventory_db")


@pytest.mark.asyncio
async def test_flash_sale_concurrency_race_condition():
    """
    Race Condition Benchmark:
    Initialize item with stock = 1.
    Launch 20 concurrent threads trying to reserve that 1 item simultaneously.
    Verify that exactly 1 wins and 19 fail without overselling.
    """
    flash_item_id = f"FLASH-ITEM-{uuid.uuid4().hex[:6].upper()}"
    num_concurrent_users = 20

    # 1. Direct DB Setup: Insert test item with stock = 1
    engine = create_db_engine(DB_URL)
    SessionFactory = create_session_factory(engine)
    with SessionFactory() as session:
        item = InventoryItem(
            item_id=flash_item_id,
            name="Limited Edition Flash Biryani",
            stock=1,
        )
        session.add(item)
        session.commit()

    # 2. Concurrency Runner: Fire 20 requests at the exact same millisecond
    async def make_reservation_request(user_idx: int):
        order_id = f"ORD-RACE-{user_idx}-{uuid.uuid4().hex[:4].upper()}"
        idem_key = f"IDEM-RACE-{user_idx}-{uuid.uuid4().hex[:6]}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    f"{INVENTORY_URL}/inventory/reserve",
                    json={
                        "order_id": order_id,
                        "items": [flash_item_id],
                    },
                    headers={"Idempotency-Key": idem_key},
                )
                return resp.status_code, resp.json()
            except Exception as e:
                return 500, {"error": str(e)}

    # Launch all 20 coroutines in parallel
    tasks = [make_reservation_request(i) for i in range(num_concurrent_users)]
    results = await asyncio.gather(*tasks)

    # 3. Analyze Results
    success_count = 0
    conflict_count = 0
    other_errors = 0

    for status_code, body in results:
        if status_code == 200 and body.get("status") == "RESERVED":
            success_count += 1
        elif status_code == 409 or body.get("status") == "OUT_OF_STOCK" or "out of stock" in str(body).lower():
            conflict_count += 1
        else:
            other_errors += 1

    # 4. Verify DB Invariants
    with SessionFactory() as session:
        final_item = session.query(InventoryItem).filter_by(item_id=flash_item_id).first()
        final_stock = final_item.stock if final_item else -1
        total_reservations = session.query(Reservation).filter(Reservation.items.like(f"%{flash_item_id}%")).count()

    print(f"\n================ FLASH SALE CONCURRENCY REPORT ================")
    print(f"Total Concurrent Shoppers:  {num_concurrent_users}")
    print(f"Initial Stock:              1")
    print(f"Successful Reservations:    {success_count}  (Expected: 1)")
    print(f"Rejected / Out of Stock:    {conflict_count} (Expected: {num_concurrent_users - 1})")
    print(f"Final Inventory in DB:      {final_stock}    (Must be: 0, NEVER negative)")
    print(f"Total DB Reservation Rows:  {total_reservations} (Must be: 1)")
    print(f"===============================================================")

    # Assertions
    assert success_count == 1, f"Expected exactly 1 successful reservation, got {success_count}"
    assert conflict_count == num_concurrent_users - 1, f"Expected {num_concurrent_users - 1} rejections, got {conflict_count}"
    assert final_stock == 0, f"Critical Bug: Final stock is {final_stock}, expected 0 (overselling detected!)"
    assert total_reservations == 1, f"Expected exactly 1 reservation row in DB, got {total_reservations}"
