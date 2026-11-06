"""Wiki catalog (CatalogFragment, CategoryPostActivity, CatalogSubmissionListFragment, APK 3.4).

Wikis stay in Blogs (blogType 2). Approval creates a distinct catalog copy, linked by
catalogSourceItemId, while the author's original publication stays untouched. Categories live
in x{ndc}/ItemCategories; the copy gets isCurated and its catalogCategoryIds, with order in
catalogPositions.{categoryId}. A member's own catalog (profile) is the virtual category whose id is
their uid and lists their ItemPins in pin order. Submissions are x{ndc}/KnowledgeBaseRequests
(status 1 pending, 2 approved, 3 rejected). Authorship never changes: a fork is a new wiki owned
by the reader that keeps originalItemId.
"""

from copy import deepcopy
from time import time as timestamp
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Request
from pymongo import ASCENDING, DESCENDING

from helpers.routers.cachable import CachableRoute
from helpers.community_access import (
    is_member,
    module_config,
    now_iso,
    page,
    paging,
    profile,
    staff_level,
)
from helpers.database.models import Community, ModelFabric
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from objects import Base, Blog, Errors, MediaList

catalog = APIRouter()
catalog.route_class = CachableRoute

ROOT_ID = "00000000-0000-0000-0000-000000000001"
ALL_ENTRIES_ID = "00000000-0000-0000-0000-000000000002"
# Root ("All Curated") = approved catalog entries; "All Entries" = every wiki of the community,
# except the gold catalog copies (their originals are already listed).
VIRTUAL_QUERIES = {
    ROOT_ID: {"isCurated": True},
    ALL_ENTRIES_ID: {"catalogSourceItemId": {"$exists": False}},
}
WIKI = 2
PREVIEW_SIZE = 10


def _category_json(
    row: dict, ndcId: int, items_count: int = 0, subs_count: int = 0
) -> dict:
    return {
        "categoryId": row["categoryId"],
        "ndcId": ndcId,
        "label": row.get("label", ""),
        "content": row.get("content", ""),
        "icon": row.get("icon"),
        "mediaList": row.get("mediaList") or [],
        "parentCategoryId": row.get("parentCategoryId") or ROOT_ID,
        "position": row.get("position", 0),
        "itemsCount": items_count,
        "subcategoriesCount": subs_count,
        "status": row.get("status", 0),
        "createdTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime"),
    }


def _virtual(
    category_id: str,
    label: str,
    ndcId: int,
    parent,
    items: int,
    subs: int,
    position: int,
) -> dict:
    return {
        "categoryId": category_id,
        "ndcId": ndcId,
        "label": label,
        "content": "",
        "icon": None,
        "mediaList": [],
        "parentCategoryId": parent,
        "position": position,
        "itemsCount": items,
        "subcategoriesCount": subs,
        "status": 0,
        "createdTime": "1970-01-01T00:00:00Z",
        "modifiedTime": "1970-01-01T00:00:00Z",
    }


async def _counted(db, ndcId: int, row: dict) -> dict:
    items = await db.get(f"x{ndcId}", "Blogs").count_documents(
        {"blogType": WIKI, "status": 0, "catalogCategoryIds": row["categoryId"]}
    )
    subs = await db.get(f"x{ndcId}", "ItemCategories").count_documents(
        {"parentCategoryId": row["categoryId"], "status": 0}
    )
    return _category_json(row, ndcId, items, subs)


async def _readable(db, ndcId: int, uid) -> bool:
    community = await db.get(table="Communities").find_one({"id": ndcId}, {"_id": 1})
    return community is not None


async def _items(
    db, ndcId: int, query: dict, start: int, size: int, uid, category: str | None = None
) -> list:
    order = [("createdTime", DESCENDING)]
    if category:
        order.insert(0, (f"catalogPositions.{category}", ASCENDING))
    rows = [
        r
        async for r in db.get(f"x{ndcId}", "Blogs")
        .find({"blogType": WIKI, "status": 0, **query})
        .sort(order)
        .skip(start)
        .limit(size)
    ]
    return [await Blog.Info(r, db, ndcId=ndcId, trigger_uid=uid) for r in rows]


async def _append(db, ndcId: int, category_ids: list, item_ids: list):
    """Put entries at the end of each category they are filed into (order kept per category)."""
    blogs = db.get(f"x{ndcId}", "Blogs")
    for category in category_ids:
        key = f"catalogPositions.{category}"
        last = await blogs.find_one(
            {key: {"$exists": True}}, {key: 1}, sort=[(key, DESCENDING)]
        )
        position = ((last or {}).get("catalogPositions") or {}).get(category, -1) + 1
        for item_id in item_ids:
            result = await blogs.update_one(
                {"id": item_id, key: {"$exists": False}}, {"$set": {key: position}}
            )
            position += result.modified_count


