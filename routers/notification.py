from time import time as timestamp
from pymongo import DESCENDING
from fastapi import APIRouter, Request

from helpers.database.mongo import Database
from helpers.functions import parse_page_token
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors, User
from objects.user import get_level


notification_methods = APIRouter()
notification_methods.route_class = CachableRoute




@notification_methods.get("/x{ndcId}/s/notification")
async def get_notifications(
    request: Request,
    ndcId: int,
    pagingType: str | None = None,
    pageToken: str | None = None,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Notifications")

    docs = [
        item
        async for item in table.find({"uid": trigger_uid})
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    author_table = db.get(f"x{ndcId}", "Users")
    g_table = db.get(table="Users")

    notification_list = []
    for doc in docs:
        author_uid = doc.get("authorUid")
        author_row = await author_table.find_one({"id": author_uid})

        author_profile = None
        if author_row:
            global_row = await g_table.find_one({"id": author_uid})
            if global_row:
                author_row["tagList"] = list(
                    set(global_row.get("tagList", []) + author_row.get("tagList", []))
                )
                author_row["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)
                if "isTeamMember" in global_row:
                    author_row["isTeamMember"] = global_row["isTeamMember"]
                if "isVerified" in global_row:
                    author_row["isVerified"] = global_row["isVerified"]
                if global_row.get("status", 0) in [9, 10]:
                    author_row["status"] = global_row["status"]

            author_profile = User.GetUserInfo(
                author_row,
                triggerUserId=trigger_uid,
                extensions=author_row.get("extensions"),
                ndcId=ndcId,
            )

        notification_list.append({
            "notificationId": doc.get("id"),
            "ndcId": ndcId,
            "type": doc.get("type"),
            "parentType": doc.get("parentType"),
            "parentId": doc.get("parentId"),
            "parentText": doc.get("parentText"),
            "objectId": doc.get("objectId"),
            "objectType": doc.get("objectType"),
            "objectSubtype": doc.get("objectSubtype"),
            "objectText": doc.get("objectText"),
            "contextText": doc.get("contextText"),
            "contextValue": doc.get("contextValue"),
            "contextNdcId": doc.get("contextNdcId"),
            "createdTime": doc.get("createdTime"),
            "author": author_profile,
        })

    db.close()
    return Base.Answer(
        {"notificationList": notification_list},
        spent_time=timestamp() - t1,
    )


@notification_methods.get("/x{ndcId}/s/notice")
async def get_notices(
    request: Request,
    ndcId: int,
    type: str | None = None,
    status: int | None = None,
    start: int = 0,
    size: int = 25,
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    size = size if 0 < size < 101 else 25

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Notices")
    users_table = db.get(f"x{ndcId}", "Users")

    query = {"targetUid": trigger_uid}
    if status is not None:
        query["status"] = status

    docs = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("createdTime", DESCENDING)
    ]

    notice_list = []
    for doc in docs:
        target_user = await users_table.find_one({"id": doc.get("targetUid")})
        operator = await users_table.find_one({"id": doc.get("operatorUid")})
        
        notice_list.append({
            "notificationId": doc.get("notificationId"),
            "noticeId": doc.get("id"),
            "ndcId": ndcId,
            "title": doc.get("title"),
            "targetUser": {
                "uid": target_user.get("id") if target_user else None,
                "nickname": target_user.get("nickname") if target_user else None,
                "level": get_level(target_user.get("reputation", 0)) if target_user else None,
                "reputation": target_user.get("reputation") if target_user else None,
            },
            "operator": {
                "uid": operator.get("id") if operator else None,
                "nickname": operator.get("nickname") if operator else None,
                "level": get_level(operator.get("reputation", 0)) if operator else None,
                "reputation": operator.get("reputation") if operator else None,
                "role": operator.get("role") if operator else None,
            },
        })

    db.close()
    return Base.Answer(
        {"noticeList": notice_list},
        spent_time=timestamp() - t1,
    )


@notification_methods.post("/x{ndcId}/s/notification/checked")
async def check_notifications(request: Request, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    table = db.get(f"x{ndcId}", "Notifications")

    await table.update_many(
        {"uid": trigger_uid, "read": {"$ne": True}},
        {"$set": {"read": True}},
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@notification_methods.delete("/x{ndcId}/s/notification/{notificationId}")
async def delete_notification(request: Request, ndcId: int, notificationId: str):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    table = db.get(f"x{ndcId}", "Notifications")

    result = await table.delete_one({"id": notificationId, "uid": trigger_uid})
    db.close()

    if result.deleted_count == 0:
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

    return Base.Answer(spent_time=timestamp() - t1)


@notification_methods.delete("/x{ndcId}/s/notification")
async def clear_notifications(request: Request, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    table = db.get(f"x{ndcId}", "Notifications")

    await table.delete_many({"uid": trigger_uid})
    db.close()

    return Base.Answer(spent_time=timestamp() - t1)