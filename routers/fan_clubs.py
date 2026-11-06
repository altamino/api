"""Fan clubs (com.narvii.influencer, APK 3.4): leaders grant a member a club with a monthly fee,
members subscribe with coins for 30 days, and subscribers-only posts require an active subscription.

Global collections: FanClubs {ndcId, creatorUid, monthlyFee, enabled},
FanSubscriptions {ndcId, creatorUid, fanUid, activeFrom, lastRenewedAt, expiresAt, isAutoRenew},
FanPayments {transactionId, ndcId, creatorUid, fanUid, coins} (idempotency of a payment).
Automatic renewal is only stored as a preference; there is no background renewal job.
"""

from datetime import timedelta
from time import time as timestamp

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers import coin_ledger
from helpers.routers.cachable import CachableRoute
from helpers.community_access import is_member, page, paging, profile, staff_level
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.fan_access import active_subscription, club_enabled, utcnow
from objects import Base, Errors

fan_clubs = APIRouter()
fan_clubs.route_class = CachableRoute
PERIOD = timedelta(days=30)
LEADER = 2
_payments_indexed = False


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


async def _sync_profile(db, ndcId: int, creator_uid: str):
    """influencerInfo on the community profile mirrors the club (fee and live fan count)."""
    club = await club_enabled(db, ndcId, creator_uid)
    users = db.get(f"x{ndcId}", "Users")
    if not club:
        await users.update_one({"id": creator_uid}, {"$unset": {"influencerInfo": ""}})
        return
    fans = await db.get(table="FanSubscriptions").count_documents(
        {"ndcId": ndcId, "creatorUid": creator_uid, "expiresAt": {"$gt": utcnow()}}
    )
    await users.update_one(
        {"id": creator_uid},
        {
            "$set": {
                "influencerInfo": {
                    "monthlyFee": club["monthlyFee"],
                    "fansCount": fans,
                    "pinned": False,
                }
            }
        },
    )


async def _fan_club_json(db, ndcId: int, fan_uid: str, creator_uid: str) -> dict:
    sub = await db.get(table="FanSubscriptions").find_one(
        {"ndcId": ndcId, "creatorUid": creator_uid, "fanUid": fan_uid}
    )
    community = await db.get(table="Communities").find_one(
        {"id": ndcId},
        {"_id": 0, "id": 1, "name": 1, "icon": 1, "aminoId": 1, "themeColor": 1},
    )
    active = bool(sub and sub["expiresAt"] > utcnow())
    return {
        "ndcId": ndcId,
        "targetUid": creator_uid,
        "fansStatus": 1 if active else 0,
        "community": {
            "ndcId": ndcId,
            "name": community.get("name"),
            "icon": community.get("icon"),
            "endpoint": community.get("aminoId"),
        }
        if community and sub
        else None,
        "isAutoRenew": bool(sub and sub.get("isAutoRenew")),
        "createdTime": _iso(sub and sub.get("activeFrom")),
        "renewedTime": _iso(sub and sub.get("lastRenewedAt")),
        "expiredTime": _iso(sub and sub.get("expiresAt")),
        "targetUserProfile": await profile(db, ndcId, creator_uid, fan_uid),
    }


