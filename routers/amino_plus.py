"""Amino+ paid with coins (MembershipFragment / product v2 in the 3.4 client; port of Kioraa amino-plus).

The account flag stays global Users.isPaidSubscriber (read everywhere for A+ badges and store
items). A coin subscription adds Users.aminoPlus {source: "coins", startedTime, expiresAt,
autoRenew, lastRenewedAt}; helpers.renewals renews it or switches the flag off when it ends.
Grants made by the team (isPaidSubscriber without a coin plan) are never touched. Real-money
payments (paymentType 5, Google Play) are not configured and are refused without charging.
"""

from time import time as timestamp

from fastapi import APIRouter, Request
from pymongo.errors import DuplicateKeyError

from helpers import coin_ledger
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.fan_access import utcnow
from helpers.renewals import (
    AMINO_PLUS_PRICE,
    PERIOD,
    renew_amino_plus,
    AMINO_PLUS_COIN_SALES_ENABLED,
)
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors

amino_plus = APIRouter()
amino_plus.route_class = CachableRoute

COIN_SKU = "altamino.amino.plus.coin.monthly"
COIN_PAYMENT = 1
_payments_indexed = False


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _product() -> dict:
    return {
        "title": f"Amino+ — {AMINO_PLUS_PRICE}",
        "description": "Amino+ / 1 month",
        "numberOfMonths": 1,
        "numberOfCoins": AMINO_PLUS_PRICE,
        "price": AMINO_PLUS_PRICE,
        "canAutoRenew": True,
        "savePercent": 0,
        "skuList": [COIN_SKU],
        "suggested": True,
        "badge": "",
        "icon": None,
    }


def _status(user: dict | None) -> dict:
    user = user or {}
    plan = user.get("aminoPlus") or {}
    membership = None
    if user.get("isPaidSubscriber"):
        coins = plan.get("source") == "coins"
        membership = {
            "membershipStatus": 1,
            "paymentType": COIN_PAYMENT if coins else 0,
            "isAutoRenew": bool(
                AMINO_PLUS_COIN_SALES_ENABLED and coins and plan.get("autoRenew")
            ),
            "isPremiumItemMembership": False,
            "createdTime": plan.get("startedTime") if coins else None,
        }
        if coins:
            membership["expiredTime"] = _iso(plan.get("expiresAt"))
    return {
        "accountMembershipEnabled": True,
        "hasAnyAppleSubscription": False,
        "hasAnyAndroidSubscription": False,
        "membership": membership,
        "premiumFeatureEnabled": True,
    }


def _coin_sales_unavailable(request: Request, started: float):
    messages = {
        "pt": "A compra de Amino+ por moedas está indisponível.",
        "en": "Amino+ purchases with coins are unavailable.",
        "es": "La compra de Amino+ con monedas no está disponible.",
    }
    return Errors.Custom(
        103,
        messages.get((request.state.lang or "en")[:2], messages["en"]),
        spent_time=timestamp() - started,
        lang=request.state.lang,
    )


def _payment_context(raw) -> dict:
    if isinstance(raw, str):
        import json

        raw = json.loads(raw) if len(raw) <= 2000 else None
    if not isinstance(raw, dict):
        raise ValueError("paymentContext")
    return raw


