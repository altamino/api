from datetime import UTC, datetime
from re import IGNORECASE as REGEX_IGNORECASE_FLAG
from re import escape as regex_escape
from re import match as re_match
from time import time as timestamp
from typing import Union
from uuid import uuid4
from time import time

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.database.models import Community, ModelFabric
from helpers.database.mongo import Database
from helpers.tipping_limiter import check_and_increment_tipping_limit
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.strikecheck import strike_check
from helpers.functions import calculate_page_tokens, parse_page_token
from helpers.routers.cachable import CachableRoute
from objects import Base, Blog, Errors, User, MediaList
from objects.types import BlogType, UserRole
from services.store import StoreService

blog_methods = APIRouter()
blog_methods.route_class = CachableRoute


def _wrap_wiki_for_blog_feed(item):
    item_id = item.get("itemId")
    if not item_id:
        return item

    ref_object = dict(item)
    wrapper = dict(item)
    wrapper.pop("itemId", None)
    wrapper.pop("label", None)
    wrapper["blogId"] = item_id
    wrapper["type"] = 1
    wrapper["refObjectId"] = item_id
    wrapper["refObjectType"] = 2
    wrapper["refObject"] = ref_object
    return wrapper


@blog_methods.get("/x{ndcId}/s/feed/blog-recommended")
async def get_recommended_blogs(request: Request, ndcId: int):
    # mock for now
    return Base.Answer({"blogList": []})


# fearured
@blog_methods.get("/x{ndcId}/s/feed/featured")
async def get_featured_blogs(
    request: Request,
    ndcId: int,
    pageToken: str | None = None,
    start: int = 0,
    size: int = 25,
):

    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")
    current_time = int(time() * 1000)
    query = {
        "$or": [
            {
                "featuredType": 1,
                "$expr": {
                    "$gt": [
                        {
                            "$add": [
                                "$featuredTime",
                                {"$multiply": ["$featuredDuration", 1000]},
                            ]
                        },
                        current_time,
                    ]
                },
            },
            {"featuredType": 2},
        ]
    }

    blogs = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("featuredTime", DESCENDING)
    ]

    blogList = [
        await Blog.Info(
            item, db, ndcId=ndcId, trigger_uid=request.state.session.get("uid")
        )
        for item in blogs
    ]

    featuredList = [
        {
            "ndcId": str(ndcId),
            "refObject": item,
            "refObjectId": item.get("id"),
            "refObjectType": item.get("blogType", 0),
        }
        for item in blogList
    ]

    db.close()

    return Base.Answer(
        {
            "featuredList": featuredList,
            "paging": calculate_page_tokens(start, size, blogList),
        },
        spent_time=timestamp() - t1,
    )


