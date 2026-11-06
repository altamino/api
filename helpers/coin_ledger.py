"""Coin statement for GET /g/s/wallet/coin/history.

An entry is written right after each balance change and stores the balance read back from the
account, so the list shows the resulting total. History before this ledger existed cannot be
rebuilt from the current balance and is not invented. A ledger failure never undoes the
operation that changed the coins; it is logged instead.
"""

from datetime import UTC, datetime
from time import time_ns
from uuid import uuid4
import logging

log = logging.getLogger(__name__)


async def record(db, uid: str | None, amount, reason: str, ndcId: int = 0, **ext):
    if not uid or not amount:
        return
    try:
        row = await db.get(table="Users").find_one({"id": uid}, {"coins": 1})
        await db.get(table="CoinHistory").insert_one(
            {
                "id": str(uuid4()),
                "uid": uid,
                "ndcId": ndcId,
                "reason": reason,
                "amount": round(float(amount), 2),
                "balanceAfter": round(float((row or {}).get("coins", 0.0)), 2),
                "createdTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "seq": time_ns(),
                "ext": ext,
            }
        )
    except Exception:
        log.exception("coin ledger write failed (uid=%s reason=%s)", uid, reason)


async def debit(db, uid: str, coins) -> bool:
    """Atomic debit: succeeds only when the balance covers it (no double spending)."""
    result = await db.get(table="Users").update_one(
        {"id": uid, "coins": {"$gte": coins}}, {"$inc": {"coins": -coins}}
    )
    return result.modified_count == 1