def _catalog_content_extensions(source: dict) -> dict:
    """Copy actual content metadata, excluding account, promotion and paid/social state."""
    value = source.get("extensions")
    if not isinstance(value, dict):
        return {}
    excluded = {
        "featuredType",
        "featuredTime",
        "featuredDuration",
        "promoteInfo",
        "tipInfo",
        "tippingInfo",
        "payments",
        "payment",
        "coins",
        "reward",
        "rewards",
        "fansOnly",
        "influencerFansOnly",
        "influencer",
        "membership",
        "membershipId",
        "votes",
        "votedValue",
        "votesCount",
        "commentsCount",
        "globalVotesCount",
        "globalVotedValue",
        "globalCommentsCount",
        "liked",
        "upvote",
        "downvote",
        "wall",
        "isCurated",
        "catalogCategoryIds",
        "catalogPositions",
    }
    return {key: deepcopy(item) for key, item in value.items() if key not in excluded}


async def _publish_catalog_copy(
    db,
    ndcId: int,
    copy_id: str,
    source_id: str,
    category_ids: list[str],
    *,
    allow_republish: bool = False,
):
    """Finish a reserved copy. A retry never republishes a copy explicitly removed afterward."""
    blogs = db.get(f"x{ndcId}", "Blogs")
    query = {"id": copy_id, "blogType": WIKI, "catalogSourceItemId": source_id}
    if not allow_republish:
        query["catalogPublicationPending"] = True
    result = await blogs.update_one(
        query,
        {
            "$set": {"isCurated": True, "status": 0},
            "$addToSet": {"catalogCategoryIds": {"$each": category_ids}},
            "$unset": {"catalogPublicationPending": ""},
        },
    )
    row = await blogs.find_one(
        {
            "id": copy_id,
            "blogType": WIKI,
            "catalogSourceItemId": source_id,
            "status": 0,
            "isCurated": True,
        }
    )
    if row is not None and (result.matched_count or allow_republish):
        await _append(db, ndcId, category_ids, [copy_id])
    return row


async def _catalog_copy(
    db,
    ndcId: int,
    source: dict,
    operator_uid: str,
    category_ids: list[str],
    *,
    request_id: str | None = None,
    publish: bool = True,
):
    """Idempotent persistent copy, also usable by an explicit, backed-up legacy data repair.

    The original is never updated here. A deterministic Mongo _id makes concurrent retries of
    the same request converge without introducing an index or copying publication history.
    """
    if not source or source.get("blogType") != WIKI or source.get("status", 0) != 0:
        return None
    if source.get("catalogSourceItemId"):
        return None  # callers organize existing copies separately, never recursively clone them
    source_id = source["id"]
    identity = f"altamino:catalog:x{ndcId}:{source_id}:" + (
        f"request:{request_id}" if request_id else "filing"
    )
    copy_id = str(uuid5(NAMESPACE_URL, identity))
    doc = ModelFabric.Construct(
        Community.Blogs,
        id=copy_id,
        authorId=source["authorId"],
        title=source.get("title") or source.get("label") or "",
        content=source.get("content"),
        blogType=WIKI,
        mediaList=deepcopy(source.get("mediaList") or []),
        extensions=_catalog_content_extensions(source),
        tags=deepcopy(source.get("tags") or []),
    )
    for key in (
        "icon",
        "keywords",
        "label",
        "address",
        "latitude",
        "longitude",
        "contributorUidList",
    ):
        if key in source:
            doc[key] = deepcopy(source[key])
    doc.update(
        {
            "_id": copy_id,
            "status": 9,
            "isCurated": False,
            "catalogSourceItemId": source_id,
            "catalogOperatorUid": operator_uid,
            "catalogPublicationPending": True,
            "createdTime": now_iso(),
            "modifiedTime": now_iso(),
        }
    )
    if request_id:
        doc["catalogApprovalRequestId"] = request_id
    blogs = db.get(f"x{ndcId}", "Blogs")
    await blogs.update_one({"_id": copy_id}, {"$setOnInsert": doc}, upsert=True)
    row = await blogs.find_one(
        {
            "_id": copy_id,
            "id": copy_id,
            "blogType": WIKI,
            "catalogSourceItemId": source_id,
        }
    )
    if row is None or (
        request_id and row.get("catalogApprovalRequestId") != request_id
    ):
        return None
    if not publish:
        return row
    return await _publish_catalog_copy(
        db, ndcId, copy_id, source_id, category_ids, allow_republish=request_id is None
    )


async def _catalog_for_filing(
    db, ndcId: int, source: dict, operator_uid: str, category_ids: list[str]
):
    """Staff organizes a copy or creates/reuses the source's separate community entry."""
    blogs = db.get(f"x{ndcId}", "Blogs")
    if source.get("catalogSourceItemId") or source.get("isCurated"):
        # Existing curated legacy entries are preserved; this operation is not a data migration.
        query = {"id": source["id"], "blogType": WIKI, "status": 0}
        update = await blogs.update_one(
            query, {"$addToSet": {"catalogCategoryIds": {"$each": category_ids}}}
        )
        if not update.matched_count:
            return None
        await _append(db, ndcId, category_ids, [source["id"]])
        return await blogs.find_one(query)
    existing = await blogs.find_one(
        {
            "catalogSourceItemId": source["id"],
            "blogType": WIKI,
            "status": 0,
            "isCurated": True,
        }
    )
    if existing:
        return await _catalog_for_filing(
            db, ndcId, existing, operator_uid, category_ids
        )
    return await _catalog_copy(db, ndcId, source, operator_uid, category_ids)


