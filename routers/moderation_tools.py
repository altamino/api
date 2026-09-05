from helpers.functions import (
    calculate_page_tokens,
    parse_page_token,
)
from helpers.i18n import i18n
from time import time as timestamp

from fastapi import APIRouter, Request

from helpers.database.mongo import Database
from helpers.database.models import ModelFabric, MH_Item
from helpers.decorators.validauth import validauth_required
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors, ModHistory, User, Blog, Chat
from objects.types import UserRole
from datetime import datetime
from uuid import uuid4

moderation_tools = APIRouter()
moderation_tools.route_class = CachableRoute


async def check_rights(
    db, uid: str, ndcId: int = 0, no_curators: bool = False, only_gods: bool = False
) -> (bool, int):
    table = db.get(f"x{ndcId}", table="Users")
    user = await table.find_one({"id": uid})
    if user is None:
        return False, 0

    role = user.get("role", 0)
    print(role)

    if no_curators and role == UserRole.Curator:
        return False, 0

    if only_gods:
        return UserRole.is_global_staff(role), 3

    modLevel_matrix = {
        100: 2,
        101: 1,
        102: 2,
        200: 3,
        201: 3,
        555: 3,
        254: 3,
    }
    return UserRole.is_privileged_role(user.get("role", 0)), modLevel_matrix.get(
        user.get("role", 0), 0
    )