@amino_plus.get("/g/s/membership")
@amino_plus.get("/x{ndcId}/s/membership")
async def membership(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    if not uid:
        return Base.Answer(_status(None), spent_time=timestamp() - t1)
    db = await Database().init()
    try:
        user = await db.get(table="Users").find_one({"id": uid})
        if user:
            user = await renew_amino_plus(db, user)  # a due renewal shows up right away
        return Base.Answer(_status(user), spent_time=timestamp() - t1)
    finally:
        db.close()


@amino_plus.get("/g/s/membership/product/v2")
@amino_plus.get("/x{ndcId}/s/membership/product/v2")
@validauth_required
async def products(request: Request, ndcId: int = 0, paymentType: int = COIN_PAYMENT):
    t1 = timestamp()
    if int(paymentType) != COIN_PAYMENT:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    items = [_product()] if AMINO_PLUS_COIN_SALES_ENABLED else []
    return Base.Answer(
        {"productList": items, "allItemCount": len(items)}, spent_time=timestamp() - t1
    )


@amino_plus.post("/g/s/membership/product/subscribe")
@amino_plus.post("/x{ndcId}/s/membership/product/subscribe")
@validauth_required
async def subscribe(request: Request, ndcId: int = 0):
    global _payments_indexed
    t1 = timestamp()
    if not AMINO_PLUS_COIN_SALES_ENABLED:
        return _coin_sales_unavailable(request, t1)
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        if int(data.get("paymentType", COIN_PAYMENT)) != COIN_PAYMENT:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        sku = data.get("sku", data.get("productId"))
        if sku != COIN_SKU or data.get("uid") not in (None, uid):
            raise ValueError("sku")
        ctx = _payment_context(data.get("paymentContext"))
        transaction_id = str(ctx["transactionId"])[:100]
        auto_renew = ctx.get("isAutoRenew", True)
        if not transaction_id or not isinstance(auto_renew, bool):
            raise ValueError("paymentContext")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        users = db.get(table="Users")
        payments = db.get(table="AminoPlusPayments")
        if not _payments_indexed:
            await payments.create_index("transactionId", unique=True)
            _payments_indexed = True
        if await payments.find_one(
            {"transactionId": transaction_id, "uid": uid, "status": "paid"}
        ):
            return Base.Answer(
                _status(await users.find_one({"id": uid})), spent_time=timestamp() - t1
            )
        user = await users.find_one({"id": uid})
        if not user:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
        user = await renew_amino_plus(db, user)
        if user.get("isPaidSubscriber"):
            return Errors.InvalidRequest(
                timestamp() - t1, lang=request.state.lang
            )  # already a member
        try:
            await payments.insert_one(
                {
                    "transactionId": transaction_id,
                    "uid": uid,
                    "status": "pending",
                    "price": AMINO_PLUS_PRICE,
                    "createdTime": _iso(utcnow()),
                }
            )
        except DuplicateKeyError:
            return Base.Answer(
                _status(await users.find_one({"id": uid})), spent_time=timestamp() - t1
            )
        now = utcnow()
        charged = await users.update_one(
            {
                "id": uid,
                "coins": {"$gte": AMINO_PLUS_PRICE},
                "isPaidSubscriber": {"$ne": True},
            },
            {
                "$inc": {"coins": -AMINO_PLUS_PRICE},
                "$set": {
                    "isPaidSubscriber": True,
                    "aminoPlus": {
                        "source": "coins",
                        "startedTime": _iso(now),
                        "expiresAt": now + PERIOD,
                        "autoRenew": auto_renew,
                        "lastRenewedAt": now,
                    },
                },
            },
        )
        if not charged.modified_count:
            await payments.delete_one(
                {"transactionId": transaction_id, "status": "pending"}
            )
            return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)
        await payments.update_one(
            {"transactionId": transaction_id}, {"$set": {"status": "paid"}}
        )
        await coin_ledger.record(db, uid, -AMINO_PLUS_PRICE, "amino_plus_subscription")
        return Base.Answer(
            _status(await users.find_one({"id": uid})), spent_time=timestamp() - t1
        )
    finally:
        db.close()


@amino_plus.post("/g/s/membership/config")
@amino_plus.post("/x{ndcId}/s/membership/config")
@validauth_required
async def config(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        if int(data.get("paymentType", COIN_PAYMENT)) != COIN_PAYMENT:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        auto_renew = _payment_context(data.get("paymentContext"))["isAutoRenew"]
        if not isinstance(auto_renew, bool):
            raise ValueError("isAutoRenew")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if auto_renew and not AMINO_PLUS_COIN_SALES_ENABLED:
        return _coin_sales_unavailable(request, t1)
    db = await Database().init()
    try:
        users = db.get(table="Users")
        result = await users.update_one(
            {
                "id": uid,
                "isPaidSubscriber": True,
                "aminoPlus.source": "coins",
                "aminoPlus.expiresAt": {"$gt": utcnow()},
            },
            {"$set": {"aminoPlus.autoRenew": auto_renew}},
        )
        if not result.matched_count:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            _status(await users.find_one({"id": uid})), spent_time=timestamp() - t1
        )
    finally:
        db.close()


@amino_plus.get("/g/s/membership/latest-payment-context")
@amino_plus.get("/x{ndcId}/s/membership/latest-payment-context")
@validauth_required
async def latest_payment_context(request: Request, ndcId: int = 0):
    return Base.Answer({"paymentContext": None})


@amino_plus.post("/g/s/membership/product/pre-subscribe")
@amino_plus.post("/x{ndcId}/s/membership/product/pre-subscribe")
@validauth_required
async def pre_subscribe(request: Request, ndcId: int = 0):
    """Google Play billing is not configured: nothing is charged."""
    return Errors.InvalidRequest(0, lang=request.state.lang)