async def profile_item_rows(db, ndcId: int, owner: str) -> list[dict]:
    """A member's Wikis tab: their own wikis plus approved (gold) entries they saved, in the order
    they set (ItemPins.position), then the rest newest first."""
    pins = {
        r["itemId"]: r
        async for r in db.get(f"x{ndcId}", "ItemPins").find({"uid": owner})
    }
    rows = [
        r
        async for r in db.get(f"x{ndcId}", "Blogs")
        .find(
            {
                "blogType": WIKI,
                "status": 0,
                "$or": [
                    {"authorId": owner, "catalogSourceItemId": {"$exists": False}},
                    {"id": {"$in": list(pins)}, "isCurated": True},
                ],
            }
        )
        .limit(2000)
    ]
    rows.sort(key=lambda r: r.get("createdTime") or "", reverse=True)
    ordered = sorted(
        (r for r in rows if isinstance((pins.get(r["id"]) or {}).get("position"), int)),
        key=lambda r: pins[r["id"]]["position"],
    )
    return ordered + [r for r in rows if r not in ordered]


async def favorites_mapping(db, ndcId: int, viewer: str | None, item_ids: list) -> dict:
    """inMyFavoritesMapping / inMyFavorites: the entry is already on the viewer's Wikis tab."""
    if not viewer or not item_ids:
        return {}
    blogs = db.get(f"x{ndcId}", "Blogs")
    active = {
        r["id"]: r
        async for r in blogs.find(
            {"id": {"$in": item_ids}, "blogType": WIKI, "status": 0},
            {"id": 1, "authorId": 1, "isCurated": 1, "catalogSourceItemId": 1},
        )
    }
    mine = {
        item_id
        for item_id, row in active.items()
        if row.get("authorId") == viewer and not row.get("catalogSourceItemId")
    }
    pinned = {
        r["itemId"]
        async for r in db.get(f"x{ndcId}", "ItemPins").find(
            {"uid": viewer, "itemId": {"$in": item_ids}}, {"itemId": 1}
        )
    }
    return {
        i: 1
        for i in item_ids
        if i in mine or (i in pinned and active.get(i, {}).get("isCurated"))
    }


async def _user_root(db, ndcId: int, uid: str | None):
    """The member catalog shown on a profile: virtual category = their uid."""
    if not uid or not await db.get(f"x{ndcId}", "Users").find_one(
        {"id": uid}, {"_id": 1}
    ):
        return None
    return _virtual(
        uid,
        "User Catalog",
        ndcId,
        None,
        len(await profile_item_rows(db, ndcId, uid)),
        0,
        0,
    )


async def _pinned(db, ndcId: int, owner: str, start: int, size: int, viewer) -> list:
    rows = (await profile_item_rows(db, ndcId, owner))[start : start + size]
    return [await Blog.Info(r, db, ndcId=ndcId, trigger_uid=viewer) for r in rows]


