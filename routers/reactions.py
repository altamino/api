"""Emoji / sticker reactions on chat messages and posts (port of the Kioraa contract).

API only: the AltAmino 3.4 APK has no reaction UI yet, so nothing is visible in the app until a
client consumes these routes. Up to three distinct reactions per person and target; POST adds,
PUT replaces the person's reactions, DELETE removes one by key. Responses carry the aggregated
reactionList with the reader's own selection.

This router must be included BEFORE routers.chats: chats has a catch-all
POST /chat/thread/{id}/message/{id}/{admin} that would otherwise receive .../reaction.
"""

from time import time as timestamp

from fastapi import APIRouter, Request

from helpers.routers.cachable import CachableRoute
from helpers.community_access import is_member, now_iso
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.validauth import validauth_required
from objects import Base, Errors

reactions = APIRouter()
reactions.route_class = CachableRoute
MAX_PER_USER = 3
KINDS = ("emoji", "sticker")


async def _summary(db, ndcId: int, target: str, viewer: str) -> list:
    out: dict[str, dict] = {}
    async for row in (
        db.get(f"x{ndcId}", "Reactions").find({"target": target}).sort("createdTime", 1)
    ):
        item = out.setdefault(
            row["key"],
            {
                "key": row["key"],
                "kind": row["kind"],
                "value": row["value"],
                "icon": row.get("icon"),
                "count": 0,
                "selected": False,
            },
        )
        item["count"] += 1
        item["selected"] = item["selected"] or row["uid"] == viewer
    return list(out.values())


async def message_summaries(
    db, ndcId: int, chatId: str, message_ids: list, viewer
) -> dict:
    """reactionSummary for a page of chat messages, keyed by messageId (one query per page)."""
    if not message_ids:
        return {}
    prefix = f"message:{chatId}:"
    out: dict[str, dict] = {}
    async for row in (
        db.get(f"x{ndcId}", "Reactions")
        .find({"target": {"$in": [prefix + m for m in message_ids]}})
        .sort("createdTime", 1)
    ):
        items = out.setdefault(row["target"][len(prefix) :], {})
        item = items.setdefault(
            row["key"],
            {
                "key": row["key"],
                "kind": row["kind"],
                "value": row["value"],
                "icon": row.get("icon"),
                "count": 0,
                "selected": False,
            },
        )
        item["count"] += 1
        item["selected"] = item["selected"] or row["uid"] == viewer
    return {m: list(v.values()) for m, v in out.items()}


async def _message_target(db, ndcId: int, chatId: str, messageId: str, uid: str):
    chat = await db.get(f"x{ndcId}", "Chats").find_one(
        {"id": chatId}, {"memberList": 1, "chatType": 1}
    )
    if not chat or uid not in (chat.get("memberList") or []):
        return None
    message = await db.get(f"x{ndcId}", f"_Chat:{chatId}").find_one(
        {"messageId": messageId}, {"messageType": 1}
    )
    if not message or message.get("messageType") == 100:
        return None
    return f"message:{chatId}:{messageId}"


async def _blog_target(db, ndcId: int, blogId: str, uid: str):
    blog = await db.get(f"x{ndcId}", "Blogs").find_one(
        {"id": blogId, "status": 0}, {"_id": 1}
    )
    if not blog or not await is_member(db, ndcId, uid):
        return None
    return f"blog:{blogId}"


async def _handle(
    request: Request,
    ndcId: int,
    resolve,
    result_key: dict,
    reaction_key: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        target = await resolve(db, uid)
        if target is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "Reactions")
        if request.method in ("POST", "PUT"):
            try:
                data = await request.json()
                kind, value = str(data["kind"]), str(data["value"])[:200]
            except Exception:
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            if kind not in KINDS or not value or (data.get("uid") not in (None, uid)):
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            key = f"{kind}:{value}"
            icon = None
            if kind == "sticker":
                # any published sticker (built-in or a pack's); reacting needs no ownership of the pack
                pack = await db.get(table="StickerCollections").find_one(
                    {"stickerList.stickerId": value, "status": 0}, {"stickerList.$": 1}
                )
                if not pack:
                    return Errors.InvalidRequest(
                        timestamp() - t1, lang=request.state.lang
                    )
                icon = pack["stickerList"][0].get("icon")
            mine = [
                r["key"]
                async for r in table.find({"target": target, "uid": uid}, {"key": 1})
            ]
            if request.method == "PUT":
                await table.delete_many(
                    {"target": target, "uid": uid, "key": {"$ne": key}}
                )
            elif key not in mine and len(mine) >= MAX_PER_USER:
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            await table.update_one(
                {"target": target, "uid": uid, "key": key},
                {
                    "$setOnInsert": {
                        "kind": kind,
                        "value": value,
                        "icon": icon,
                        "createdTime": now_iso(),
                    }
                },
                upsert=True,
            )
        elif request.method == "DELETE":
            await table.delete_one({"target": target, "uid": uid, "key": reaction_key})
        return Base.Answer(
            {**result_key, "reactionList": await _summary(db, ndcId, target, uid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@reactions.get("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}/reaction")
@reactions.post("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}/reaction")
@reactions.put("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}/reaction")
@turtlelimiter(limit=20, period=TurtleTime.minute, tag="reaction")
@validauth_required
async def message_reaction(request: Request, ndcId: int, chatId: str, messageId: str):
    return await _handle(
        request,
        ndcId,
        lambda db, uid: _message_target(db, ndcId, chatId, messageId, uid),
        {"messageId": messageId, "threadId": chatId},
    )


@reactions.delete(
    "/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}/reaction/{reactionKey}"
)
@validauth_required
async def delete_message_reaction(
    request: Request, ndcId: int, chatId: str, messageId: str, reactionKey: str
):
    return await _handle(
        request,
        ndcId,
        lambda db, uid: _message_target(db, ndcId, chatId, messageId, uid),
        {"messageId": messageId, "threadId": chatId},
        reactionKey,
    )


@reactions.get("/x{ndcId}/s/blog/{blogId}/reaction")
@reactions.post("/x{ndcId}/s/blog/{blogId}/reaction")
@reactions.put("/x{ndcId}/s/blog/{blogId}/reaction")
@turtlelimiter(limit=20, period=TurtleTime.minute, tag="reaction")
@validauth_required
async def blog_reaction(request: Request, ndcId: int, blogId: str):
    return await _handle(
        request,
        ndcId,
        lambda db, uid: _blog_target(db, ndcId, blogId, uid),
        {"blogId": blogId},
    )


@reactions.delete("/x{ndcId}/s/blog/{blogId}/reaction/{reactionKey}")
@validauth_required
async def delete_blog_reaction(
    request: Request, ndcId: int, blogId: str, reactionKey: str
):
    return await _handle(
        request,
        ndcId,
        lambda db, uid: _blog_target(db, ndcId, blogId, uid),
        {"blogId": blogId},
        reactionKey,
    )