# podborka 2
@blog_methods.get("/x{ndcId}/s/feed/featured-more")
@blog_methods.get("/g/s/feed/featured-more")
async def get_featured_more(
    request: Request,
    ndcId: int = 0,
    pageToken: str | None = None,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")
    current_time = int(time() * 1000)
    query = {
        "$or": [
            {
                "featuredType": 1,
                "$expr": {
                    "$gt": [
                        {
                            "$add": [
                                "$featuredTime",
                                {"$multiply": ["$featuredDuration", 1000]},
                            ]
                        },
                        current_time,
                    ]
                },
            },
            {"featuredType": 2},
        ]
    }

    blogs = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    blogList = [
        await Blog.Info(
            item, db, ndcId=ndcId, trigger_uid=request.state.session.get("uid")
        )
        for item in blogs
    ]
    blogList = [_wrap_wiki_for_blog_feed(item) for item in blogList]

    db.close()
    return Base.Answer(
        {
            "blogList": blogList,
            "featuredBlogCategory": "featured",
            "paging": calculate_page_tokens(start, size, blogList),
        },
        spent_time=timestamp() - t1,
    )


@blog_methods.get("/x{ndcId}/s/feed/blog-all")
@blog_methods.get("/g/s/feed/blog-all")
async def get_latest_blog_posts(
    request: Request,
    ndcId: int = 0,
    pageToken: str | None = None,
    start: int = 0,
    size: int = 5,
    q: Union[str, None] = None,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    query = {}
    if q:
        query["title"] = {"$regex": regex_escape(q.strip()), "$options": "i"}

    blogs = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    blogList = [
        await Blog.Info(
            item, db, ndcId=ndcId, trigger_uid=request.state.session.get("uid")
        )
        for item in blogs
    ]
    blogList = [_wrap_wiki_for_blog_feed(item) for item in blogList]

    db.close()
    return Base.Answer(
        {
            "blogList": blogList,
            "paging": calculate_page_tokens(start, size, blogList),
        },
        spent_time=timestamp() - t1,
    )


@blog_methods.get("/g/s/blog")
@blog_methods.get("/x{ndcId}/s/blog")
@blog_methods.get("/x{ndcId}/s/item")
async def get_blogs(
    request: Request,
    q: Union[str, None] = None,
    uid: str | None = None,
    ndcId: int = 0,
    size: int = 25,
    pageToken: str | None = None,
    start: int = 0,
    type: str | None = None,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    is_wiki = request.url.path.endswith("/item")
    query = {}
    if is_wiki:
        query["blogType"] = 2

    if q or uid:
        raw_q = q.strip() if q else uid.strip()
        if type in ["user", "user-all"] and re_match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            raw_q,
            REGEX_IGNORECASE_FLAG,
        ):
            query["authorId"] = raw_q
        else:
            query["title"] = {"$regex": regex_escape(raw_q), "$options": "i"}

    blogs = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    blogList = [
        await Blog.Info(
            item, db, ndcId=ndcId, trigger_uid=request.state.session.get("uid")
        )
        for item in blogs
    ]
    if not is_wiki:
        blogList = [_wrap_wiki_for_blog_feed(item) for item in blogList]

    key_name = "itemList" if is_wiki else "blogList"

    db.close()
    return Base.Answer(
        {
            key_name: blogList,
            "paging": calculate_page_tokens(start, size, blogList),
        },
        spent_time=timestamp() - t1,
    )


@blog_methods.get("/g/s/announcement")
async def announcement(
    request: Request,
    start: int = 0,
    size: int = 25,
    language: str = "en",
    pageToken: str | None = None,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get("x0", "Blogs")

    blogs = [
        item
        async for item in table.find({"blogType": 0})
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    blogList = [
        await Blog.Info(item, db, ndcId=0, trigger_uid=request.state.session.get("uid"))
        for item in blogs
    ]

    db.close()
    return Base.Answer(
        {
            "blogList": blogList,
            "paging": calculate_page_tokens(start, size, blogList),
        },
        spent_time=timestamp() - t1,
    )


@blog_methods.get("/g/s/announcement/{blogId}")
async def get_announcement(
    request: Request,
    blogId: str,
):
    t1 = timestamp()

    db = await Database().init()
    table = db.get("x0", "Blogs")

    blog = await table.find_one({"id": blogId})
    if blog:
        blog_info = await Blog.Info(
            blog, db, ndcId=0, trigger_uid=request.state.session.get("uid")
        )
        db.close()

        return Base.Answer(
            {"blog": blog_info},
            spent_time=timestamp() - t1,
        )


@blog_methods.get("/g/s/blog/{blogId}")
@blog_methods.get("/x{ndcId}/s/blog/{blogId}")
@blog_methods.get("/x{ndcId}/s/item/{blogId}")
async def get_blog(
    request: Request,
    blogId: str,
    ndcId: int = 0,
):
    t1 = timestamp()

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    blog = await table.find_one({"id": blogId})
    if blog:
        blog_info = await Blog.Info(
            blog, db, ndcId=ndcId, trigger_uid=request.state.session.get("uid")
        )
        db.close()

        answ_key = "item" if blog["blogType"] == 2 else "blog"
        return Base.Answer(
            {answ_key: blog_info},
            spent_time=timestamp() - t1,
        )

    db.close()
    return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)


# edit blog post


@blog_methods.post("/g/s/blog/{blogId}")
@blog_methods.post("/x{ndcId}/s/blog/{blogId}")
@blog_methods.post("/x{ndcId}/s/item/{blogId}")
async def edit_blog(request: Request, blogId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    data = await request.json()

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    blog = await table.find_one({"id": blogId})
    if not blog:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

    if blog["authorId"] != trigger_uid:
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    preparedQueries = {"modifiedTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}

    if "title" in data:
        preparedQueries["title"] = data["title"]
    if "content" in data:
        preparedQueries["content"] = data["content"]
    if "mediaList" in data:
        preparedQueries["mediaList"] = data["mediaList"]

    extensions = data.get("extensions", {})
    if extensions:
        current_extensions = blog.get("extensions", {})
        style = extensions.get("style", {})
        if style:
            current_style = current_extensions.get("style", {})
            for k in [
                "backgroundMediaList",
                "backgroundColor",
                "coverMediaIndexList",
                "coverMediaList",
            ]:
                if k in style:
                    current_style[k] = style[k]
            current_extensions["style"] = current_style

        if "privilegeOfCommentOnPost" in extensions:
            current_extensions["commentAllowance"] = extensions[
                "privilegeOfCommentOnPost"
            ]

        if "props" in extensions:
            preparedQueries["props"] = [
                {
                    "title": item["title"],
                    "type": item["type"]
                    if item["type"]
                    in ["text", "levelStar", "date", "levelCost", "levelHeart"]
                    else "text",
                    "value": item["value"],
                }
                for item in extensions["props"]
            ]

        preparedQueries["extensions"] = current_extensions

    await table.update_one({"id": blogId}, {"$set": preparedQueries})
    updated_blog = await table.find_one({"id": blogId})
    blog_info = await Blog.Info(updated_blog, db, ndcId=ndcId, trigger_uid=trigger_uid)

    db.close()

    key = "item" if updated_blog["blogType"] == 2 else "blog"
    return Base.Answer({key: blog_info}, spent_time=timestamp() - t1)


# delete blog post


@blog_methods.delete("/g/s/blog/{blogId}")
@blog_methods.delete("/x{ndcId}/s/blog/{blogId}")
@blog_methods.delete("/x{ndcId}/s/item/{blogId}")
@blog_methods.post("/x{ndcId}/s/item/{blogId}/batch-delete")
async def delete_blog(request: Request, blogId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    blog = await table.find_one({"id": blogId})
    if not blog:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
    users = db.get(f"x{ndcId}", "Users")
    user = await users.find_one({"id": trigger_uid})
    if blog["authorId"] != trigger_uid and (
        not user or not UserRole.is_global_staff(user.get("role", 0))
    ):
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    await table.delete_one({"id": blogId})

    db.close()
    return Base.Answer({}, spent_time=timestamp() - t1)


# add vote to blog
@blog_methods.post("/g/s/blog/{blogId}/vote")
@blog_methods.post("/g/s/item/{blogId}/vote")
@blog_methods.post("/g/s/blog/{blogId}/g-vote")
@blog_methods.post("/x{ndcId}/s/blog/{blogId}/vote")
@blog_methods.post("/x{ndcId}/s/item/{blogId}/vote")
async def vote_blog(request: Request, blogId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    value = data.get("value", 4)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    # upvote
    if value in [1, 2, 3, 4]:
        await table.update_one(
            {"id": blogId},
            {
                "$addToSet": {"upvote": trigger_uid},
                "$pull": {"downvote": trigger_uid},
            },
        )
    # downvote
    elif value == -1:
        await table.update_one(
            {"id": blogId},
            {
                "$addToSet": {"downvote": trigger_uid},
                "$pull": {"upvote": trigger_uid},
            },
        )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# remove vote from blog


@blog_methods.delete("/g/s/blog/{blogId}/g-vote")
@blog_methods.delete("/g/s/blog/{blogId}/vote")
@blog_methods.delete("/g/s/item/{blogId}/vote")
@blog_methods.delete("/x{ndcId}/s/blog/{blogId}/vote")
@blog_methods.delete("/x{ndcId}/s/item/{blogId}/vote")
async def remove_vote_from_blog(request: Request, blogId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")

    await table.update_one(
        {"id": blogId}, {"$pull": {"upvote": trigger_uid, "downvote": trigger_uid}}
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# see who voted for blog
@blog_methods.get("/g/s/announcement/{blogId}/g-vote")
@blog_methods.get("/g/s/blog/{blogId}/g-vote")
@blog_methods.get("/g/s/blog/{blogId}/vote")
@blog_methods.get("/g/s/item/{blogId}/vote")
@blog_methods.get("/x{ndcId}/s/blog/{blogId}/vote")
@blog_methods.get("/x{ndcId}/s/item/{blogId}/vote")
async def get_blog_voters(
    request: Request,
    blogId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")
    blog = await table.find_one({"id": blogId})
    if blog is None:
        db.close()
        return Base.Answer({"userProfileList": []}, spent_time=timestamp() - t1)

    votes = blog.get("upvote", []) + blog.get("downvote", [])
    votes_selected = votes[start : start + size]

    xndc_users = db.get(f"x{ndcId}", "Users")
    trigger_uid = request.state.session.get("uid")

    voters_list = [
        User.GetUserInfo(u, ndcId=ndcId, triggerUserId=trigger_uid)
        for item in votes_selected
        if (u := await xndc_users.find_one({"id": item}))
    ]

    db.close()
    return Base.Answer({"userProfileList": voters_list}, spent_time=timestamp() - t1)


# post blog


@blog_methods.post("/g/s/blog")
@blog_methods.post("/x{ndcId}/s/blog")
@blog_methods.post("/x{ndcId}/s/item")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="post-blog")
@strike_check
async def post_blog(request: Request, ndcId: int = 0):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    data = await request.json()
    try:
        is_wiki = request.url.path.endswith("/item")
        blog_type = 2 if is_wiki else data["type"]
        title = data["label"] if is_wiki else data["title"]
        content = data["content"]
        extensions = data.get("extensions", {})
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if blog_type not in [
        BlogType.Basic,
        BlogType.Image,
        BlogType.Question,
        BlogType.Vote,
        BlogType.Wiki,
    ]:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if content is None and blog_type != BlogType.Image:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()

    if ndcId > 0:
        xndcid_users = db.get(f"x{ndcId}", "Users")
        user_in_community = await xndcid_users.find_one({"id": trigger_uid})
        if not user_in_community:
            db.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    else:
        users = db.get("x0", "Users")
        user = await users.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            db.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    style = extensions.get("style", {}) or {}
    useful_extensions = {
        "commentAllowance": extensions.get("privilegeOfCommentOnPost", 1),
        "style": {},
        "coverAnimation": extensions.get("coverAnimation", "none"),
    }
    for k in [
        "backgroundMediaList",
        "backgroundColor",
        "coverMediaIndexList",
        "coverMediaList",
    ]:
        useful_extensions["style"].update({k: style.get(k)})

    blogId = str(uuid4())
    blog_data = ModelFabric.Construct(
        Community.Blogs,
        id=blogId,
        authorId=trigger_uid,
        title=title,
        content=content,
        blogType=blog_type,
        mediaList=data.get("mediaList"),
        extensions=useful_extensions,
    )
    if "durationInDays" in data:
        blog_data["pollDuration"] = data["durationInDays"]
        blog_data["pollTimestamp"] = int(timestamp() * 1000)
    if "polloptList" in data:
        blog_data["pollOptions"] = [
            {
                "type": 0,
                "status": 0,
                "title": item["title"],
                "mediaList": MediaList.List(item.get("mediaList", [])),
                "voted": [],
            }
            for item in data["polloptList"]
        ]
    if "props" in extensions:
        blog_data["props"] = [
            {
                "title": item["title"],
                "type": item["type"]
                if item["type"]
                in ["text", "levelStar", "date", "levelCost", "levelHeart"]
                else "text",
                "value": item["value"],
            }
            for item in extensions["props"]
        ]
    table = db.get(f"x{ndcId}", "Blogs")
    await table.insert_one(blog_data)

    blog_info = await Blog.Info(blog_data, db, ndcId=ndcId, trigger_uid=trigger_uid)

    db.close()
    key = "item" if blog_type == 2 else "blog"
    return Base.Answer({key: blog_info}, spent_time=timestamp() - t1)


@blog_methods.post("/x{ndcId}/s/blog/{blogId}/tipping")
@blog_methods.post("/g/s/blog/{blogId}/tipping")
@turtlelimiter(limit=5, period=TurtleTime.minute, tag="tip")
async def tip_blog(request: Request, blogId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    try:
        data = await request.json()
        coins = float(data.get("coins", 0))
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if coins < 1 or coins > 500:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    is_blocked, _ = await check_and_increment_tipping_limit(trigger_uid)
    if is_blocked:
        return Errors.TooManyRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    users_table = db.get(table="Users")
    sender = await users_table.find_one({"id": trigger_uid})
    if sender is None:
        db.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    if sender.get("coins", 0.0) < coins:
        db.close()
        return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)

    blogs_table = db.get(f"x{ndcId}", "Blogs")
    blog = await blogs_table.find_one({"id": blogId})
    if blog is None:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    author_uid = blog.get("authorId")

    # Deduct from sender and credit author
    if author_uid:
        await users_table.update_one({"id": trigger_uid}, {"$inc": {"coins": -coins}})
        await users_table.update_one({"id": author_uid}, {"$inc": {"coins": coins}})
    else:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    # Update blog tipInfo leaderboard
    tip_info = blog.get("tipInfo", {})
    tippers_list = tip_info.get("tippersList", [])

    tipper_entry = next((t for t in tippers_list if t.get("uid") == trigger_uid), None)
    if tipper_entry:
        tipper_entry["totalTippedCoins"] = round(
            tipper_entry.get("totalTippedCoins", 0.0) + coins, 2
        )
    else:
        ndc_users = db.get(f"x{ndcId}", "Users")
        ndc_sender = await ndc_users.find_one({"id": trigger_uid}) or sender
        tipper_entry = {
            "uid": trigger_uid,
            "nickname": ndc_sender.get("nickname", ""),
            "icon": ndc_sender.get("icon"),
            "reputation": ndc_sender.get("reputation", 0),
            "totalTippedCoins": round(coins, 2),
        }
        tippers_list.append(tipper_entry)

    tippers_list.sort(key=lambda x: x.get("totalTippedCoins", 0.0), reverse=True)
    new_tipped_coins = round(tip_info.get("tippedCoins", 0.0) + coins, 2)

    updated_tip_info = {
        "tipMaxCoin": 500,
        "tippersCount": len(tippers_list),
        "tippable": True,
        "tipMinCoin": 1,
        "tippedCoins": new_tipped_coins,
        "tippersList": tippers_list,
    }

    await blogs_table.update_one(
        {"id": blogId}, {"$set": {"tipInfo": updated_tip_info}}
    )
    db.close()

    return Base.Answer({"tipInfo": updated_tip_info}, spent_time=timestamp() - t1)





@blog_methods.get("/g/s/item/{blogId}/tipping/tipped-users-summary")
@blog_methods.get("/x{ndcId}/s/item/{blogId}/tipping/tipped-users-summary")
@blog_methods.get("/g/s/blog/{blogId}/tipping/tipped-users-summary")
@blog_methods.get("/x{ndcId}/s/blog/{blogId}/tipping/tipped-users-summary")
@blog_methods.get("/g/s/item/{blogId}/tipping/tipped-users")
@blog_methods.get("/x{ndcId}/s/item/{blogId}/tipping/tipped-users")
@blog_methods.get("/g/s/blog/{blogId}/tipping/tipped-users")
@blog_methods.get("/x{ndcId}/s/blog/{blogId}/tipping/tipped-users")
async def get_blog_tiped_users_summary(
    request: Request,
    blogId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    connection = await Database().init()
    blog_table = connection.get(f"x{ndcId}", "Blogs")
    blog_info = await blog_table.find_one({"id": blogId})
    if blog_info is None:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    tip_info = blog_info.get("tipInfo", {})
    tippers_list = tip_info.get("tippersList", [])
    page = tippers_list[start:start + size]

    ndc_users = connection.get(f"x{ndcId}", "Users")
    g_table = connection.get(table="Users")

    tipped_user_list = []
    for entry in page:
        uid = entry.get("uid")
        row = await ndc_users.find_one({"id": uid})
        global_row = await g_table.find_one({"id": uid})
        if row is None or global_row is None:
            continue

        row["tagList"] = list(set(global_row.get("tagList", []) + row.get("tagList", [])))
        row["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)
        if "isTeamMember" in global_row:
            row["isTeamMember"] = global_row["isTeamMember"]
        if "isVerified" in global_row:
            row["isVerified"] = global_row["isVerified"]
        if global_row.get("status", 0) in [9, 10]:
            row["status"] = global_row["status"]

        async with await StoreService.create(uid, ndcId) as svc:
            row["iconFrame"] = await svc.frame_icon(row.get("frameId"))

        tipper_user = User.GetUserInfo(
            row,
            triggerUserId=trigger_uid,
            extensions=row.get("extensions"),
            ndcId=ndcId,
        )

        tipped_user_list.append({
            "tipper": tipper_user,
            "totalTippedCoins": entry.get("totalTippedCoins", 0.0),
            "lastTippedTime": entry.get("lastTippedTime"),
            "lastThankedTime": entry.get("lastThankedTime"),
            "isTipperAccessible": True,
        })

    connection.close()
    return Base.Answer({"tippedUserList": tipped_user_list}, spent_time=timestamp() - t1)





#idk todo (for pool blogs)
@blog_methods.get("/g/s/blog/{blogId}/poll/options-active-voterssummary")
@blog_methods.get("/x{ndcId}/s/blog/{blogId}/poll/options-active-voterssummary")
async def get_blog_poll_voters(
    request: Request,
    blogId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Blogs")
    blog = await table.find_one({"id": blogId})
    if blog is None:
        db.close()
        return Base.Answer({"userProfileList": []}, spent_time=timestamp() - t1)

    votes = blog.get("pollVoters", [])
    votes_selected = votes[start : start + size]

    xndc_users = db.get(f"x{ndcId}", "Users")
    trigger_uid = request.state.session.get("uid")

    voters_list = [
        User.GetUserInfo(u, ndcId=ndcId, triggerUserId=trigger_uid)
        for item in votes_selected
        if (u := await xndc_users.find_one({"id": item}))
    ]

    db.close()
    return Base.Answer({"userProfileList": voters_list}, spent_time=timestamp() - t1)