@catalog.get("/x{ndcId}/s/item-category")
async def list_categories(
    request: Request, ndcId: int, type: str | None = None, q: str | None = None
):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _readable(db, ndcId, uid):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if type == "user":
            root = await _user_root(db, ndcId, q)
            if root is None:
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            return Base.Answer(
                {"itemCategoryList": [root]}, spent_time=timestamp() - t1
            )
        rows = [
            await _counted(db, ndcId, r)
            async for r in db.get(f"x{ndcId}", "ItemCategories")
            .find({"status": 0})
            .sort([("position", ASCENDING), ("createdTime", ASCENDING)])
        ]
        blogs = db.get(f"x{ndcId}", "Blogs")
        curated = await blogs.count_documents(
            {"blogType": WIKI, "status": 0, **VIRTUAL_QUERIES[ROOT_ID]}
        )
        everything = await blogs.count_documents(
            {"blogType": WIKI, "status": 0, **VIRTUAL_QUERIES[ALL_ENTRIES_ID]}
        )
        top = [r for r in rows if r["parentCategoryId"] == ROOT_ID]
        root = _virtual(ROOT_ID, "Catalog", ndcId, None, curated, len(top), 0)
        return Base.Answer(
            {
                "itemCategoryList": [root, *rows],
                "allEntriesItemCategory": _virtual(
                    ALL_ENTRIES_ID, "All Entries", ndcId, ROOT_ID, everything, 0, -1
                ),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/item-category/{categoryId}")
async def category_detail(
    request: Request,
    ndcId: int,
    categoryId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        cats = db.get(f"x{ndcId}", "ItemCategories")
        curated = {"isCurated": True}
        if categoryId == ROOT_ID:
            subs = [
                await _counted(db, ndcId, r)
                async for r in cats.find({"status": 0, "parentCategoryId": None}).sort(
                    "position", ASCENDING
                )
            ]
            total = await db.get(f"x{ndcId}", "Blogs").count_documents(
                {"blogType": WIKI, "status": 0, **curated}
            )
            category, items = (
                _virtual(ROOT_ID, "Catalog", ndcId, None, total, len(subs), 0),
                [],
            )
        elif categoryId == ALL_ENTRIES_ID:
            everything = VIRTUAL_QUERIES[ALL_ENTRIES_ID]
            items = await _items(db, ndcId, everything, start, size, uid)
            total = await db.get(f"x{ndcId}", "Blogs").count_documents(
                {"blogType": WIKI, "status": 0, **everything}
            )
            category, subs = (
                _virtual(ALL_ENTRIES_ID, "All Entries", ndcId, ROOT_ID, total, 0, -1),
                [],
            )
        else:
            row = await cats.find_one({"categoryId": categoryId, "status": 0})
            user_root = None if row else await _user_root(db, ndcId, categoryId)
            if user_root:
                category, subs = user_root, []
                items = await _pinned(db, ndcId, categoryId, start, size, uid)
            elif not row:
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            else:
                subs = [
                    await _counted(db, ndcId, r)
                    async for r in cats.find(
                        {"status": 0, "parentCategoryId": categoryId}
                    ).sort("position", ASCENDING)
                ]
                items = await _items(
                    db,
                    ndcId,
                    {"catalogCategoryIds": categoryId},
                    start,
                    size,
                    uid,
                    categoryId,
                )
                category = await _counted(db, ndcId, row)
        favorites = await favorites_mapping(
            db, ndcId, uid, [i.get("itemId") or i.get("blogId") for i in items]
        )
        return Base.Answer(
            {
                "itemCategory": category,
                "itemCategoryList": subs,
                "itemList": items,
                "childrenWrapper": {
                    "type": "itemCategory" if subs else "item",
                    "itemCategoryList": subs,
                    "itemList": items,
                    "inMyFavoritesMapping": favorites,
                },
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/item-category/{categoryId}/item-previews")
async def category_previews(request: Request, ndcId: int, categoryId: str):
    """CategoryPreviewResponse: the app asks for several categories at once (ids joined by commas)."""
    t1 = timestamp()
    uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        previews = {}
        for category in [c for c in categoryId.split(",") if c][:50]:
            virtual = category in VIRTUAL_QUERIES
            query = VIRTUAL_QUERIES.get(category) or {"catalogCategoryIds": category}
            previews[category] = await _items(
                db, ndcId, query, 0, PREVIEW_SIZE, uid, None if virtual else category
            )
        return Base.Answer({"itemPreviews": previews}, spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/item-category/{categoryId}/list")
async def category_items(
    request: Request,
    ndcId: int,
    categoryId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    curated = categoryId in VIRTUAL_QUERIES
    query = VIRTUAL_QUERIES.get(categoryId) or {"catalogCategoryIds": categoryId}
    db = await Database().init()
    try:
        if not curated and await _user_root(db, ndcId, categoryId):
            items = await _pinned(db, ndcId, categoryId, start, size, uid)
            total = len(await profile_item_rows(db, ndcId, categoryId))
        else:
            items = await _items(
                db, ndcId, query, start, size, uid, None if curated else categoryId
            )
            total = await db.get(f"x{ndcId}", "Blogs").count_documents(
                {"blogType": WIKI, "status": 0, **query}
            )
        return Base.Answer(
            {
                "itemList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


def _category_fields(data: dict) -> dict:
    out = {}
    label = data.get("label") or data.get("title")
    if isinstance(label, str) and label.strip():
        out["label"] = label.strip()[:100]
    if isinstance(data.get("content"), str):
        out["content"] = data["content"][:5000]
    if "icon" in data:
        out["icon"] = data["icon"] if isinstance(data["icon"], str) else None
    if isinstance(data.get("mediaList"), list):
        out["mediaList"] = [MediaList.Item(m) for m in data["mediaList"][:20]]
    return out


@catalog.post("/x{ndcId}/s/item-category")
@validauth_required
async def create_category(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        fields = _category_fields(data)
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if "label" not in fields:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    parent = data.get("parentCategoryId")
    parent = None if parent in (None, "", ROOT_ID) else str(parent)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        cats = db.get(f"x{ndcId}", "ItemCategories")
        if parent and not await cats.find_one(
            {"categoryId": parent, "status": 0}, {"_id": 1}
        ):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        last = await cats.find_one({"status": 0}, sort=[("position", DESCENDING)])
        row = {
            "categoryId": str(uuid4()),
            "parentCategoryId": parent,
            "authorId": uid,
            "label": "",
            "content": "",
            "icon": None,
            "mediaList": [],
            "position": (last or {}).get("position", -1) + 1,
            "status": 0,
            "createdTime": now_iso(),
            "modifiedTime": now_iso(),
            **fields,
        }
        await cats.insert_one(dict(row))
        return Base.Answer(
            {"itemCategory": await _counted(db, ndcId, row)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item-category/{categoryId}")
@validauth_required
async def edit_category(request: Request, ndcId: int, categoryId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        fields = _category_fields(await request.json())
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        cats = db.get(f"x{ndcId}", "ItemCategories")
        if fields:
            await cats.update_one(
                {"categoryId": categoryId, "status": 0},
                {"$set": {**fields, "modifiedTime": now_iso()}},
            )
        row = await cats.find_one({"categoryId": categoryId, "status": 0})
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            {"itemCategory": await _counted(db, ndcId, row)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.delete("/x{ndcId}/s/item-category/{categoryId}")
@validauth_required
async def delete_category(request: Request, ndcId: int, categoryId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        cats = db.get(f"x{ndcId}", "ItemCategories")
        # The category and its whole subtree are hidden; the wikis themselves are untouched.
        ids, frontier = [], [categoryId]
        while frontier:
            ids += frontier
            frontier = [
                r["categoryId"]
                async for r in cats.find(
                    {"parentCategoryId": {"$in": frontier}, "status": 0},
                    {"categoryId": 1},
                )
            ]
        result = await cats.update_many(
            {"categoryId": {"$in": ids}, "status": 0},
            {"$set": {"status": 9, "modifiedTime": now_iso()}},
        )
        if result.matched_count == 0:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        await db.get(f"x{ndcId}", "Blogs").update_many(
            {"catalogCategoryIds": {"$in": ids}},
            {"$pull": {"catalogCategoryIds": {"$in": ids}}},
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


def _removal_ids(data: dict, fallback=None) -> list[str]:
    """Validate native batch input without coercing objects or truncating a requested batch."""
    if not isinstance(data, dict):
        raise ValueError("Expected an object")
    values = (
        data.get("itemIdList")
        if "itemIdList" in data
        else [data.get("itemId", fallback)]
    )
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError("Expected one to 100 item ids")
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value != value.strip()
        for value in values
    ):
        raise ValueError("Invalid item id")
    if "sourceUid" in data and (
        not isinstance(data["sourceUid"], str) or not data["sourceUid"]
    ):
        raise ValueError("Invalid source uid")
    return list(dict.fromkeys(values))


async def _active_wikis_exist(db, ndcId: int, ids: list[str]) -> bool:
    found = {
        row["id"]
        async for row in db.get(f"x{ndcId}", "Blogs").find(
            {"id": {"$in": ids}, "blogType": WIKI, "status": 0}, {"id": 1}
        )
    }
    return found == set(ids)


async def _remove_catalog_approval(db, ndcId: int, ids: list[str]) -> bool:
    """Remove catalog membership only; publication and readers' saved preferences survive."""
    blogs = db.get(f"x{ndcId}", "Blogs")
    rows = [
        row
        async for row in blogs.find(
            {"id": {"$in": ids}, "blogType": WIKI, "status": 0},
            {"id": 1, "catalogSourceItemId": 1},
        )
    ]
    if {row["id"] for row in rows} != set(ids):
        return False
    matched = 0
    for row in rows:
        state = {"isCurated": False}
        if row.get("catalogSourceItemId"):
            state["status"] = (
                9  # archive the catalog copy; never archive its original publication
            )
        result = await blogs.update_one(
            {"id": row["id"], "blogType": WIKI, "status": 0},
            {
                "$set": state,
                "$unset": {
                    "catalogCategoryIds": "",
                    "catalogPositions": "",
                    "catalogPublicationPending": "",
                },
            },
        )
        matched += result.matched_count
    return matched == len(ids)


@catalog.post("/x{ndcId}/s/item/{itemId}/batch-delete")
@validauth_required
async def batch_delete_catalog_items(request: Request, ndcId: int, itemId: str):
    """Native catalog removal is either personal unpinning or staff decuration, never deletion."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        ids = _removal_ids(data, itemId)
        if (
            not isinstance(itemId, str)
            or not itemId
            or len(itemId) > 128
            or itemId not in ids
        ):
            raise ValueError("Batch anchor must be included")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    personal = "sourceUid" in data
    if personal and data["sourceUid"] != uid:
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if personal:
            if not await is_member(db, ndcId, uid):
                return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        elif not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if not await _active_wikis_exist(db, ndcId, ids):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if personal:
            # Removing an already absent pin is idempotent, as long as its actual wiki exists.
            await db.get(f"x{ndcId}", "ItemPins").delete_many(
                {"uid": uid, "itemId": {"$in": ids}}
            )
        elif not await _remove_catalog_approval(db, ndcId, ids):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item-category/{categoryId}/item-remove")
@validauth_required
async def remove_items_from_category(request: Request, ndcId: int, categoryId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        ids = _removal_ids(data)
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    personal = categoryId == uid or "sourceUid" in data
    if "sourceUid" in data and data["sourceUid"] != uid:
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if personal:
            if not await is_member(db, ndcId, uid):
                return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        elif not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if not await _active_wikis_exist(db, ndcId, ids):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if personal:
            # The owner takes saved entries off their Wikis tab; original wikis remain.
            await db.get(f"x{ndcId}", "ItemPins").delete_many(
                {"uid": uid, "itemId": {"$in": ids}}
            )
        elif categoryId in (ROOT_ID, ALL_ENTRIES_ID):
            if not await _remove_catalog_approval(db, ndcId, ids):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        else:
            if not await db.get(f"x{ndcId}", "ItemCategories").find_one(
                {"categoryId": categoryId, "status": 0}, {"categoryId": 1}
            ):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            result = await db.get(f"x{ndcId}", "Blogs").update_many(
                {"id": {"$in": ids}, "blogType": WIKI, "status": 0},
                {
                    "$pull": {"catalogCategoryIds": categoryId},
                    "$unset": {f"catalogPositions.{categoryId}": ""},
                },
            )
            if result.matched_count != len(ids):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item/{itemId}/tag")
@validauth_required
async def tag_item(request: Request, ndcId: int, itemId: str):
    """With categoryIdList: staff files entries into catalog categories. Without it: the reader
    pins the entry to their own favorites (profile)."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    to_profile = data.get("destinationUid") is not None
    if to_profile and data["destinationUid"] != uid:
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    # ItemHelper.addToCategory sends destinationUid = self: that is always "save to my Wikis tab",
    # never staff filing, even if the client also sends the profile root as a category.
    if (
        not to_profile
        and data.get("categoryIdList") is not None
        and not isinstance(data["categoryIdList"], list)
    ):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if data.get("itemIdList") is not None and not isinstance(data["itemIdList"], list):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    categories = (
        []
        if to_profile
        else [
            str(c)
            for c in (data.get("categoryIdList") or [])
            if c not in (ROOT_ID, ALL_ENTRIES_ID)
        ][:50]
    )
    item_ids = list(
        dict.fromkeys(str(i) for i in (data.get("itemIdList") or [itemId]))
    )[:100]
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        blogs = db.get(f"x{ndcId}", "Blogs")
        if categories:
            if not await staff_level(db, ndcId, uid):
                return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
            existing = [
                r["categoryId"]
                async for r in db.get(f"x{ndcId}", "ItemCategories").find(
                    {"categoryId": {"$in": categories}, "status": 0}, {"categoryId": 1}
                )
            ]
            if set(existing) != set(categories):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            sources = {
                r["id"]: r
                async for r in blogs.find(
                    {"id": {"$in": item_ids}, "blogType": WIKI, "status": 0}
                )
            }
            if not sources or set(sources) != set(item_ids):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            # Filing a member's wiki makes (or reuses) its gold catalog copy; filing a copy that is
            # already in the catalog only adds categories. Originals are never changed.
            for item_id in item_ids:
                if (
                    await _catalog_for_filing(
                        db, ndcId, sources[item_id], uid, existing
                    )
                    is None
                ):
                    return Errors.DataNotExist(
                        timestamp() - t1, lang=request.state.lang
                    )
        else:
            # Anyone may save approved (gold) entries to their Wikis tab; their own wikis are there already.
            pins = db.get(f"x{ndcId}", "ItemPins")
            saved = 0
            for item_id in item_ids:
                row = await blogs.find_one(
                    {"id": item_id, "blogType": WIKI, "status": 0},
                    {"authorId": 1, "isCurated": 1},
                )
                if not row or (row.get("authorId") != uid and not row.get("isCurated")):
                    continue
                await pins.update_one(
                    {"uid": uid, "itemId": item_id},
                    {"$setOnInsert": {"createdTime": now_iso()}},
                    upsert=True,
                )
                saved += 1
            if not saved:
                return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item/{itemId}/fork")
@validauth_required
async def fork_item(request: Request, ndcId: int, itemId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        community = await db.get(table="Communities").find_one(
            {"id": ndcId}, {"configuration": 1}
        )
        if module_config(community, "catalog").get("curationEnabled") is False:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        blogs = db.get(f"x{ndcId}", "Blogs")
        src = await blogs.find_one({"id": itemId, "blogType": WIKI, "status": 0})
        if not src:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if not src.get("isCurated"):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        doc = ModelFabric.Construct(
            Community.Blogs,
            id=str(uuid4()),
            authorId=uid,
            title=src.get("title"),
            content=src.get("content"),
            blogType=WIKI,
            mediaList=src.get("mediaList"),
            extensions=src.get("extensions") or {},
        )
        doc["originalItemId"] = itemId
        await blogs.insert_one(dict(doc))
        item = await Blog.Info(doc["id"], db, ndcId=ndcId, trigger_uid=uid)
        return Base.Answer(
            {
                "item": item,
                "inMyFavorites": 1,
                "isBookmarked": False,
                "taggedObjects": [],
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


def _id_list(data: dict, key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(key)
    out = []
    for i in value[:500]:
        if str(i) not in out:
            out.append(str(i))
    return out


@catalog.post("/x{ndcId}/s/item-category/{categoryId}/position")
@validauth_required
async def reorder_categories(request: Request, ndcId: int, categoryId: str):
    """CategoryOrganizeFragment: new order of the subcategories of categoryId (root = top level)."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = _id_list(await request.json(), "itemCategoryIdList")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    parent = None if categoryId == ROOT_ID else categoryId
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        cats = db.get(f"x{ndcId}", "ItemCategories")
        for position, category in enumerate(
            c for c in ids if c not in (ROOT_ID, ALL_ENTRIES_ID)
        ):
            await cats.update_one(
                {"categoryId": category, "parentCategoryId": parent, "status": 0},
                {"$set": {"position": position, "modifiedTime": now_iso()}},
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item-category/{categoryId}/item-position")
@validauth_required
async def reorder_category_items(request: Request, ndcId: int, categoryId: str):
    """ItemOrganizeFragment: new order of the entries inside one category."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = _id_list(await request.json(), "itemIdList")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if categoryId not in (ROOT_ID, ALL_ENTRIES_ID):
            blogs = db.get(f"x{ndcId}", "Blogs")
            for position, item_id in enumerate(ids):
                await blogs.update_one(
                    {"id": item_id, "catalogCategoryIds": categoryId},
                    {"$set": {f"catalogPositions.{categoryId}": position}},
                )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item-category/{categoryId}/item-move")
@validauth_required
async def move_category_items(request: Request, ndcId: int, categoryId: str):
    """CatalogFragment: move entries from this category to destinationCategoryId (end of its list)."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        ids = _id_list(data, "itemIdList")
        destination = str(data["destinationCategoryId"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if destination in (ROOT_ID, ALL_ENTRIES_ID, categoryId):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if not await db.get(f"x{ndcId}", "ItemCategories").find_one(
            {"categoryId": destination, "status": 0}, {"_id": 1}
        ):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        blogs = db.get(f"x{ndcId}", "Blogs")
        moved = [
            r["id"]
            async for r in blogs.find({"id": {"$in": ids}, "blogType": WIKI}, {"id": 1})
        ]
        if categoryId not in (ROOT_ID, ALL_ENTRIES_ID):
            await blogs.update_many(
                {"id": {"$in": moved}},
                {
                    "$pull": {"catalogCategoryIds": categoryId},
                    "$unset": {f"catalogPositions.{categoryId}": ""},
                },
            )
        await blogs.update_many(
            {"id": {"$in": moved}},
            {
                "$addToSet": {"catalogCategoryIds": destination},
                "$set": {"isCurated": True},
            },
        )
        await _append(db, ndcId, [destination], [i for i in ids if i in moved])
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item/reorder")
@validauth_required
async def reorder_my_items(request: Request, ndcId: int):
    """ItemOrganizeFragment on a profile: a member orders their own catalog (sourceUid = self).
    Registered before routers.blogs, whose POST /item/{blogId} would otherwise take this path."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        ids = _id_list(data, "itemIdList")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if data.get("sourceUid") not in (None, uid):
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        allowed = {r["id"] for r in await profile_item_rows(db, ndcId, uid)}
        pins = db.get(f"x{ndcId}", "ItemPins")
        for position, item_id in enumerate(i for i in ids if i in allowed):
            # own wikis get an order record too, so the whole tab follows the new order
            await pins.update_one(
                {"uid": uid, "itemId": item_id},
                {
                    "$set": {"position": position},
                    "$setOnInsert": {"createdTime": now_iso()},
                },
                upsert=True,
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/item/{itemId}/contributors")
async def item_contributors(request: Request, ndcId: int, itemId: str):
    """ItemDetailFragment: the author first (contributorType 1), then the credited contributors."""
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    db = await Database().init()
    try:
        item = await db.get(f"x{ndcId}", "Blogs").find_one(
            {"id": itemId, "blogType": WIKI, "status": 0}
        )
        if not item:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        people = []
        for kind, member in [(1, item.get("authorId"))] + [
            (0, u) for u in item.get("contributorUidList") or []
        ]:
            user = await profile(db, ndcId, member, viewer)
            if user and all(p.get("uid") != user.get("uid") for p in people):
                people.append(
                    {
                        **user,
                        "contributorType": kind,
                        "contributedTime": item.get("createdTime")
                        if kind
                        else item.get("modifiedTime"),
                    }
                )
        return Base.Answer({"contributorList": people}, spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/item/{itemId}/contributors")
@validauth_required
async def set_item_contributors(request: Request, ndcId: int, itemId: str):
    """ContributorSortFragment: the author (or staff) sets who is credited and in which order."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = _id_list(await request.json(), "contributorUidList")[:50]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        blogs = db.get(f"x{ndcId}", "Blogs")
        item = await blogs.find_one(
            {"id": itemId, "blogType": WIKI, "status": 0}, {"authorId": 1}
        )
        if not item:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if item.get("authorId") != uid and not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        members = {
            r["id"]
            async for r in db.get(f"x{ndcId}", "Users").find(
                {"id": {"$in": ids}}, {"id": 1}
            )
        }
        await blogs.update_one(
            {"id": itemId},
            {
                "$set": {
                    "contributorUidList": [
                        i for i in ids if i in members and i != item.get("authorId")
                    ]
                }
            },
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/item/{itemId}/tag-related")
async def item_tag_related(
    request: Request,
    ndcId: int,
    itemId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    """ "Favorite Related Pages". The 3.4 client reads these as abstract Feed objects that it can't
    build from plain items, so the list stays empty instead of answering 404."""
    t1 = timestamp()
    start, size = page(start, size, pageToken)
    return Base.Answer(
        {"tagRelatedObjects": [], "paging": paging(start, size, [])},
        spent_time=timestamp() - t1,
    )


async def _request_json(db, ndcId: int, row: dict, viewer) -> dict:
    item = await db.get(f"x{ndcId}", "Blogs").find_one({"id": row["itemId"]})
    return {
        "requestId": row["requestId"],
        "ndcId": ndcId,
        "itemId": row["itemId"],
        "destinationItemId": row.get("destinationItemId"),
        "message": row.get("message", ""),
        "responseMessage": row.get("responseMessage", ""),
        "status": row.get("status", 1),
        "uid": row["uid"],
        "createdTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime"),
        "item": await Blog.Info(item, db, ndcId=ndcId, trigger_uid=viewer)
        if item
        else None,
        "originalItem": None,
        "operator": await profile(db, ndcId, row.get("operatorUid"), viewer),
        "author": await profile(db, ndcId, row["uid"], viewer),
    }


@catalog.post("/x{ndcId}/s/knowledge-base-request")
@validauth_required
async def submit_to_catalog(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        item_id = str(data["itemId"])
        message = str(data.get("message") or "")[:2000]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        item = await db.get(f"x{ndcId}", "Blogs").find_one(
            {"id": item_id, "blogType": WIKI, "status": 0}
        )
        if not item:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if (
            item.get("authorId") != uid
            or item.get("catalogSourceItemId")
            or item.get("isCurated")
        ):
            # only the member's own original can be submitted; catalog entries are already there
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "KnowledgeBaseRequests")
        row = await table.find_one({"itemId": item_id, "status": 1})
        if row:  # one pending submission per entry; resubmitting updates the note
            await table.update_one(
                {"requestId": row["requestId"]},
                {"$set": {"message": message, "modifiedTime": now_iso()}},
            )
            row["message"] = message
        else:
            row = {
                "requestId": str(uuid4()),
                "itemId": item_id,
                "uid": uid,
                "message": message,
                "responseMessage": "",
                "status": 1,
                "createdTime": now_iso(),
                "modifiedTime": now_iso(),
            }
            await table.insert_one(dict(row))
        return Base.Answer(
            {"knowledgeBaseRequest": await _request_json(db, ndcId, row, uid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/knowledge-base-request")
@catalog.get("/x{ndcId}/s/knowledge-base-request/activities")
@validauth_required
async def list_requests(
    request: Request,
    ndcId: int,
    type: str = "pending",
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]
    start, size = page(start, size, pageToken)
    activities = request.url.path.endswith("/activities")
    db = await Database().init()
    try:
        staff = await staff_level(db, ndcId, uid)
        if activities:
            query = {"status": {"$in": [2, 3]}}
        elif type == "pending":
            query = {"status": 1}
        else:
            query = {}
        if not staff and not activities:
            query["uid"] = uid  # members only see their own submissions
        table = db.get(f"x{ndcId}", "KnowledgeBaseRequests")
        total = await table.count_documents(query)
        rows = [
            r
            async for r in table.find(query)
            .sort([("modifiedTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = [await _request_json(db, ndcId, r, uid) for r in rows]
        return Base.Answer(
            {
                "knowledgeBaseRequestList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.get("/x{ndcId}/s/knowledge-base-request/{requestId}")
@validauth_required
async def get_request(request: Request, ndcId: int, requestId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        row = await db.get(f"x{ndcId}", "KnowledgeBaseRequests").find_one(
            {"requestId": requestId}
        )
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if row["uid"] != uid and not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            {"knowledgeBaseRequest": await _request_json(db, ndcId, row, uid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@catalog.post("/x{ndcId}/s/knowledge-base-request/{requestId}/approve")
@catalog.post("/x{ndcId}/s/knowledge-base-request/{requestId}/reject")
@validauth_required
async def review_request(request: Request, ndcId: int, requestId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    approve = request.url.path.endswith("/approve")
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "KnowledgeBaseRequests")
        row = await table.find_one({"requestId": requestId, "status": 1})
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        update = {
            "status": 2 if approve else 3,
            "operatorUid": uid,
            "modifiedTime": now_iso(),
        }
        if approve:
            if data.get("destinationCategoryIdList") is not None and not isinstance(
                data["destinationCategoryIdList"], list
            ):
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
            wanted = [
                str(c)
                for c in (data.get("destinationCategoryIdList") or [])
                if c not in (ROOT_ID, ALL_ENTRIES_ID)
            ][:50]
            existing = [
                r["categoryId"]
                async for r in db.get(f"x{ndcId}", "ItemCategories").find(
                    {"categoryId": {"$in": wanted}, "status": 0}, {"categoryId": 1}
                )
            ]
            if set(existing) != set(wanted):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            blogs = db.get(f"x{ndcId}", "Blogs")
            active_item = {"id": row["itemId"], "blogType": WIKI, "status": 0}
            if not await blogs.find_one(active_item, {"id": 1}):
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            update["destinationCategoryIdList"] = existing
        else:
            update["responseMessage"] = str(
                data.get("responseMessage") or data.get("message") or ""
            )[:2000]
        transition = await table.update_one(
            {"requestId": requestId, "status": 1}, {"$set": update}
        )
        if transition.matched_count != 1:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if approve:
            # The author's wiki stays as it is (white); the catalog gets its own gold copy.
            source = await blogs.find_one(active_item)
            copy = await _catalog_copy(
                db, ndcId, source, uid, existing, request_id=requestId
            )
            if copy is None:
                # Separate collections are not atomic: if deletion won the race, restore only
                # this pending request's transition rather than report an approval with no wiki.
                restore = {"$set": {k: row[k] for k in update if k in row}}
                absent = {k: "" for k in update if k not in row}
                if absent:
                    restore["$unset"] = absent
                await table.update_one({"requestId": requestId, **update}, restore)
                return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
            await table.update_one(
                {"requestId": requestId}, {"$set": {"destinationItemId": copy["id"]}}
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()
