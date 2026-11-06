"""Reports and the native review queue (FlagReportOptionDialog / FlagLogListFragment, APK 3.4).

Members report with POST /x{ndcId}/s/flag (global: POST /g/s/g-flag) using
{objectId, objectType, flagType, message, parentId, parentType, mediaList}. Only community
staff read the queue, the per-object logs and resolve them; acting on the reported item still
goes through the existing moderation tools.
"""

from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.routers.cachable import CachableRoute
from helpers.community_access import (
    is_member,
    now_iso,
    page,
    paging,
    profile,
    staff_level,
)
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.validauth import validauth_required
from objects import Base, Blog, Errors, MediaList

flag_center = APIRouter()
flag_center.route_class = CachableRoute

OBJECT_TYPES = {
    0,
    1,
    2,
    3,
    7,
    12,
    16,
    109,
}  # user, blog, wiki, comment, message, chat, community, shared file
FILTERS = {
    "bullying": {0, 109},
    "spam": {2},
    "off-topic": {4},
    "nappropriate-content": {1, 100, 101, 102, 106, 107, 108, 110},
    "art-theft": {3},
    "trolling": {5},
    "others": {200, 201},
}


async def _owner(
    db, ndcId: int, object_type: int, object_id: str, parent_id: str | None
):
    if object_type == 0:
        return object_id
    if object_type in (1, 2):
        row = await db.get(f"x{ndcId}", "Blogs").find_one(
            {"id": object_id}, {"authorId": 1}
        )
        return (row or {}).get("authorId")
    if object_type == 3:
        row = await db.get(f"x{ndcId}", "Comments").find_one(
            {"commentId": object_id}, {"authorId": 1}
        )
        return (row or {}).get("authorId")
    if object_type == 12:
        row = await db.get(f"x{ndcId}", "Chats").find_one(
            {"id": object_id}, {"hostId": 1}
        )
        return (row or {}).get("hostId")
    if object_type == 7 and parent_id:
        row = await db.get(f"x{ndcId}", f"_Chat:{parent_id}").find_one(
            {"messageId": object_id}, {"authorId": 1}
        )
        return (row or {}).get("authorId")
    if object_type == 109:
        row = await db.get(f"x{ndcId}", "SharedFiles").find_one(
            {"fileId": object_id}, {"authorId": 1}
        )
        return (row or {}).get("authorId")
    return None


