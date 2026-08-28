from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.database.models import ModelFabric, CommentSchema
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.strikecheck import strike_check
from helpers.routers.cachable import CachableRoute
from objects import Base, Comments, Errors, User, MediaList

comments_router = APIRouter()
comments_router.route_class = CachableRoute


#
# HELPERS
#


async def _get_comment_list(
    db,
    comments_table,
    xndc_users,
    rootId: str,
    itemId: str,
    itemType: int,
    ndcId: int,
    trigger_uid: str | None,
    start: int,
    size: int,
    sort_order: int,
):
    query = {"rootId": rootId, "parentId": None}
    comments = [
        item
        async for item in comments_table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", sort_order)
    ]

    wc_list = []
    for comment in comments:
        count = await comments_table.count_documents({"parentId": comment["commentId"]})
        formatted = await Comments.Parent(
            comment,
            xndc_users,
            itemId,
            itemType=itemType,
            ndcId=ndcId,
            triggerUserId=trigger_uid,
            subcommentsCount=count,
        )
        formatted["subcommentsPreview"] = [
            await Comments.Son(
                subitem,
                xndc_users,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
            async for subitem in comments_table.find(
                query | {"parentId": comment["commentId"]}
            )
            .limit(1)
            .sort("createdTime", 1)
        ]
        wc_list.append(formatted)
    return wc_list


async def _post_comment(
    db,
    comments_table,
    users_table,
    rootId: str,
    itemId: str,
    itemType: int,
    ndcId: int,
    trigger_uid: str,
    data: dict,
    cumId: str | None,
):
    if cumId:
        # Edit comment
        comment = await comments_table.find_one({"commentId": cumId})
        if not comment or comment["authorId"] != trigger_uid:
            return None, Errors.NotEnoughRights(lang="en")  # Simplification for now

        await comments_table.update_one(
            {"commentId": cumId},
            {
                "$set": {
                    "content": data["content"],
                    "mediaList": MediaList.List(data.get("mediaList", [])),
                }
            },
        )
        updated_comment = await comments_table.find_one({"commentId": cumId})
        if updated_comment.get("parentId"):
            wmObj = await Comments.Son(
                updated_comment,
                users_table,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
        else:
            wmObj = await Comments.Parent(
                updated_comment,
                users_table,
                itemId,
                itemType=itemType,
                ndcId=ndcId,
                triggerUserId=trigger_uid,
            )
        return wmObj, None

    else:
        # New comment
        respond_to = data.get("respondTo")
        comment_id = str(uuid4())

        # Ensure proper parentId for nested replies
        parent_id = None
        if respond_to:
            parent_comment = await comments_table.find_one({"commentId": respond_to})
            if parent_comment:
                parent_id = parent_comment.get("parentId") or parent_comment.get(
                    "commentId"
                )

        if respond_to and parent_id is None:
            parent_id = respond_to
            # the logic is if there is respondTo, comment will be 100% a son
            # so either we use parentId from comment we answer to or we use that comment as parent

        new_comment = ModelFabric.Construct(
            CommentSchema,
            commentId=comment_id,
            rootId=rootId,
            parentId=parent_id,
            authorId=trigger_uid,
            content=data["content"],
            mediaList=MediaList.List(data.get("mediaList", [])),
        )
        await comments_table.insert_one(new_comment)
        if new_comment.get("parentId"):
            wmObj = await Comments.Son(
                new_comment,
                users_table,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
        else:
            wmObj = await Comments.Parent(
                new_comment,
                users_table,
                itemId,
                itemType=itemType,
                ndcId=ndcId,
                triggerUserId=trigger_uid,
            )
        return wmObj, None


async def _delete_comment(
    comments_table,
    commentId: str,
    trigger_uid: str,
    check_author_id: str,
):
    comment = await comments_table.find_one({"commentId": commentId})
    if not comment:
        return Errors.DataNotExist(lang="en")

    if comment["authorId"] != trigger_uid and check_author_id != trigger_uid:
        return Errors.NotEnoughRights(lang="en")

    # Delete the comment
    await comments_table.delete_one({"commentId": commentId})
    # Delete replies
    await comments_table.delete_many({"parentId": commentId})
    return None


async def _check_blog_author(db, ndcId: int, blogId: str):
    blogs_table = db.get(f"x{ndcId}", "Blogs")
    blog = await blogs_table.find_one({"id": blogId})
    return blog["authorId"] if blog else None


async def _vote_comment(
    comments_table,
    commentId: str,
    trigger_uid: str,
    value: int,
):
    comment = await comments_table.find_one({"commentId": commentId})
    if not comment:
        return Errors.DataNotExist(lang="en")

    if value == 1:
        await comments_table.update_one(
            {"commentId": commentId},
            {
                "$addToSet": {"upvotes": trigger_uid},
                "$pull": {"downvotes": trigger_uid},
            },
        )
    elif value == -1:
        await comments_table.update_one(
            {"commentId": commentId},
            {
                "$addToSet": {"downvotes": trigger_uid},
                "$pull": {"upvotes": trigger_uid},
            },
        )
    else:
        return Errors.InvalidRequest(lang="en")
    return None


async def _remove_comment_vote(
    comments_table,
    commentId: str,
    trigger_uid: str,
):
    await comments_table.update_one(
        {"commentId": commentId},
        {
            "$pull": {
                "upvotes": trigger_uid,
                "downvotes": trigger_uid,
            }
        },
    )
    return None


async def _get_comment_voters(
    comments_table,
    xndc_users,
    commentId: str,
    ndcId: int,
    trigger_uid: str | None,
    start: int,
    size: int,
):
    comment = await comments_table.find_one({"commentId": commentId})
    if comment is None:
        return {"userProfileList": []}

    votes = comment.get("upvotes", []) + comment.get("downvotes", [])
    votes_selected = votes[start : start + size]

    voters_list = [
        User.GetUserInfo(u, ndcId=ndcId, triggerUserId=trigger_uid)
        for item in votes_selected
        if (u := await xndc_users.find_one({"id": item}))
    ]
    return {"userProfileList": voters_list}


#
# BLOG METHODS
#

# get blog's wall


async def _get_comment_list(
    db,
    comments_table,
    xndc_users,
    rootId: str,
    itemId: str,
    itemType: int,
    ndcId: int,
    trigger_uid: str | None,
    start: int,
    size: int,
    sort_order: int,
):
    query = {"rootId": rootId, "parentId": None}
    comments = [
        item
        async for item in comments_table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", sort_order)
    ]

    wc_list = []
    for comment in comments:
        count = await comments_table.count_documents({"parentId": comment["commentId"]})
        formatted = await Comments.Parent(
            comment,
            xndc_users,
            itemId,
            itemType=itemType,
            ndcId=ndcId,
            triggerUserId=trigger_uid,
            subcommentsCount=count,
        )
        formatted["subcommentsPreview"] = [
            await Comments.Son(
                subitem,
                xndc_users,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
            async for subitem in comments_table.find(
                query | {"parentId": comment["commentId"]}
            )
            .limit(1)
            .sort("createdTime", 1)
        ]
        wc_list.append(formatted)
    return wc_list


@comments_router.get("/g/s/blog/{blogId}/g-comment")
@comments_router.get("/g/s/blog/{blogId}/comment")
@comments_router.get("/x{ndcId}/s/blog/{blogId}/comment")
async def get_blog_comments(
    request: Request,
    blogId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
    sort: str = "newest",
):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    xndc_users = db.get(f"x{ndcId}", "Users")

    wc_list = await _get_comment_list(
        db,
        comments_table,
        xndc_users,
        f"blog:{blogId}",
        blogId,
        2,
        ndcId,
        trigger_uid,
        start,
        size,
        DESCENDING if sort == "newest" else 1,
    )

    db.close()
    return Base.Answer({"commentList": wc_list}, spent_time=timestamp() - t1)


# get replies to blog's wall post


@comments_router.get("/g/s/blog/{blogId}/g-comment/{commentId}")
@comments_router.get("/g/s/blog/{blogId}/g-comment/{commentId}/response")
@comments_router.get("/g/s/blog/{blogId}/comment/{commentId}")
@comments_router.get("/g/s/blog/{blogId}/comment/{commentId}/response")
@comments_router.get("/g/s/item/{blogId}/g-comment/{commentId}")
@comments_router.get("/g/s/item/{blogId}/g-comment/{commentId}/response")
@comments_router.get("/g/s/item/{blogId}/comment/{commentId}")
@comments_router.get("/g/s/item/{blogId}/comment/{commentId}/response")
@comments_router.get("/x{ndcId}/s/blog/{blogId}/comment/{commentId}")
@comments_router.get("/x{ndcId}/s/blog/{blogId}/comment/{commentId}/response")
@comments_router.get("/x{ndcId}/s/item/{blogId}/comment/{commentId}")
@comments_router.get("/x{ndcId}/s/item/{blogId}/comment/{commentId}/response")
async def get_blog_comment_answers(
    request: Request,
    blogId: str,
    commentId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")

    comments = [
        item
        async for item in comments_table.find({"parentId": commentId})
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    xndc_users = db.get(f"x{ndcId}", "Users")

    wc_list = [
        await Comments.Son(
            item, xndc_users, itemId=blogId, triggerUserId=trigger_uid, ndcId=ndcId
        )
        for item in comments
    ]

    db.close()
    return Base.Answer({"commentList": wc_list}, spent_time=timestamp() - t1)


# post on blog's wall


async def _post_comment(
    db,
    comments_table,
    users_table,
    rootId: str,
    itemId: str,
    itemType: int,
    ndcId: int,
    trigger_uid: str,
    data: dict,
    cumId: str | None,
):
    if cumId:
        # Edit comment
        comment = await comments_table.find_one({"commentId": cumId})
        if not comment or comment["authorId"] != trigger_uid:
            return None, Errors.NotEnoughRights(lang="en")  # Simplification for now

        await comments_table.update_one(
            {"commentId": cumId},
            {
                "$set": {
                    "content": data["content"],
                    "mediaList": MediaList.List(data.get("mediaList", [])),
                }
            },
        )
        updated_comment = await comments_table.find_one({"commentId": cumId})
        if updated_comment.get("parentId"):
            wmObj = await Comments.Son(
                updated_comment,
                users_table,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
        else:
            wmObj = await Comments.Parent(
                updated_comment,
                users_table,
                itemId,
                itemType=itemType,
                ndcId=ndcId,
                triggerUserId=trigger_uid,
            )
        return wmObj, None

    else:
        # New comment
        respond_to = data.get("respondTo")
        comment_id = str(uuid4())

        # Ensure proper parentId for nested replies
        parent_id = None
        if respond_to:
            parent_comment = await comments_table.find_one({"commentId": respond_to})
            if parent_comment:
                parent_id = parent_comment.get("parentId") or parent_comment.get(
                    "commentId"
                )

        if respond_to and parent_id is None:
            parent_id = respond_to
            # the logic is if there is respondTo, comment will be 100% a son
            # so either we use parentId from comment we answer to or we use that comment as parent

        new_comment = ModelFabric.Construct(
            CommentSchema,
            commentId=comment_id,
            rootId=rootId,
            parentId=parent_id,
            authorId=trigger_uid,
            content=data["content"],
            mediaList=MediaList.List(data.get("mediaList", [])),
        )
        await comments_table.insert_one(new_comment)
        if new_comment.get("parentId"):
            wmObj = await Comments.Son(
                new_comment,
                users_table,
                itemId=itemId,
                itemType=itemType,
                triggerUserId=trigger_uid,
                ndcId=ndcId,
            )
        else:
            wmObj = await Comments.Parent(
                new_comment,
                users_table,
                itemId,
                itemType=itemType,
                ndcId=ndcId,
                triggerUserId=trigger_uid,
            )
        return wmObj, None


@comments_router.post("/g/s/blog/{blogId}/g-comment")
@comments_router.post("/g/s/blog/{blogId}/g-comment/{cumId}")
@comments_router.post("/g/s/item/{blogId}/g-comment")
@comments_router.post("/g/s/item/{blogId}/g-comment/{cumId}")
@comments_router.post("/g/s/blog/{blogId}/comment")
@comments_router.post("/g/s/blog/{blogId}/comment/{cumId}")
@comments_router.post("/g/s/item/{blogId}/comment")
@comments_router.post("/g/s/item/{blogId}/comment/{cumId}")
@comments_router.post("/x{ndcId}/s/blog/{blogId}/comment")
@comments_router.post("/x{ndcId}/s/blog/{blogId}/comment/{cumId}")
@comments_router.post("/x{ndcId}/s/item/{blogId}/comment")
@comments_router.post("/x{ndcId}/s/item/{blogId}/comment/{cumId}")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="blog-comment")
@strike_check
async def post_blog_comment(
    blogId: str,
    request: Request,
    ndcId: int = 0,
    cumId: str | None = None,  # to allow edit comments
):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    data = await request.json()
    try:
        if not data["content"]:
            raise Exception()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    users_table = db.get(f"x{ndcId}", "Users")

    wmObj, error = await _post_comment(
        db,
        comments_table,
        users_table,
        f"blog:{blogId}",
        blogId,
        2,
        ndcId,
        trigger_uid,
        data,
        cumId,
    )

    db.close()
    if error:
        return error
    return Base.Answer({"comment": wmObj}, spent_time=timestamp() - t1)


# delete comment from blog
@comments_router.delete("/g/s/blog/{blogId}/g-comment/{commentId}")
@comments_router.delete("/g/s/item/{blogId}/g-comment/{commentId}")
@comments_router.delete("/g/s/blog/{blogId}/comment/{commentId}")
@comments_router.delete("/g/s/item/{blogId}/comment/{commentId}")
@comments_router.delete("/x{ndcId}/s/blog/{blogId}/comment/{commentId}")
@comments_router.delete("/x{ndcId}/s/item/{blogId}/comment/{commentId}")
async def delete_blog_comment(
    request: Request, blogId: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    author_id = await _check_blog_author(db, ndcId, blogId)

    error = await _delete_comment(comments_table, commentId, trigger_uid, author_id)

    db.close()
    if error:
        return error
    return Base.Answer(spent_time=timestamp() - t1)


# vote for blog comment


@comments_router.post("/g/s/blog/{blogId}/g-comment/{commentId}/g-vote")
@comments_router.post("/g/s/item/{blogId}/g-comment/{commentId}/g-vote")
@comments_router.post("/g/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.post("/g/s/item/{blogId}/comment/{commentId}/vote")
@comments_router.post("/x{ndcId}/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.post("/x{ndcId}/s/item/{blogId}/comment/{commentId}/vote")
async def vote_blog_comment(
    request: Request, blogId: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    value = data.get("value", 0)
    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    error = await _vote_comment(comments_table, commentId, trigger_uid, value)
    db.close()
    if error:
        return error
    return Base.Answer(spent_time=timestamp() - t1)


@comments_router.delete("/g/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.delete("/g/s/blog/{blogId}/g-comment/{commentId}/g-vote")
@comments_router.delete("/g/s/item/{blogId}/g-comment/{commentId}/g-vote")
@comments_router.delete("/g/s/item/{blogId}/comment/{commentId}/vote")
@comments_router.delete("/x{ndcId}/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.delete("/x{ndcId}/s/item/{blogId}/comment/{commentId}/vote")
async def remove_blog_comment_vote(
    request: Request, blogId: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    await _remove_comment_vote(comments_table, commentId, trigger_uid)
    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# see who voted for blog comment


@comments_router.get("/g/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.get("/g/s/item/{blogId}/comment/{commentId}/vote")
@comments_router.get("/x{ndcId}/s/blog/{blogId}/comment/{commentId}/vote")
@comments_router.get("/x{ndcId}/s/item/{blogId}/comment/{commentId}/vote")
async def get_blog_comment_voters(
    request: Request,
    blogId: str,
    commentId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()
    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    xndc_users = db.get(f"x{ndcId}", "Users")
    trigger_uid = request.state.session.get("uid")
    voters = await _get_comment_voters(
        comments_table, xndc_users, commentId, ndcId, trigger_uid, start, size
    )
    db.close()
    return Base.Answer(voters, spent_time=timestamp() - t1)


#
# PROFILE METHODS
#

# get user's wall


@comments_router.get("/g/s/user-profile/{uid}/g-comment")
@comments_router.get("/x{ndcId}/s/user-profile/{uid}/comment")
async def get_user_wall_comments(
    request: Request,
    uid: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
    sort: str = "newest",
):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    xndc_users = db.get(f"x{ndcId}", "Users")

    wc_list = await _get_comment_list(
        db,
        comments_table,
        xndc_users,
        f"profile:{uid}",
        uid,
        0,
        ndcId,
        trigger_uid,
        start,
        size,
        DESCENDING if sort == "newest" else 1,
    )

    db.close()
    return Base.Answer({"commentList": wc_list}, spent_time=timestamp() - t1)


# get replies to user's wall post


@comments_router.get("/g/s/user-profile/{uid}/g-comment/{commentId}")
@comments_router.get("/g/s/user-profile/{uid}/g-comment/{commentId}/response")
@comments_router.get("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}")
@comments_router.get("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}/response")
async def get_user_wall_comment_answers(
    request: Request,
    uid: str,
    commentId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")

    comments = [
        item
        async for item in comments_table.find({"parentId": commentId})
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    xndc_users = db.get(f"x{ndcId}", "Users")

    wc_list = [
        await Comments.Son(
            item,
            xndc_users,
            itemId=uid,
            itemType=0,
            triggerUserId=trigger_uid,
            ndcId=ndcId,
        )
        for item in comments
    ]

    db.close()
    return Base.Answer({"commentList": wc_list}, spent_time=timestamp() - t1)


# post on user's wall


@comments_router.post("/g/s/user-profile/{uid}/g-comment")
@comments_router.post("/g/s/user-profile/{uid}/g-comment/{cumId}")
@comments_router.post("/g/s/user-profile/{uid}/comment")
@comments_router.post("/g/s/user-profile/{uid}/comment/{cumId}")
@comments_router.post("/x{ndcId}/s/user-profile/{uid}/comment")
@comments_router.post("/x{ndcId}/s/user-profile/{uid}/comment/{cumId}")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="profile-comment")
@strike_check
async def post_user_wall_comment(
    uid: str,
    request: Request,
    ndcId: int = 0,
    cumId: str | None = None,  # to allow edit comments
):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    data = await request.json()
    try:
        if not data["content"]:
            raise Exception()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    users_table = db.get(f"x{ndcId}", "Users")

    wmObj, error = await _post_comment(
        db,
        comments_table,
        users_table,
        f"profile:{uid}",
        uid,
        0,
        ndcId,
        trigger_uid,
        data,
        cumId,
    )

    db.close()
    if error:
        return error
    return Base.Answer({"comment": wmObj}, spent_time=timestamp() - t1)


# delete comment from user's wall
@comments_router.delete("/g/s/user-profile/{uid}/g-comment/{commentId}")
@comments_router.delete("/g/s/user-profile/{uid}/comment/{commentId}")
@comments_router.delete("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}")
async def delete_user_wall_comment(
    request: Request, uid: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")

    error = await _delete_comment(comments_table, commentId, trigger_uid, uid)

    db.close()
    if error:
        return error
    return Base.Answer(spent_time=timestamp() - t1)


# vote for user's wall comment


@comments_router.post("/g/s/user-profile/{uid}/g-comment/{commentId}/g-vote")
@comments_router.post("/g/s/user-profile/{uid}/comment/{commentId}/vote")
@comments_router.post("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}/vote")
async def vote_user_wall_comment(
    request: Request, uid: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    try:
        data = await request.json()
    except Exception:
        data = {}
    value = data.get("value", 0)

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    comment = await comments_table.find_one({"commentId": commentId})
    if not comment:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

    if value == 1:
        await comments_table.update_one(
            {"commentId": commentId},
            {
                "$addToSet": {"upvotes": trigger_uid},
                "$pull": {"downvotes": trigger_uid},
            },
        )
    elif value == -1:
        await comments_table.update_one(
            {"commentId": commentId},
            {
                "$addToSet": {"downvotes": trigger_uid},
                "$pull": {"upvotes": trigger_uid},
            },
        )
    else:
        db.close()
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# remove vote from user's wall comment


@comments_router.delete("/g/s/user-profile/{uid}/comment/{commentId}/vote")
@comments_router.delete("/g/s/user-profile/{uid}/g-comment/{commentId}/g-vote")
@comments_router.delete("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}/vote")
async def remove_user_wall_comment_vote(
    request: Request, uid: str, commentId: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")

    await comments_table.update_one(
        {"commentId": commentId},
        {
            "$pull": {
                "upvotes": trigger_uid,
                "downvotes": trigger_uid,
            }
        },
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# see who voted for user's wall comment


@comments_router.get("/g/s/user-profile/{uid}/comment/{commentId}/vote")
@comments_router.get("/x{ndcId}/s/user-profile/{uid}/comment/{commentId}/vote")
async def get_user_wall_comment_voters(
    request: Request,
    uid: str,
    commentId: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()

    db = await Database().init()
    comments_table = db.get(f"x{ndcId}", "Comments")
    comment = await comments_table.find_one({"commentId": commentId})
    if comment is None:
        db.close()
        return Base.Answer({"userProfileList": []}, spent_time=timestamp() - t1)

    votes = comment.get("upvotes", []) + comment.get("downvotes", [])
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