@fan_clubs.post("/x{ndcId}/s/influencer/creator-config")
@validauth_required
async def creator_config(request: Request, ndcId: int):
    """The creator tunes their own club; only a leader can grant it in the first place."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        enabled = bool(data["enabled"])
        fee = int(data["monthlyFee"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if not 1 <= fee <= 500:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        clubs = db.get(table="FanClubs")
        if not await clubs.find_one(
            {"ndcId": ndcId, "creatorUid": uid, "granted": True}
        ):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        await clubs.update_one(
            {"ndcId": ndcId, "creatorUid": uid},
            {"$set": {"enabled": enabled, "monthlyFee": fee}},
        )
        await _sync_profile(db, ndcId, uid)
        return Base.Answer(
            {"influencerInfo": {"monthlyFee": fee, "enabled": enabled}},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.post("/x{ndcId}/s/influencer/{creatorUid}")
@validauth_required
async def grant_club(request: Request, ndcId: int, creatorUid: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        fee = int((await request.json())["monthlyFee"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if not 1 <= fee <= 500:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if await staff_level(db, ndcId, uid) < LEADER:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if not await is_member(db, ndcId, creatorUid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        await db.get(table="FanClubs").update_one(
            {"ndcId": ndcId, "creatorUid": creatorUid},
            {"$set": {"monthlyFee": fee, "enabled": True, "granted": True}},
            upsert=True,
        )
        await _sync_profile(db, ndcId, creatorUid)
        return Base.Answer(
            {"uid": creatorUid, "monthlyFee": fee}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@fan_clubs.delete("/x{ndcId}/s/influencer/{creatorUid}")
@validauth_required
async def revoke_club(request: Request, ndcId: int, creatorUid: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if await staff_level(db, ndcId, uid) < LEADER:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        result = await db.get(table="FanClubs").update_one(
            {"ndcId": ndcId, "creatorUid": creatorUid, "granted": True},
            {"$set": {"enabled": False, "granted": False}},
        )
        if result.matched_count == 0:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        await _sync_profile(db, ndcId, creatorUid)
        return Base.Answer(
            {"uid": creatorUid, "removed": True}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@fan_clubs.get("/g/s/influencer/fans")
@fan_clubs.get("/x{ndcId}/s/influencer/fans")
@validauth_required
async def my_subscriptions(
    request: Request,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        subs = db.get(table="FanSubscriptions")
        query = {"fanUid": uid, "expiresAt": {"$gt": utcnow()}}
        total = await subs.count_documents(query)
        rows = [
            r
            async for r in subs.find(query)
            .sort([("lastRenewedAt", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = [
            await _fan_club_json(db, r["ndcId"], uid, r["creatorUid"]) for r in rows
        ]
        return Base.Answer(
            {
                "fanClubList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.get("/x{ndcId}/s/influencer/{creatorUid}")
@validauth_required
async def get_club(request: Request, ndcId: int, creatorUid: str):
    t1 = timestamp()
    db = await Database().init()
    try:
        return Base.Answer(
            {
                "fanClub": await _fan_club_json(
                    db, ndcId, request.state.session["uid"], creatorUid
                )
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.get("/x{ndcId}/s/influencer/{creatorUid}/fans")
@validauth_required
async def club_fans(
    request: Request,
    ndcId: int,
    creatorUid: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        if not await club_enabled(db, ndcId, creatorUid):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        subs = db.get(table="FanSubscriptions")
        query = {
            "ndcId": ndcId,
            "creatorUid": creatorUid,
            "expiresAt": {"$gt": utcnow()},
        }
        total = await subs.count_documents(query)
        rows = [
            r
            async for r in subs.find(query)
            .sort([("activeFrom", DESCENDING)])
            .skip(start)
            .limit(size)
        ]

        async def fan_json(row):
            return {
                "uid": row["fanUid"],
                "fansStatus": 1,
                "expiredTime": _iso(row["expiresAt"]),
                "totalTippedCoins": 0,
                "isTipperAccessible": True,
                "fansUserProfile": await profile(db, ndcId, row["fanUid"], uid),
            }

        mine = await subs.find_one({**query, "fanUid": uid})
        items = [await fan_json(r) for r in rows]
        return Base.Answer(
            {
                "fanClubList": items,
                "myFanClub": await fan_json(mine) if mine else None,
                "influencerUserProfile": await profile(db, ndcId, creatorUid, uid),
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.post("/x{ndcId}/s/influencer/{creatorUid}/subscribe")
@validauth_required
async def subscribe(request: Request, ndcId: int, creatorUid: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ctx = (await request.json())["paymentContext"]
        transaction_id = str(ctx["transactionId"])[:64]
        auto_renew = bool(ctx.get("isAutoRenew", False))
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if uid == creatorUid or not transaction_id:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        payments = db.get(table="FanPayments")
        global _payments_indexed
        if not _payments_indexed:
            await payments.create_index("transactionId", unique=True)
            _payments_indexed = True
        existing = await payments.find_one({"transactionId": transaction_id})
        if existing:  # the same payment retried: never charge twice
            if (existing["fanUid"], existing["creatorUid"], existing["ndcId"]) != (
                uid,
                creatorUid,
                ndcId,
            ):
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            return Base.Answer(
                {"fanClubList": [await _fan_club_json(db, ndcId, uid, creatorUid)]},
                spent_time=timestamp() - t1,
            )
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        club = await club_enabled(db, ndcId, creatorUid)
        if not club or not await is_member(db, ndcId, creatorUid):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        coins = int(club["monthlyFee"])
        # Claim the transaction id first (unique index) so concurrent retries cannot double-charge.
        try:
            await payments.insert_one(
                {
                    "transactionId": transaction_id,
                    "ndcId": ndcId,
                    "creatorUid": creatorUid,
                    "fanUid": uid,
                    "coins": coins,
                    "status": "pending",
                }
            )
        except Exception:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        if not await coin_ledger.debit(db, uid, coins):
            await payments.delete_one(
                {"transactionId": transaction_id, "status": "pending"}
            )
            return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)
        await db.get(table="Users").update_one(
            {"id": creatorUid}, {"$inc": {"coins": coins}}
        )
        await payments.update_one(
            {"transactionId": transaction_id}, {"$set": {"status": "paid"}}
        )
        await coin_ledger.record(
            db, uid, -coins, "fan_subscription", ndcId, creatorUid=creatorUid
        )
        await coin_ledger.record(db, creatorUid, coins, "fan_income", ndcId, fanUid=uid)
        subs = db.get(table="FanSubscriptions")
        now = utcnow()
        current = await subs.find_one(
            {"ndcId": ndcId, "creatorUid": creatorUid, "fanUid": uid}
        )
        base = max(now, current["expiresAt"]) if current else now
        await subs.update_one(
            {"ndcId": ndcId, "creatorUid": creatorUid, "fanUid": uid},
            {
                "$set": {
                    "expiresAt": base + PERIOD,
                    "isAutoRenew": auto_renew,
                    "lastRenewedAt": now,
                },
                "$setOnInsert": {"activeFrom": now},
            },
            upsert=True,
        )
        await _sync_profile(db, ndcId, creatorUid)
        return Base.Answer(
            {"fanClubList": [await _fan_club_json(db, ndcId, uid, creatorUid)]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.post("/x{ndcId}/s/influencer/{creatorUid}/config")
@validauth_required
async def subscription_config(request: Request, ndcId: int, creatorUid: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        auto_renew = bool((await request.json())["paymentContext"]["isAutoRenew"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await active_subscription(db, ndcId, creatorUid, uid):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        await db.get(table="FanSubscriptions").update_one(
            {"ndcId": ndcId, "creatorUid": creatorUid, "fanUid": uid},
            {"$set": {"isAutoRenew": auto_renew}},
        )
        return Base.Answer(
            {"fanClub": await _fan_club_json(db, ndcId, uid, creatorUid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@fan_clubs.delete("/x{ndcId}/s/influencer/{creatorUid}/subscribe")
@validauth_required
async def unsubscribe(request: Request, ndcId: int, creatorUid: str):
    """A paid month stays active until it expires; afterwards the record can be removed."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if await active_subscription(db, ndcId, creatorUid, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        await db.get(table="FanSubscriptions").delete_one(
            {"ndcId": ndcId, "creatorUid": creatorUid, "fanUid": uid}
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()