@flag_center.post("/g/s/g-flag")
@flag_center.post("/x{ndcId}/s/flag")
@turtlelimiter(limit=10, period=TurtleTime.minute, tag="flag")
@validauth_required
async def submit_flag(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        object_id = str(data["objectId"])[:150]
        object_type = int(data.get("objectType", 0))
        flag_type = int(data.get("flagType", 200))
        message = str(data.get("message") or "")[:2000]
        parent_id = data.get("parentId")
        parent_type = data.get("parentType")
    except (KeyError, TypeError, ValueError):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if object_type not in OBJECT_TYPES or not object_id:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    media = []
    for item in (data.get("mediaList") or [])[:5]:
        try:
            media.append(MediaList.Item(item))
        except Exception:
            return Errors.InvalidMediaContent(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "Flags")
        # One open report per reporter and object: a repeat updates the reason, it does not
        # inflate the count shown to moderators.
        await table.update_one(
            {"objectId": object_id, "reporterUid": uid, "status": "pending"},
            {
                "$set": {
                    "objectType": object_type,
                    "flagType": flag_type,
                    "message": message,
                    "parentId": str(parent_id) if parent_id else None,
                    "parentType": parent_type,
                    "mediaList": media,
                    "modifiedTime": now_iso(),
                },
                "$setOnInsert": {
                    "flagId": str(uuid4()),
                    "ndcId": ndcId,
                    "createdTime": now_iso(),
                },
            },
            upsert=True,
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


async def _require_staff(db, ndcId: int, uid: str) -> bool:
    return await staff_level(db, ndcId, uid) > 0


@flag_center.get("/x{ndcId}/s/flag")
@flag_center.get("/g/s/flag")
@validauth_required
async def flag_queue(
    request: Request,
    ndcId: int = 0,
    status: str = "pending",
    type: str = "all",
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    if type != "all" and type not in FILTERS:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    states = ["pending"] if status == "pending" else ["resolved", "dismissed"]

    db = await Database().init()
    try:
        if not await _require_staff(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "Flags")
        groups: dict[str, list] = {}
        async for row in (
            table.find({"status": {"$in": states}})
            .sort([("createdTime", DESCENDING)])
            .limit(5000)
        ):
            groups.setdefault(row["objectId"], []).append(row)
        matched = [
            g
            for g in groups.values()
            if type == "all" or {r.get("flagType", 200) for r in g} & FILTERS[type]
        ]
        flag_list = []
        for g in matched[start : start + size]:
            newest, oldest = g[0], g[-1]
            object_type = newest.get("objectType", 0)
            owner = await _owner(
                db, ndcId, object_type, newest["objectId"], newest.get("parentId")
            )
            reviewed = next((r for r in g if r.get("reviewerUid")), None)
            codes = sorted({r.get("flagType", 200) for r in g})
            ref = None
            if object_type in (1, 2):
                blog = await db.get(f"x{ndcId}", "Blogs").find_one(
                    {"id": newest["objectId"]}
                )
                ref = (
                    await Blog.Info(blog, db, ndcId=ndcId, trigger_uid=uid)
                    if blog
                    else None
                )
            reporter = await profile(db, ndcId, newest.get("reporterUid"), uid)
            flag_list.append(
                {
                    "objectId": newest["objectId"],
                    "objectType": object_type,
                    "objectUid": owner,
                    "objectUser": await profile(db, ndcId, owner, uid),
                    "refObject": ref,
                    "reporterUid": newest.get("reporterUid"),
                    "reporter": reporter,
                    "reporterUser": reporter,
                    "operator": await profile(
                        db, ndcId, (reviewed or {}).get("reviewerUid"), uid
                    ),
                    "status": 1 if status == "pending" else 2,
                    "flaggedCount": len(g),
                    "totalFlaggedCount": len(g),
                    "flaggedTypes": codes,
                    "totalFlaggedTypes": codes,
                    "reasonType": newest.get("flagType", 200),
                    "reasonMessage": newest.get("message", ""),
                    "parentId": newest.get("parentId"),
                    "parentType": newest.get("parentType")
                    or (12 if object_type == 7 else 0),
                    "extensions": {},
                    "screenshotMediaList": newest.get("mediaList") or [],
                    "createdTime": oldest.get("createdTime"),
                    "modifiedTime": newest.get("modifiedTime")
                    or newest.get("createdTime"),
                    "lastResolvedTime": (reviewed or {}).get("reviewedTime"),
                }
            )
        return Base.Answer(
            {
                "flagList": flag_list,
                "allItemCount": len(matched),
                "paging": paging(start, size, flag_list),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@flag_center.get("/x{ndcId}/s/flag/target-object/{objectId}/flag-logs")
@validauth_required
async def flag_logs(
    request: Request,
    objectId: str,
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
        if not await _require_staff(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "Flags")
        total = await table.count_documents({"objectId": objectId})
        logs = []
        async for row in (
            table.find({"objectId": objectId})
            .sort([("createdTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ):
            logs.append(
                {
                    "objectId": objectId,
                    "flagType": row.get("flagType", 200),
                    "message": row.get("message", ""),
                    "createdTime": row.get("createdTime"),
                    "reporterUid": row.get("reporterUid"),
                    "reporter": await profile(db, ndcId, row.get("reporterUid"), uid),
                    "mediaList": row.get("mediaList") or [],
                }
            )
        return Base.Answer(
            {
                "flagLogList": logs,
                "allItemCount": total,
                "paging": paging(start, size, logs),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@flag_center.post("/x{ndcId}/s/flag/target-object/{objectId}/resolved")
@validauth_required
async def resolve_flags(request: Request, objectId: str, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    resolve_type = data.get("resolveType")
    note = str(data.get("resolveMessage") or "")[:2000]
    db = await Database().init()
    try:
        if not await _require_staff(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "Flags")
        result = await table.update_many(
            {"objectId": objectId, "status": "pending"},
            {
                "$set": {
                    "status": "dismissed" if resolve_type == 0 else "resolved",
                    "reviewerUid": uid,
                    "reviewReason": note,
                    "reviewedTime": now_iso(),
                }
            },
        )
        if result.matched_count == 0 and not await table.find_one(
            {"objectId": objectId}, {"_id": 1}
        ):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            {"objectId": objectId, "status": 2, "resolvedCount": result.modified_count},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()
