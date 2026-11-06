"""Coin renewals: Amino+ (global Users.aminoPlus) and fan club subscriptions (FanSubscriptions).

A renewal is due when the paid period ended and auto-renew is on. It charges one period at the
current price, only if the balance covers it, and only once: every write is conditioned on the
expiry it read, so concurrent sweeps or reads never bill twice. Missed periods are not billed
retroactively. Without coins (or with auto-renew off) the subscription simply ends.

`lifespan` runs the sweep every minute; the same functions also run on demand when a member's
status is read, so nobody depends on the timer to see a renewal.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from helpers import coin_ledger
from helpers.fan_access import utcnow

log = logging.getLogger(__name__)

AMINO_PLUS_PRICE = int(os.environ.get("AMINO_PLUS_PRICE_COINS", "500"))
AMINO_PLUS_COIN_SALES_ENABLED = False  # Owner withdrew coin purchases and renewals.
PERIOD = timedelta(days=30)
SWEEP_SECONDS = 60


async def renew_amino_plus(db, user: dict) -> dict:
    """Process one coin-paid Amino+ account; returns the up-to-date user row."""
    users = db.get(table="Users")
    plan = user.get("aminoPlus") or {}
    expires = plan.get("expiresAt")
    if (
        plan.get("source") != "coins"
        or not user.get("isPaidSubscriber")
        or not expires
        or expires > utcnow()
    ):
        return user
    now = utcnow()
    if AMINO_PLUS_COIN_SALES_ENABLED and plan.get("autoRenew"):
        renewed = await users.update_one(
            {
                "id": user["id"],
                "aminoPlus.source": "coins",
                "aminoPlus.expiresAt": expires,
                "coins": {"$gte": AMINO_PLUS_PRICE},
            },
            {
                "$inc": {"coins": -AMINO_PLUS_PRICE},
                "$set": {
                    "aminoPlus.expiresAt": now + PERIOD,
                    "aminoPlus.lastRenewedAt": now,
                    "isPaidSubscriber": True,
                },
            },
        )
        if renewed.modified_count:
            await coin_ledger.record(
                db, user["id"], -AMINO_PLUS_PRICE, "amino_plus_subscription"
            )
            return await users.find_one({"id": user["id"]}) or user
    # no auto-renew or not enough coins: the membership ends (manual grants never carry source "coins")
    await users.update_one(
        {"id": user["id"], "aminoPlus.source": "coins", "aminoPlus.expiresAt": expires},
        {
            "$set": {
                "isPaidSubscriber": False,
                "aminoPlus.source": "coins_expired",
                "aminoPlus.autoRenew": False,
            }
        },
    )
    return await users.find_one({"id": user["id"]}) or user


async def renew_fan_subscription(db, sub: dict) -> dict | None:
    """Process one fan subscription; returns the row if it is (still) active, else None."""
    subs = db.get(table="FanSubscriptions")
    expires = sub.get("expiresAt")
    if expires and expires > utcnow():
        return sub
    if not sub.get("isAutoRenew"):
        return None
    club = await db.get(table="FanClubs").find_one(
        {"ndcId": sub["ndcId"], "creatorUid": sub["creatorUid"], "enabled": True}
    )
    fee = int((club or {}).get("monthlyFee") or 0)
    now = utcnow()
    charged = False
    if club and fee > 0:
        charged = (
            await db.get(table="Users").update_one(
                {"id": sub["fanUid"], "coins": {"$gte": fee}}, {"$inc": {"coins": -fee}}
            )
        ).modified_count == 1
    if charged:
        extended = await subs.update_one(
            {"_id": sub["_id"], "expiresAt": expires, "isAutoRenew": True},
            {"$set": {"expiresAt": now + PERIOD, "lastRenewedAt": now}},
        )
        if extended.modified_count:
            await db.get(table="Users").update_one(
                {"id": sub["creatorUid"]}, {"$inc": {"coins": fee}}
            )
            await coin_ledger.record(
                db,
                sub["fanUid"],
                -fee,
                "fan_subscription",
                sub["ndcId"],
                creatorUid=sub["creatorUid"],
            )
            await coin_ledger.record(
                db,
                sub["creatorUid"],
                fee,
                "fan_income",
                sub["ndcId"],
                fanUid=sub["fanUid"],
            )
            return await subs.find_one({"_id": sub["_id"]})
        # another sweep renewed it first: give the coins back
        await db.get(table="Users").update_one(
            {"id": sub["fanUid"]}, {"$inc": {"coins": fee}}
        )
        current = await subs.find_one({"_id": sub["_id"]})
        return (
            current
            if current and current.get("expiresAt") and current["expiresAt"] > utcnow()
            else None
        )
    await subs.update_one(
        {"_id": sub["_id"], "expiresAt": expires}, {"$set": {"isAutoRenew": False}}
    )
    try:
        from routers.fan_clubs import _sync_profile

        await _sync_profile(db, sub["ndcId"], sub["creatorUid"])
    except Exception:
        log.exception("fan club profile sync failed")
    return None


async def sweep_once():
    from helpers.database.mongo import Database

    db = await Database().init()
    try:
        now = utcnow()
        async for user in (
            db.get(table="Users")
            .find(
                {
                    "aminoPlus.source": "coins",
                    "isPaidSubscriber": True,
                    "aminoPlus.expiresAt": {"$lte": now},
                }
            )
            .limit(200)
        ):
            try:
                await renew_amino_plus(db, user)
            except Exception:
                log.exception("Amino+ renewal failed (uid=%s)", user.get("id"))
        async for sub in (
            db.get(table="FanSubscriptions")
            .find({"isAutoRenew": True, "expiresAt": {"$lte": now}})
            .limit(200)
        ):
            try:
                await renew_fan_subscription(db, sub)
            except Exception:
                log.exception("fan subscription renewal failed")
    finally:
        db.close()


async def renewal_loop():
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "renewal sweep failed"
            )  # never stop the API; retried next tick
        await asyncio.sleep(SWEEP_SECONDS)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(renewal_loop())
    try:
        yield
    finally:
        task.cancel()
