"""Saved posts (FeedHelper / BookmarkAdapter, APK 3.4).

POST /bookmark {objectType, objectId}; DELETE /bookmark/{objectId};
GET /bookmark -> bookmarkList [{refObjectId, refObjectType, refObject, bookmarkedTime}].
Private to the reader; a removed or no longer visible post is listed with refObject null.
"""

from time import time as timestamp

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.routers.cachable import CachableRoute
from helpers.community_access import is_member, now_iso, page, paging
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.fan_access import can_read_fan_content
from objects import Base, Blog, Errors

bookmarks = APIRouter()
bookmarks.route_class = CachableRoute
POST_TYPES = (1, 2)  # blog, wiki entry (both stored in Blogs)


async def _visible_post(db, ndcId: int, objectId: str, uid: str):
    blog = await db.get(f"x{ndcId}", "Blogs").find_one({"id": objectId})
    if not blog or blog.get("status", 0) != 0 or not await is_member(db, ndcId, uid):
        return None
    if (blog.get("extensions") or {}).get(
        "fansOnly"
    ) and not await can_read_fan_content(db, ndcId, blog.get("authorId"), uid):
        return None
    return blog


@bookmarks.post("/g/s/bookmark")
@bookmarks.post("/x{ndcId}/s/bookmark")
@validauth_required
async def add_bookmark(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        object_id = str(data["objectId"])
        object_type = int(data.get("objectType", 1))
        scope = int(data.get("ndcId", ndcId) or 0) if ndcId == 0 else ndcId
    except (KeyError, TypeError, ValueError):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if object_type not in POST_TYPES:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        if await _visible_post(db, scope, object_id, uid) is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        await db.get(table="Bookmarks").update_one(
            {"uid": uid, "ndcId": scope, "objectId": object_id},
            {"$setOnInsert": {"objectType": object_type, "bookmarkedTime": now_iso()}},
            upsert=True,
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@bookmarks.delete("/g/s/bookmark/{objectId}")
@bookmarks.delete("/x{ndcId}/s/bookmark/{objectId}")
@validauth_required
async def remove_bookmark(request: Request, objectId: str, ndcId: int = 0):
    t1 = timestamp()
    query = {"uid": request.state.session["uid"], "objectId": objectId}
    if ndcId:
        query["ndcId"] = ndcId
    db = await Database().init()
    try:
        # Removal works even after the original post was hidden or deleted.
        await db.get(table="Bookmarks").delete_many(query)
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@bookmarks.get("/g/s/bookmark")
@bookmarks.get("/x{ndcId}/s/bookmark")
@validauth_required
async def list_bookmarks(
    request: Request,
    ndcId: int = 0,
    start: int = 0,
    size: int = 20,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    query = {"uid": uid}
    if ndcId:
        query["ndcId"] = ndcId
    db = await Database().init()
    try:
        table = db.get(table="Bookmarks")
        total = await table.count_documents(query)
        rows = [
            r
            async for r in table.find(query)
            .sort([("bookmarkedTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = []
        for r in rows:
            blog = await _visible_post(db, r["ndcId"], r["objectId"], uid)
            ref = (
                await Blog.Info(blog, db, ndcId=r["ndcId"], trigger_uid=uid)
                if blog
                else None
            )
            items.append(
                {
                    "refObjectId": r["objectId"],
                    "refObjectType": r.get("objectType", 1),
                    "refObject": ref,
                    "bookmarkedTime": r.get("bookmarkedTime"),
                    "ndcId": r["ndcId"],
                }
            )
        return Base.Answer(
            {
                "bookmarkList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()