# MODERATION HISTORY
# f"/x{self.comId}/s/admin/operation?objectId={userId}&objectType=0&pagingType=t&size={size}",
@moderation_tools.get("/g/s/admin/operation")
@moderation_tools.get("/x{ndcId}/s/admin/operation")
@validauth_required
async def moderation_history(
    request: Request,
    ndcId: int = 0,
    objectId: str = "",
    objectType: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session["uid"]

    db = await Database().init()
    can_do, modLevel = await check_rights(db, uid, ndcId, only_gods=(ndcId == 0))
    if not can_do:
        db.close()
        return Errors.NotEnoughRights(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    start = parse_page_token(pageToken, 0)
    size = size if 0 < size < 101 else 25

    table = db.get(f"x{ndcId}", "ModerationHistory")

    if objectId and objectType:
        query = {"objectId": objectId, "objectType": objectType}
    else:
        query = {}

    history = (
        await table.find(query)
        .sort("createdTime", -1)
        .skip(start)
        .limit(size)
        .to_list(length=size)
    )

    author_ids = list(set([h["authorId"] for h in history if "authorId" in h]))

    # Map: objectType -> set of objectIds
    objects_by_type = {}
    for h in history:
        ot = h["objectType"]
        oid = h["objectId"]
        if ot not in objects_by_type:
            objects_by_type[ot] = set()
        objects_by_type[ot].add(oid)

    # Bulk fetch users (authors and potentially moderated users)
    user_ids_to_fetch = set(author_ids)
    if 0 in objects_by_type:
        user_ids_to_fetch.update(objects_by_type[0])

    user_table = db.get(f"x{ndcId}", "Users")
    users = await user_table.find({"id": {"$in": list(user_ids_to_fetch)}}).to_list(
        length=None
    )
    user_map = {u["id"]: User.GetUserInfo(u, ndcId=ndcId) for u in users}

    object_maps = {}
    for ot, ids in objects_by_type.items():
        if ot == 0:
            object_maps[ot] = {uid: user_map.get(uid) for uid in ids}
            continue
        elif ot == 1:
            table_name = "Blogs"
        elif ot == 12:
            table_name = "Chats"
        else:
            continue

        table = db.get(f"x{ndcId}", table_name)
        objs = await table.find({"id": {"$in": list(ids)}}).to_list(length=None)

        processed_objs = {}
        for o in objs:
            if ot == 1:
                processed_objs[o["id"]] = await Blog.Info(o, db, ndcId=ndcId)
            elif ot == 12:
                processed_objs[o["id"]] = await Chat.Info(o, db, ndcId=ndcId)
        object_maps[ot] = processed_objs

    loc = "g" if ndcId == 0 else f"x{ndcId}"
    admin_log_list = []
    for h in history:
        author = user_map.get(h.get("authorId"))
        ot = h["objectType"]
        oid = h["objectId"]
        ot_linkmap = {
            0: "user-profile",
            1: "blog",
            12: "chat-thread",
        }
        internal_link = f"ndc://{loc}/{ot_linkmap[ot]}/{oid}"
        h["objectUrl"] = internal_link
        punished = object_maps.get(ot, {}).get(oid)
        admin_log_list.append(
            ModHistory.Item(ndcId, h, author, punished, lang=request.state.lang)
        )

    db.close()

    return Base.Answer(
        {
            "adminLogList": admin_log_list,
            "paging": calculate_page_tokens(start, size, admin_log_list),
        },
        spent_time=timestamp() - t1,
    )


@moderation_tools.post("/g/s/user-profile/{uid}/ban")
@moderation_tools.post("/x{ndcId}/s/user-profile/{uid}/ban")
@moderation_tools.post("/g/s/user-profile/{uid}/unban")
@moderation_tools.post("/x{ndcId}/s/user-profile/{uid}/unban")
@validauth_required
async def ban_user_toggle(request: Request, uid: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    try:
        data = await request.json()
        reason = data.get("note", {}).get("content", "")
    except Exception:
        reason = ""

    db = await Database().init()
    can_do, modLevel = await check_rights(
        db, request.state.session["uid"], ndcId, only_gods=(ndcId == 0)
    )
    if not can_do:
        db.close()
        return Errors.NotEnoughRights(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    is_unban = "unban" in request.url.path
    status = 0 if is_unban else 9

    table = db.get(f"x{ndcId}", "Users")
    await table.update_one({"id": uid}, {"$set": {"status": status}})

    history = db.get(f"x{ndcId}", "ModerationHistory")
    await history.insert_one(
        ModelFabric.Construct(
            MH_Item,
            operation=110,
            additionalValue=status,
            badgeColor="success" if status == 0 else "danger",
            reason=reason,
            modLevel=modLevel,
            objectId=uid,
            objectType=0,
            authorId=request.state.session["uid"],
        )
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@moderation_tools.post("/x{ndcId}/s/{object_type}/{object_id}/admin")
@moderation_tools.post("/x{ndcId}/s/chat/{object_type}/{object_id}/admin")
@moderation_tools.post("/g/s/{object_type}/{object_id}/admin")
@moderation_tools.post("/g/s/chat/{object_type}/{object_id}/admin")
@validauth_required
async def admin_action(
    request: Request, object_type: str, object_id: str, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    data = await request.json()
    db = await Database().init()
    can_do, modLevel = await check_rights(
        db, request.state.session["uid"], ndcId, only_gods=(ndcId == 0)
    )
    if not can_do:
        db.close()
        return Errors.NotEnoughRights(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    table_map = {
        "blog": ("Blogs", 1),
        "item": ("Blogs", 1),
        "thread": ("Chats", 12),
        "chat/thread": ("Chats", 12),
        "user-profile": ("Users", 0),
    }
    table_name, oT = table_map.get(object_type)
    if not table_name:
        db.close()
        return Errors.InvalidRequest()

    operation = data["adminOpName"]
    value = data.get("adminOpValue")
    reason = data.get("adminOpNote", {}).get("content", "")
    table = db.get(f"x{ndcId}", table_name)
    history = db.get(f"x{ndcId}", "ModerationHistory")

    print(f"Admin action: {object_type} ({table_name}) - {operation} - {value}")

    if table_name == "Users" and operation != 114:
        badgeColor = "default"
        if operation == 18:
            badgeColor = "danger"
            await table.update_one(
                {"id": object_id},
                {"$set": {"extensions.hideUserProfile": True}},
            )
        elif operation == 19:
            badgeColor = "success"
            await table.update_one(
                {"id": object_id},
                {"$set": {"extensions.hideUserProfile": False}},
            )
        elif operation == 207:
            if ndcId == 0:
                return Errors.InvalidRequest()
            titles = value.get("titles", []) if isinstance(value, dict) else []
            await table.update_one({"id": object_id}, {"$set": {"titles": titles}})
        else:
            db.close()
            return Errors.UnimplementedPath()

        await history.insert_one(
            ModelFabric.Construct(
                MH_Item,
                operation=operation,
                badgeColor=badgeColor,
                reason=reason,
                modLevel=modLevel,
                objectId=object_id,
                objectType=oT,
                authorId=request.state.session["uid"],
            )
        )

    else:
        if operation == 110:
            if value == 0:
                status = 0
            elif value == 9:
                status = 9
            else:
                db.close()
                return Errors.UnimplementedPath()

            await table.update_one({"id": object_id}, {"$set": {"status": status}})
            await history.insert_one(
                ModelFabric.Construct(
                    MH_Item,
                    operation=110,
                    additionalValue=status,
                    badgeColor="success" if status == 0 else "danger",
                    reason=reason,
                    modLevel=modLevel,
                    objectId=object_id,
                    objectType=oT,
                    authorId=request.state.session["uid"],
                )
            )
        elif operation == 114:
            featuredType = value.get("featuredType")
            featuredDuration = value.get("featuredDuration")
            await table.update_one(
                {"id": object_id},
                {
                    "$set": {
                        "featuredTime": int(timestamp() * 1000),
                        "featuredDuration": featuredDuration,
                        "featuredType": featuredType,
                        "featuredBy": request.state.session["uid"],
                    }
                },
            )
            await history.insert_one(
                ModelFabric.Construct(
                    MH_Item,
                    operation=operation,
                    badgeColor="success",
                    reason=reason,
                    modLevel=modLevel,
                    objectId=object_id,
                    objectType=oT,
                    authorId=request.state.session["uid"],
                )
            )
        else:
            db.close()
            return Errors.UnimplementedPath()

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@moderation_tools.post("/x{ndcId}/s/notice")
@moderation_tools.post("/g/s/notice")
@validauth_required
async def send_notice(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    data = await request.json()

    db = await Database().init()
    can_do, modLevel = await check_rights(db, uid, ndcId, only_gods=(ndcId == 0))
    if not can_do:
        db.close()
        return Errors.NotEnoughRights(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    try:
        target_uid = data["uid"]
        title = data["title"]
        content = data["content"]
        penalty_type = data.get("penaltyType", 0)  # 0 = warning, 1 = strike
        penalty_value = data.get("penaltyValue", 0)  # seconds for strike
        notice_type = data.get("noticeType", 7)  # 4 = strike, 7 = warning
        attached_object = data.get("attachedObject", {})
    except KeyError:
        db.close()
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    notice = {
        "id": str(uuid4()),
        "uid": target_uid,
        "triggerId": uid,
        "title": title,
        "content": content,
        "attachedObject": attached_object,
        "penaltyType": penalty_type,
        "penaltyValue": penalty_value,
        "noticeType": notice_type,
        "ndcId": ndcId,
        "createdTime": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    table = db.get(f"x{ndcId}", "Notices")
    await table.insert_one(notice)

    op = 267
    timeouts = [
        1 * 60 * 60,
        2 * 60 * 60,
        3 * 60 * 60,
        4 * 60 * 60,
        6 * 60 * 60,
        8 * 60 * 60,
        12 * 60 * 60,
        24 * 60 * 60,
        48 * 60 * 60,
        72 * 60 * 60,
    ]
    if penalty_type == 1 and penalty_value in timeouts:
        op = 205

        table = db.get(f"x{ndcId}", "Users")
        await table.update_one(
            {"id": target_uid},
            {"$set": {"timeout_until": int(timestamp()) + penalty_value}},
        )

    history = db.get(f"x{ndcId}", "ModerationHistory")
    await history.insert_one(
        ModelFabric.Construct(
            MH_Item,
            operation=op,
            badgeColor="warning",
            reason=content,
            modLevel=modLevel,
            objectId=target_uid,
            objectType=0,
            timeout=penalty_value,
            authorId=request.state.session["uid"],
        )
    )

    db.close()
    return Base.Answer({}, spent_time=timestamp() - t1)


@moderation_tools.get("/x{ndcId}/s/notice/message-template/{template_type}")
@moderation_tools.get("/g/s/notice/message-template/{template_type}")
async def get_notice_templates(request: Request, template_type: str, ndcId: int = 0):
    t1 = timestamp()

    if template_type not in ["strike", "warning"]:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    templates = i18n.get(f"mod.templates.{template_type}", lang=request.state.lang)

    return Base.Answer(
        {"messageTemplateList": templates},
        spent_time=timestamp() - t1,
    )
