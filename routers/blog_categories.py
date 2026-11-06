"""Post (topic) categories: BlogCategoryListFragment, BlogCategoryPickerFragment and
ChangeCategoryFragment in the 3.4 client. Port of the Kioraa community-admin/content rules.

Categories live in x{ndc}/BlogCategories (status 0 visible, 9 hidden from members). A post keeps
its categories in Blogs.taggedBlogCategoryIdList (max 10). Leaders manage the list; the author or
staff choose the categories of a post. The list of posts per category stays in routers.blogs
(GET /blog-category/{id}/blog-list). The community module "topicCategories" only controls whether
the client shows the page; the API answers either way.

Included before routers.blogs so POST /blog/{blogId}/blog-category is never shadowed.
"""

from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request
from pymongo import ASCENDING

from helpers.community_access import is_member, now_iso, page, paging, staff_level
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors

blog_categories = APIRouter()
blog_categories.route_class = CachableRoute

MAX_PER_POST = 10
LEADER = 2


def _json(row: dict, ndcId: int, blogs_count: int) -> dict:
    return {
        "categoryId": row["categoryId"],
        "ndcId": ndcId,
        "label": row.get("label", ""),
        "content": row.get("content", ""),
        "icon": row.get("icon"),
        "type": row.get("type", 0),
        "style": 0,
        "status": row.get("status", 0),
        "position": row.get("position", 0),
        "blogsCount": blogs_count,
        "createdTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime"),
    }


async def _counted(db, ndcId: int, row: dict) -> dict:
    count = await db.get(f"x{ndcId}", "Blogs").count_documents(
        {"taggedBlogCategoryIdList": row["categoryId"], "status": 0}
    )
    return _json(row, ndcId, count)


async def valid_category_ids(db, ndcId: int, value) -> list[str] | None:
    """Validated taggedBlogCategoryIdList for a post; None when the input is not a list of ids.
    Unknown or hidden categories are dropped, order and uniqueness kept."""
    if not isinstance(value, list) or len(value) > MAX_PER_POST:
        return None
    wanted = []
    for item in value:
        if not isinstance(item, str):
            return None
        if item not in wanted:
            wanted.append(item)
    existing = {
        r["categoryId"]
        async for r in db.get(f"x{ndcId}", "BlogCategories").find(
            {"categoryId": {"$in": wanted}, "status": 0}, {"categoryId": 1}
        )
    }
    return [i for i in wanted if i in existing]


@blog_categories.get("/x{ndcId}/s/blog-category")
async def list_blog_categories(
    request: Request,
    ndcId: int,
    start: int = 0,
    size: int = 100,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        if not await db.get(table="Communities").find_one({"id": ndcId}, {"_id": 1}):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        query = (
            {"status": {"$in": [0, 9]}}
            if await staff_level(db, ndcId, uid)
            else {"status": 0}
        )
        rows = [
            await _counted(db, ndcId, r)
            async for r in db.get(f"x{ndcId}", "BlogCategories")
            .find(query)
            .sort([("position", ASCENDING), ("createdTime", ASCENDING)])
            .skip(start)
            .limit(size)
        ]
        return Base.Answer(
            {"blogCategoryList": rows, "paging": paging(start, size, rows)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


def _fields(data: dict) -> dict:
    out = {}
    label = data.get("label")
    if label is not None:
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 100:
            raise ValueError("label")
        out["label"] = label.strip()
    if data.get("content") is not None:
        if not isinstance(data["content"], str) or len(data["content"]) > 10000:
            raise ValueError("content")
        out["content"] = data["content"]
    if "icon" in data:
        icon = data["icon"]
        if icon is not None and (not isinstance(icon, str) or len(icon) > 1000):
            raise ValueError("icon")
        out["icon"] = icon or None
    if data.get("type") is not None:
        if data["type"] not in (0, 1):
            raise ValueError("type")
        out["type"] = data["type"]
    if data.get("status") is not None:
        if data["status"] not in (0, 9):
            raise ValueError("status")
        out["status"] = data["status"]
    return out


@blog_categories.post("/x{ndcId}/s/blog-category/position")
@validauth_required
async def reorder_blog_categories(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = (await request.json())["blogCategoryIdList"]
        if (
            not isinstance(ids, list)
            or len(set(map(str, ids))) != len(ids)
            or len(ids) > 500
        ):
            raise ValueError
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if await staff_level(db, ndcId, uid) < LEADER:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "BlogCategories")
        for position, category in enumerate(map(str, ids)):
            await table.update_one(
                {"categoryId": category},
                {"$set": {"position": position, "modifiedTime": now_iso()}},
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@blog_categories.post("/x{ndcId}/s/blog-category")
@blog_categories.post("/x{ndcId}/s/blog-category/{categoryId}")
@validauth_required
async def save_blog_category(
    request: Request, ndcId: int, categoryId: str | None = None
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        fields = _fields(await request.json())
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if await staff_level(db, ndcId, uid) < LEADER:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "BlogCategories")
        if categoryId:
            if fields:
                await table.update_one(
                    {"categoryId": categoryId},
                    {"$set": {**fields, "modifiedTime": now_iso()}},
                )
            row = await table.find_one({"categoryId": categoryId})
            if not row:
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        else:
            if "label" not in fields:
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            last = await table.find_one({}, sort=[("position", -1)])
            row = {
                "categoryId": str(uuid4()),
                "label": "",
                "content": "",
                "icon": None,
                "type": 0,
                "status": 0,
                "position": (last or {}).get("position", -1) + 1,
                "authorId": uid,
                "createdTime": now_iso(),
                "modifiedTime": now_iso(),
                **fields,
            }
            await table.insert_one(dict(row))
        return Base.Answer(
            {"blogCategory": await _counted(db, ndcId, row)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@blog_categories.delete("/x{ndcId}/s/blog-category/{categoryId}")
@validauth_required
async def delete_blog_category(request: Request, ndcId: int, categoryId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if await staff_level(db, ndcId, uid) < LEADER:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        result = await db.get(f"x{ndcId}", "BlogCategories").delete_one(
            {"categoryId": categoryId}
        )
        if result.deleted_count == 0:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        # Posts stay; only the tag goes away.
        await db.get(f"x{ndcId}", "Blogs").update_many(
            {"taggedBlogCategoryIdList": categoryId},
            {"$pull": {"taggedBlogCategoryIdList": categoryId}},
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@blog_categories.post("/x{ndcId}/s/blog/{blogId}/blog-category")
@validauth_required
async def set_post_categories(request: Request, ndcId: int, blogId: str):
    """ChangeCategoryFragment: the author or staff replace the categories of a post."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        ids = await valid_category_ids(db, ndcId, data.get("taggedBlogCategoryIdList"))
        if ids is None:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        blogs = db.get(f"x{ndcId}", "Blogs")
        blog = await blogs.find_one(
            {"id": blogId, "status": 0, "blogType": {"$ne": 2}}, {"authorId": 1}
        )
        if not blog:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if blog.get("authorId") != uid and not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        await blogs.update_one(
            {"id": blogId}, {"$set": {"taggedBlogCategoryIdList": ids}}
        )
        return Base.Answer(
            {"taggedBlogCategoryIdList": ids}, spent_time=timestamp() - t1
        )
    finally:
        db.close()
