import asyncio
from base64 import b64decode
from random import choice
from re import escape as regex_escape
from string import ascii_letters, digits
from time import time as timestamp
from uuid import uuid4

from boto3 import resource
from fastapi import APIRouter, Request
from pymongo import DESCENDING

from helpers.database.redis import get as get_redis
from helpers.adminWS import send_ws_message as send_admin_ws
from helpers.adminWS import ApiBroadcastType
from helpers.config import Config
from helpers.database.models import Community, ModelFabric
from helpers.database.mongo import Database
from helpers.tipping_limiter import check_and_increment_tipping_limit
from helpers.decorators.bbnonsfw import bbnonsfw_manual_check
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.strikecheck import strike_check
from helpers.functions import (
    audio_length,
    calculate_page_tokens,
    detect_file_ext,
    is_app_link,
    is_hex_str,
    is_valid_uuid4,
    parse_page_token,
)
from helpers.imageTools import ImageTools
from helpers.processors.push import PushProcessor
from helpers.routers.cachable import CachableRoute
from objects import Base, Chat, Errors, Push, User
from objects.types import ChatType, UserRole, ChatAlertOptions
from objects.types.store import StoreItemType
from services.store import StoreService

from datetime import UTC, datetime

chats = APIRouter()
chats.route_class = CachableRoute


"""
#подборка
{
  "featuredChatThreadList": [ChatThread, ...],  # Закрепленные чаты
  "liveChatThreadList": [ChatThread, ...],      # Активные лайв-чаты
  "normalLiveCategoryList": [LiveCategory, ...]  # Обычные категории лайв
}



ChatThread:
{
  "threadId": str,
  "title": str,
  "memberCount": int,
  "type": int,  # 1 = SR (screen room), 2 = VV (voice), 4 = video, 8 = audio2
  "thumbnail": str,  # YouTube URL или preview
  "hasYoutube": bool,
  "youtubeUrl": str  # Если есть YouTube stream
}

LiveCategory:
{
  "categoryId": int,
  "name": str,
  "icon": str
}


"""


@chats.get("/x{ndcId}/s/live-layer/speed-dial-public")
async def get_live_layer_chats(
    request: Request,
    ndcId: int = 0,
    pageToken: str | None = None,
    start: int = 0,
    size: int = 5,
    v: int = 2,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)

    normalLiveCategoryList = []
    liveChatThreadList = []
    featuredChatThreadList = []

    db = await Database().init()
    db.get(f"x{ndcId}", "Chats")

    db.close()
    return Base.Answer(
        {
            "featuredChatThreadList": featuredChatThreadList,
            "liveChatThreadList": liveChatThreadList,
            "normalLiveCategoryList": normalLiveCategoryList,
        },
        spent_time=timestamp() - t1,
    )



async def _get_chatting_chat_ids(ndcId: int) -> list[str]:
    redis = get_redis()
    pattern = f"x{ndcId}:chat:*:chatting"
    chat_ids = []
    async for key in redis.scan_iter(pattern):
        if isinstance(key, bytes):
            key = key.decode()
        # key: x{ndcId}:chat:{chatId}:chatting
        parts = key.split(":")
        if len(parts) >= 4:
            chat_ids.append(parts[2])
    return chat_ids

@chats.get("/g/s/live-layer/public-chats")
@chats.get("/x{ndcId}/s/live-layer/public-chats")
async def live_layer_public_chats(
    request: Request,
    ndcId: int = 0,
    start: int = 0,
    size: int = 20,
):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    con = await Database().init()

    chat_ids = await _get_chatting_chat_ids(ndcId)
    page_ids = chat_ids[start : start + size]

    chats = [
        await Chat.Info(chatId, trigger_uid=trigger_uid, connection=con)
        for chatId in page_ids
    ]
    answer = {"threadList": [c for c in chats if c is not None]}
    con.close()
    return Base.Answer(answer, spent_time=timestamp() - t1)





# chat search
# /g/s/chat/thread/explore/search?q=Hello&size=25


@chats.get("/g/s/chat/thread/explore/search")
@chats.get("/x{ndcId}/s/chat/thread/explore/search")
async def user_search(
    request: Request,
    q: str = "",
    size: int = 25,
    pageToken: str | None = None,
    ndcId: int = 0,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25

    start = parse_page_token(pageToken, 0)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    query = {"chatType": 2, "title": {"$regex": regex_escape(q), "$options": "i"}}
    chats = [
        item
        async for item in table.find(query)
        .skip(start)
        .limit(size)
        .sort("timestamp", DESCENDING)
    ]
    threadList = [await Chat.Info(item["id"], db, ndcId=ndcId) for item in chats]
    if len(chats) > 0:
        answer = Base.Answer(
            {
                "threadListWrapper": {
                    "threadList": threadList,
                    "userInfoInThread": {
                        item["id"]: {"userProfileCount": 0, "userProfileList": []}
                        for item in chats
                    },
                    "paging": calculate_page_tokens(start, size, threadList),
                    "playlistInThreadList": {},
                },
                "communityInfoMapping": {},
            },
            spent_time=timestamp() - t1,
        )
        db.close()
        return answer
    else:
        db.close()
        return Base.Answer(
            {"messageList": [], "paging": {}}, spent_time=timestamp() - t1
        )



@chats.get("/g/s/chat/thread/explore/categories")
@chats.get("/x{ndcId}/s/chat/thread/explore/categories")  # ?need
async def get_explore_chats(
    request: Request,
    ndcId: int = 0,
    threadPreviewSize: int = 20,
    language: int = "en",
    start: int = 0,
    size: int = 4,
    pageToken: str | None = None,
):
    t1 = timestamp()

    request.state.session.get("uid")
    # con = await Database().init()
    answer = {"threadList": []}

    # con.close()
    return Base.Answer(answer, spent_time=timestamp() - t1)


@chats.get("/x{ndcId}/s/chat/thread/search")
@chats.get("/g/s/chat/thread/search")
async def chat_search(
    request: Request,
    ndcId: int = 0,
    q: str = "",
    action: int = 0,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()

    if pageToken:
        start = parse_page_token(pageToken, start)
    size = size if 0 < size < 101 else 25
    uid = request.state.session["uid"]

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Chats")
        query = {"memberList": uid}
        if q:
            query["title"] = {"$regex": regex_escape(q), "$options": "i"}

        threadCount = await table.count_documents(query)
        cursor = table.find(query).skip(start).limit(size)

        threadList = [
            await Chat.Info(item["id"], db, trigger_uid=uid, ndcId=ndcId)
            async for item in cursor
        ]
    finally:
        db.close()

    result = {
        "threadList": threadList,
        "communityInfoMapping": {},
        "threadCount": threadCount,
        "paging": calculate_page_tokens(start, size, threadList),
    }
    return Base.Answer(result, spent_time=timestamp() - t1)


# get chat info
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d


@chats.get("/g/s/chat/thread/{chatId}")
@chats.get("/x{ndcId}/s/chat/thread/{chatId}")
async def get_chat_info(chatId: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]

    return Base.Answer(
        {"thread": await Chat.Info(chatId, trigger_uid=trigger_uid, ndcId=ndcId)},
        spent_time=timestamp() - t1,
    )


# vvchat permission precheck
# [POST] /g/s/chat/thread/{chatId}/vvchat-permission
@chats.post("/g/s/chat/thread/{chatId}/vvchat-permission")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/vvchat-permission")
async def vvchat_permission(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]
    payload = await request.json()
    vv_chat_join_type = payload.get("vvChatJoinType", 1)
    if not isinstance(vv_chat_join_type, int):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    chat_info = await table.find_one({"id": chatId})
    if not chat_info:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

    # AltAmino client only needs a successful ack for this request.
    response = {
        "threadId": chatId,
        "ndcId": ndcId,
        "uid": trigger_uid,
        "vvChatJoinType": vv_chat_join_type,
    }
    db.close()
    return Base.Answer(response, spent_time=timestamp() - t1)


async def chat_apply_bubble(
    request, t1: float, ndcId: int, data: dict, trigger_uid: str
):

    bubble_id = data.get("bubbleId")
    chatId = data.get("threadId")
    apply_to_all = int(data.get("applyToAll", 0)) == 1

    if not chatId and not apply_to_all:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        if bubble_id:
            owned = db.get(table="UserStoreItems")
            ownership = await owned.find_one(
                {
                    "uid": trigger_uid,
                    "objectType": StoreItemType.ChatBubble,
                    "objectId": bubble_id,
                }
            )
            if not ownership:
                return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        else:
            bubble_id = "85045ed8-b05b-40de-907e-ec886889d086"  # defaultBubbleId

        table = db.get(f"x{ndcId}", "Users")
        user = await table.find_one({"id": trigger_uid})
        if user is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        if apply_to_all:
            await table.update_one(
                {"id": trigger_uid},
                {"$set": {"bubbleId": bubble_id, "chatBubbles": {}}},
            )
        else:
            await table.update_one(
                {"id": trigger_uid},
                {"$set": {f"chatBubbles.{chatId}": bubble_id}},
            )

        """
		await owned.update_one(
			{"_id": ownership["_id"]},
			{"$set": {"isActivated": True}},
		)
		"""
    finally:
        db.close()

    return Base.Answer(spent_time=timestamp() - t1)


# edit chat
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d


@chats.post("/g/s/chat/thread/{chatId}")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}")
async def edit_chat(chatId: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    data = await request.json()
    print(f"editing data for chat {chatId}:", data)
    trigger_uid = request.state.session["uid"]
    if chatId == "apply-bubble":
        return await chat_apply_bubble(request, t1, ndcId, data, trigger_uid)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    chat_info = await table.find_one({"id": chatId})

    if chat_info["hostId"] == trigger_uid or trigger_uid in chat_info.get(
        "cohostsIds", []
    ):
        ext = data.get("extensions", {})
        bg = ext.get("bm")
        if isinstance(bg, list):
            bg = bg[1]
        # TODO: verify image url

        update_chat = {}
        if data.get("content"):
            update_chat.update({"description": data["content"]})
        if data.get("title"):
            update_chat.update({"title": data["title"]})
        if data.get("icon"):
            update_chat.update({"icon": data["icon"]})
        if bg:
            update_chat.update({"background": bg})

        update_chat.update(
            {
                "pinAnnouncement": ext.get("pinAnnouncement", False),
                "announcement": ext.get("announcement"),
            }
        )

        print(update_chat)

        if len(update_chat) > 1:
            await table.update_one({"id": chatId}, {"$set": update_chat})

        answer = Base.Answer(
            {
                "thread": await Chat.Info(
                    chatId, trigger_uid=trigger_uid, connection=db, ndcId=ndcId
                )
            },
            spent_time=timestamp() - t1,
        )

        db.close()
        return answer

    else:
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)


# set background
# [POST] /api/v1/g/s/chat/thread/.../member/.../background
@chats.post("/g/s/chat/thread/{chatId}/member/{uid}/background")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/member/{uid}/background")
async def edit_background_chat(chatId: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    data = await request.json()
    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    chat_info = await table.find_one({"id": chatId})

    if chat_info["hostId"] == trigger_uid or trigger_uid in chat_info.get(
        "cohostsIds", []
    ):
        bg = None

        if len(data.get("media", [])) > 2:
            bg = data["media"][1]
            if not is_app_link(bg):
                return Errors.InvalidMediaContent()

        elif data.get("mediaUploadValue"):
            value = data["mediaUploadValue"]

            s3 = resource(
                service_name=Config.S3_SERVICE_NAME,
                aws_access_key_id=Config.S3_ACCESS_KEY,
                aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
                endpoint_url=Config.S3_ENDPOINT_URL,
            )
            image_bytes = b64decode(value)
            filetype = detect_file_ext(image_bytes[:128])
            if filetype is None:
                return Errors.InvalidMediaContent(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )
            filename = (
                Config.S3_IMAGES_FOLDER
                + "".join([choice(ascii_letters + digits) for _ in range(64)])
                + filetype
            )
            body = ImageTools.compress(b64decode(value), filetype[1:])
            s3.Bucket(Config.S3_BUCKET_NAME).put_object(Key=filename, Body=body)
            bg = Config.MEDIA_BASE_URL + filename

        if bg:
            await table.update_one({"id": chatId}, {"$set": {"background": bg}})

        answer = Base.Answer(
            {
                "thread": await Chat.Info(
                    chatId, trigger_uid=trigger_uid, connection=db, ndcId=ndcId
                )
            },
            spent_time=timestamp() - t1,
        )

        db.close()
        return answer

    return Errors.NotEnoughRights()


# delete chat
# [DELETE] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d


@chats.delete("/g/s/chat/thread/{chatId}")
@chats.delete("/x{ndcId}/s/chat/thread/{chatId}")
async def delete_chat(chatId: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    chat_info = await table.find_one({"id": chatId})
    sensitive_table = db.get(table="Users")
    user = await sensitive_table.find_one({"id": trigger_uid})
    if chat_info["hostId"] == trigger_uid or (
        user and UserRole.is_global_staff(user.get("role", 0))
    ):
        await table.delete_one({"id": chatId})
        db.close()
        return Base.Answer()
    else:
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)


# if chat exists + where user is


@chats.get("/g/s/chat/thread")
@chats.get("/x{ndcId}/s/chat/thread")
async def if_chat_exists(
    request: Request,
    type: str,
    q: str | None = None,
    size: int = 25,
    start: int = 0,
    ndcId: int = 0,
    stoptime: str | None = None,
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]
    if type == "exist-single" and q:
        db = await Database().init()
        table = db.get(f"x{ndcId}", "Chats")
        query = {
            "chatType": 0,
            "$or": [
                {"$and": [{"memberList": uid}, {"invitedList": q}]},
                {"$and": [{"memberList": q}, {"invitedList": uid}]},
                {"memberList": [q, uid]},
            ],
        }
        req = await table.find_one(query)
        if req is not None:
            r = Base.Answer(
                {
                    "threadList": [
                        await Chat.Info(req["id"], db, trigger_uid=uid, ndcId=ndcId)
                    ]
                }
            )

            db.close()
            return r
        else:
            return Errors.MythicData(timestamp() - t1, lang=request.state.lang)
    elif type == "exist-multi":
        return Base.Answer(
            {"threadList": [], "playlistInThreadList": {}}, spent_time=timestamp() - t1
        )
    elif type == "joined-me":
        size = size if 0 < size < 101 else 25

        db = await Database().init()
        table = db.get(f"x{ndcId}", "Chats")
        query = {"$or": [{"memberList": uid}, {"invitedList": uid}]}
        if stoptime:
            dt = datetime.strptime(stoptime, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            stop_ms = int(dt.timestamp() * 1000)
            query["lastMessageTimestamp"] = {"$lt": stop_ms}

        cursor = (
            table.find(query)
            .sort("lastMessageTimestamp", DESCENDING)
            .skip(start)
            .limit(size)
        )
        items = [
            await Chat.Info(item, db, trigger_uid=uid, ndcId=ndcId)
            async for item in cursor
        ]

        info = Base.Answer(
            {
                "threadList": items,
            },
            spent_time=timestamp() - t1,
        )

        db.close()
        return info
    elif type == "public-all":
        size = size if 0 < size < 101 else 25

        db = await Database().init()
        table = db.get(f"x{ndcId}", "Chats")
        items = [
            await Chat.Info(item, db, trigger_uid=uid, ndcId=ndcId)
            async for item in table.find({"chatType": 2})
            .skip(start)
            .limit(size)
            .sort("lastMessageTimestamp", DESCENDING)
        ]

        db.close()
        return Base.Answer(
            {"threadList": items},
            spent_time=timestamp() - t1,
        )
    elif type == "public-keyword":
        size = size if 0 < size < 101 else 25

        db = await Database().init()
        table = db.get(f"x{ndcId}", "Chats")
        query = {"chatType": 2, "title": {"$regex": regex_escape(q), "$options": "i"}}
        items = [
            await Chat.Info(item, db, trigger_uid=uid, ndcId=ndcId)
            async for item in table.find(query)
            .skip(start)
            .limit(size)
            .sort("timestamp", DESCENDING)
        ]

        db.close()
        return Base.Answer(
            {"threadList": items},
            spent_time=timestamp() - t1,
        )
    else:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)


# create chat
# /g/s/chat/thread


@chats.post("/g/s/chat/thread")
@chats.post("/x{ndcId}/s/chat/thread")
@turtlelimiter(limit=1, period=TurtleTime.minute, tag="create-chat")
@strike_check
async def create_chat(request: Request, ndcId: int = 0):
    t1 = timestamp()

    data = await request.json()
    trigger_uid = request.state.session["uid"]
    if data["type"] == ChatType.Private and (
        data.get("inviteeUids", []) == [] or len(data.get("inviteeUids", [])) != 1
    ):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if data["type"] == ChatType.PrivateGroup and data.get("inviteeUids", []) == []:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")

    if data["type"] == ChatType.Private:
        query = {
            "chatType": ChatType.Private,
            "$or": [
                {"memberList": {"$all": [trigger_uid] + data["inviteeUids"]}},
                {"invitedList": {"$all": [trigger_uid] + data["inviteeUids"]}},
            ],
        }
        req = await table.find_one(query)
    else:
        req = None

    if req is not None:
        chatId = req["id"]
        chatObj = req
    else:
        chatId = str(uuid4())
        if data["type"] == ChatType.Public:
            bm = data.get("extensions", {}).get("bm") or [None, None]
            bg = bm[1] if len(bm) > 1 else None
            chatObj = ModelFabric.Construct(
                Community.Chats,
                chatType=data["type"],
                id=chatId,
                hostId=trigger_uid,
                invitedList=data.get("inviteeUids", []),
                memberList=[trigger_uid],
                background=(
                    bg
                    if isinstance(bg, str)
                    else "https://media.altamino.top/default-chat-room-background/10_00.png"
                ),
                title=data.get("title", "Unnamed chat"),
                description=data.get("content", ""),
                icon=data.get("icon"),
            )
        else:
            chatObj = ModelFabric.Construct(
                Community.Chats,
                chatType=data["type"],
                id=chatId,
                hostId=trigger_uid,
                invitedList=data["inviteeUids"],
                memberList=[trigger_uid],
            )
    await table.insert_one(chatObj)

    lastMsgId = str(uuid4())
    messages = [
        ModelFabric.Construct(
            Community.Message,
            messageId=lastMsgId,
            authorId=trigger_uid,
            messageType=103,
        )
    ]
    if data.get("initialMessageContent"):
        lastMsgId = str(uuid4())
        messages.append(
            ModelFabric.Construct(
                Community.Message,
                messageId=lastMsgId,
                authorId=trigger_uid,
                messageType=0,
                content=data["initialMessageContent"],
            )
        )

    xndc_users = db.get(f"x{ndcId}", "Users")
    history = db.get(f"x{ndcId}", f"_Chat:{chatId}")
    await history.insert_many(messages)
    await table.update_one(
        {"id": chatId},
        {
            "$set": {
                "lastMessageId": lastMsgId,
                "lastMessageTimestamp": messages[-1]["timestamp"],
                f"lastReadedList.{trigger_uid}": messages[-1]["createdTime"],
            }
        },
    )

    chatInfo_obj = await Chat.Info(
        chatId, db, trigger_uid=trigger_uid, xndc_users=xndc_users, ndcId=ndcId
    )

    messages_obj = []

    for message in messages:
        user = await xndc_users.find_one({"id": message["authorId"]}) or {}

        globalBubbleId = user.get("bubbleId")
        chatBubbleId = user.get("chatBubbles", {}).get(chatId)

        bubbleId = chatBubbleId or globalBubbleId
        bubbleVersion = None

        if bubbleId:
            bubbles_table = db.get(table="ChatBubbles")
            bubble = await bubbles_table.find_one({"bubbleId": bubbleId}) or {}
            bubbleVersion = bubble.get("version", 1)

        messages_obj.append(
            await Chat.LongMessage(
                message,
                chatId,
                xndc_users,
                history_table=table,
                ndcId=ndcId,
                chatBubbleVersion=bubbleVersion,
                chatBubbleId=bubbleId,
            )
        )

    # -----

    users = db.get(f"x{ndcId}", "Users")
    g_users = db.get(table="Users")
    row2 = await users.find_one({"id": trigger_uid})

    if row2 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    global_row = await g_users.find_one({"id": trigger_uid})

    if global_row:
        if not row2.get("tagList"):
            global_tag_list = global_row.get("tagList")
            if global_tag_list:
                row2["tagList"] = global_tag_list

        if "isTeamMember" in global_row:
            row2["isTeamMember"] = global_row["isTeamMember"]

        if "isVerified" in global_row:
            row2["isVerified"] = global_row["isVerified"]
        if global_row.get("status", 0) in [9, 10]:
            row2["status"] = global_row["status"]
        if global_row.get("extensions", {}).get("__disabledLevel__"):
            row2["extensions"]["__disabledLevel__"] = global_row["extensions"][
                "__disabledLevel__"
            ]

        if ndcId == 0:
            row2 = global_row | row2

    async with await StoreService.create(trigger_uid, ndcId) as svc:
        row2["iconFrame"] = await svc.frame_icon(row2.get("frameId"))

    inviter = User.GetUserInfo(
        row2, triggerUserId=trigger_uid, extensions=row2.get("extensions"), ndcId=ndcId
    )

    if data.get("inviteeUids", []):
        asyncio.get_event_loop().create_task(
            send_admin_ws(
                {
                    "ndcId": ndcId,
                    "threadId": chatId,
                    "inviter": inviter,
                    "threadType": data["type"],
                },
                data["inviteeUids"],
                ApiBroadcastType.InviteChatPush,
            )
        )

    db.close()
    return Base.Answer(
        {"thread": chatInfo_obj, "messageList": messages_obj},
        spent_time=timestamp() - t1,
    )


# get chat history
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message?pagingType=t&size=25


@chats.get("/g/s/chat/thread/{chatId}/message")
@chats.get("/x{ndcId}/s/chat/thread/{chatId}/message")
async def get_chat_messages(
    request: Request, chatId: str, size: int = 25, pageToken: str = None, ndcId: int = 0
):
    t1 = timestamp()

    size = size if 0 < size < 101 else 25

    # parse page token
    start = parse_page_token(pageToken, 0)

    db = await Database().init()
    table = db.get(f"x{ndcId}", f"_Chat:{chatId}")
    messages = [
        item
        async for item in table.find()
        .skip(start)
        .limit(size)
        .sort("timestamp", DESCENDING)
    ]
    xndc_users = db.get(f"x{ndcId}", "Users")
    global_user = db.get(table="Users")
    messageList = []

    for message in messages:
        user = await xndc_users.find_one({"id": message["authorId"]}) or {}

        globalBubbleId = user.get("bubbleId")
        chatBubbleId = user.get("chatBubbles", {}).get(chatId)

        bubbleId = chatBubbleId or globalBubbleId
        bubbleVersion = None

        if bubbleId:
            bubbles_table = db.get(table="ChatBubbles")
            bubble = await bubbles_table.find_one({"bubbleId": bubbleId}) or {}
            bubbleVersion = bubble.get("version", 1)

        messageList.append(
            await Chat.LongMessage(
                message,
                chatId,
                xndc_users,
                history_table=table,
                ndcId=ndcId,
                chatBubbleVersion=bubbleVersion,
                chatBubbleId=bubbleId,
                global_user=global_user
            )
        )

    if len(messages) > 0:
        answer = Base.Answer(
            {
                "messageList": messageList,
                "paging": calculate_page_tokens(start, size, messageList),
            },
            spent_time=timestamp() - t1,
        )
        db.close()
        return answer
    else:
        db.close()
        return Base.Answer(
            {"messageList": [], "paging": {}}, spent_time=timestamp() - t1
        )


# send message
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message


@chats.post("/g/s/chat/thread/{chatId}/message")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/message")
@turtlelimiter(limit=3, period=TurtleTime.second, tag="send-message")
@strike_check
async def send_message(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    try:
        data = await request.json()
        if (
            (
                # [info] types in messagetypes.json
                data["type"] not in [0, 2, 3]
            )
            or (
                data.get("mediaType")
                and data["mediaType"] != 113
                and (not data.get("mediaUploadValue"))
            )
            or (
                data.get("mediaType", 0) == 103
                and (
                    not data.get("mediaUploadValue", "").startswith("ytv://")
                    or data["type"] != 0
                )
            )
            or (data.get("mediaType", 0) == 110 and data["type"] != 2)
            or (data["type"] != 0 and data.get("content") is not None)
            or (
                data["type"] == 3
                and (
                    not isinstance(data.get("stickerId"), str)
                    or not data["stickerId"].startswith("e/")
                )
            )
            or (
                data["type"] == 0
                and data.get("mediaType", 0) == 0
                and not isinstance(data.get("content"), str)
            )
        ):
            raise Exception()
    except Exception:
        return Errors.InvalidMessage(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    chat = db.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})

    staff = [chat_info["hostId"]] + chat_info.get("cohostsIds", [])
    if chat_info["isViewMode"] and trigger_uid not in staff:
        db.close()
        return Errors.ViewModeEnabled(timestamp() - t1, lang=request.state.lang)

    if trigger_uid not in chat_info["memberList"]:
        db.close()
        return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)

    if data.get("content"):
        if len(data["content"]) > Config.MAX_TEXT_SIZE:
            db.close()
            return Errors.BigMessage(timestamp() - t1, lang=request.state.lang)

    extensions = data.get("extensions", {})

    if data.get("mediaUploadValue"):
        try:
            if len(data.get("mediaUploadValue")) > Config.MAX_FILE_SIZE:
                db.close()
                return Errors.BigMediaContent(timestamp() - t1, lang=request.state.lang)
            s3 = resource(
                service_name=Config.S3_SERVICE_NAME,
                aws_access_key_id=Config.S3_ACCESS_KEY,
                aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
                endpoint_url=Config.S3_ENDPOINT_URL,
            )
            if data["mediaType"] == 100:
                image_bytes = b64decode(data["mediaUploadValue"])
                filetype = detect_file_ext(image_bytes)
                if filetype is None:
                    return Errors.InvalidMediaContent(
                        spent_time=timestamp() - t1, lang=request.state.lang
                    )

                if await bbnonsfw_manual_check(image_bytes):
                    return Errors.NSFWContent(
                        spent_time=timestamp() - t1, lang=request.state.lang
                    )

                filename = (
                    Config.S3_IMAGES_FOLDER
                    + "".join([choice(ascii_letters + digits) for _ in range(64)])
                    + filetype
                )
                body = ImageTools.compress(
                    b64decode(data["mediaUploadValue"]), filetype[1:]
                )
                s3.Bucket(Config.S3_BUCKET_NAME).put_object(Key=filename, Body=body)
                mediaLink = Config.MEDIA_BASE_URL + filename
            elif data["mediaType"] == 110:
                audio_bytes = b64decode(data["mediaUploadValue"])
                filename = (
                    Config.S3_VOICES_FOLDER
                    + "".join([choice(ascii_letters + digits) for _ in range(64)])
                    + ".aac"
                )
                extensions = extensions | {"duration": audio_length(audio_bytes)}
                s3.Bucket(Config.S3_BUCKET_NAME).put_object(
                    Key=filename, Body=audio_bytes
                )
                mediaLink = Config.MEDIA_BASE_URL + filename
            elif data["mediaType"] == 103:
                mediaLink = data.get("mediaUploadValue", "ytv://dQw4w9WgXcQ")
            else:
                mediaLink = None
        except Exception as e:
            print(e)
            db.close()
            return Errors.InvalidMessage(timestamp() - t1, lang=request.state.lang)
    else:
        mediaLink = None

    # link snippet
    # it's bugged so for now we ignore it
    """
	if (
		data.get("extensions", {}).get("linkSnippetList")
		and len(data["extensions"]["linkSnippetList"]) >= 1
	):
		linksnippet = data["extensions"]["linkSnippetList"][0]
		s3 = resource(
			service_name=Config.S3_SERVICE_NAME,
			aws_access_key_id=Config.S3_ACCESS_KEY,
			aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
			endpoint_url=Config.S3_ENDPOINT_URL,
		)
		image_bytes = b64decode(linksnippet["mediaUploadValue"])
		filetype = detect_file_ext(image_bytes)
		if filetype is None:
			return Errors.InvalidMediaContent(spent_time=timestamp()-t1, lang=request.state.lang)
		filename = (
			Config.S3_IMAGES_FOLDER
			+ "".join([choice(ascii_letters + digits) for _ in range(64)])
			+ filetype
		)
		body = ImageTools.compress(image_bytes, filetype[1:])
		s3.Bucket(Config.S3_BUCKET_NAME).put_object(Key=filename, Body=body)
		mediaLink = Config.MEDIA_BASE_URL + filename
		del data["extensions"]["linkSnippetList"]
		data["extensions"]["linkSnippetList"] = [
			{
				"body": None,
				"title": None,
				"favicon": None,
				"source": None,
				"link": linksnippet["link"],
				"deepLink": None,
				"mediaList": [[100, mediaLink, None]],
			}
		]
	"""
    if data.get("replyMessageId"):
        extensions.update({"replyMessageId": data["replyMessageId"]})

    if data.get("stickerId"):
        if data["stickerId"][2:].isdigit() or is_hex_str(
            data["stickerId"][2:], limited_to=8
        ):
            extensions.update(Chat.InternalSticker(data["stickerId"][2:]))
            data["mediaType"] = 113
            mediaLink = f"ndcsticker://{data['stickerId']}"
        # elif is_valid_uuid4(data["stickerId"]):
        # should be a custom sticker, but since we dont implemented it still...
        # [NOTE]: please implement it normally
        else:
            extensions.update(Chat.InternalSticker(data["stickerId"]))
            data["mediaType"] = 113
            mediaLink = f"ndcsticker://{data['stickerId']}"
        """        
        else:
            print("invalid stickerId:", data["stickerId"])
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )"""

    messageId = str(uuid4())
    xndc_users = db.get(f"x{ndcId}", "Users")
    global_user = db.get(table="Users")
    table = db.get(f"x{ndcId}", f"_Chat:{chatId}")
    message = ModelFabric.Construct(
        Community.Message,
        messageId=messageId,
        authorId=trigger_uid,
        messageType=data["type"],
        clientRefId=data.get("clientRefId", 0),
        content=data.get("content"),
        extensions=extensions,
        mediaType=data.get("mediaType", 0),
        mediaValue=mediaLink,
    )
    await table.insert_one(message)
    await chat.update_one(
        {"id": chatId},
        {
            "$set": {
                "lastMessageId": messageId,
                "lastMessageTimestamp": message["timestamp"],
                f"lastReadedList.{trigger_uid}": message["createdTime"],
            }
        },
    )

    user_table = db.get(f"x{ndcId}", "Users")
    user = await user_table.find_one({"id": trigger_uid}) or {}

    globalBubbleId = user.get("bubbleId")
    chatBubbleId = user.get("chatBubbles", {}).get(chatId)

    bubbleId = chatBubbleId or globalBubbleId
    bubbleVersion = None

    if bubbleId:
        bubbles_table = db.get(table="ChatBubbles")
        bubble = await bubbles_table.find_one({"bubbleId": bubbleId}) or {}
        bubbleVersion = bubble.get("version", 1)
    messageObj = await Chat.LongMessage(
        message,
        chatId,
        xndc_users,
        ndcId=ndcId,
        chatBubbleId=bubbleId,
        chatBubbleVersion=bubbleVersion,
        global_user=global_user
    )
    answer = Base.Answer({"message": messageObj}, spent_time=timestamp() - t1)

    ws_send_obj = {
        "t": 1000,
        "o": {
            "ndcId": ndcId,
            "chatMessage": messageObj,
            "alertOption": 1,
            "membershipStatus": 1,
        },
    }
    target = chat_info.get("memberList", []) + chat_info.get("invitedList", [])
    asyncio.get_event_loop().create_task(send_admin_ws(ws_send_obj, target))

    alert_options = chat_info.get("alertOptions", {})
    mentioned_uids = [
        m.get("uid")
        for m in extensions.get("mentionedArray", [])
        if isinstance(m, dict)
    ]
    notify_targets = []
    for usr in target:
        if usr == trigger_uid:
            continue
        alert = alert_options.get(usr, 1)
        if alert == 2 and usr not in mentioned_uids:
            continue
        notify_targets.append(usr)

    if notify_targets:
        asyncio.get_event_loop().create_task(
            send_admin_ws(
                {
                    "ndcId": ndcId,
                    "threadId": chatId,
                    "messageType": data["type"],
                    "content": data.get("content"),
                    "author": messageObj["author"],
                },
                notify_targets,
                ApiBroadcastType.ChatMessagePush,
            )
        )
        asyncio.get_event_loop().create_task(
            PushProcessor.SendToUsers(
                notify_targets,
                Push.ChatMessage(chat_info, message, messageObj["author"], ndcId),
            )
        )

    db.close()
    return answer


# get message
# GET /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message/3c10a84c-c9af-4ab1-84fe-ea0c8d5f2f0f


@chats.get("/g/s/chat/thread/{chatId}/message/{messageId}")
@chats.get("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}")
async def get_message(request: Request, chatId: str, messageId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    chat_table = db.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one({"id": chatId})

    if not chat_info:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    if chat_info.get("chatType") != 2:
        if trigger_uid not in chat_info.get("memberList", []):
            db.close()
            return Errors.NotEnoughRights(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

    message_table = db.get(f"x{ndcId}", f"_Chat:{chatId}")
    message_data = await message_table.find_one({"messageId": messageId})

    if not message_data:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    xndc_users = db.get(f"x{ndcId}", "Users")

    user = await xndc_users.find_one({"id": message_data["authorId"]}) or {}

    globalBubbleId = user.get("bubbleId")
    chatBubbleId = user.get("chatBubbles", {}).get(chatId)

    bubbleId = chatBubbleId or globalBubbleId
    bubbleVersion = None

    if bubbleId:
        bubbles_table = db.get(table="ChatBubbles")
        bubble = await bubbles_table.find_one({"bubbleId": bubbleId}) or {}
        bubbleVersion = bubble.get("version", 1)

    message_obj = await Chat.LongMessage(
        message_data,
        chatId,
        xndc_users,
        history_table=message_table,
        ndcId=ndcId,
        chatBubbleVersion=bubbleVersion,
        chatBubbleId=bubbleId,
    )

    answer = Base.Answer({"message": message_obj}, spent_time=timestamp() - t1)
    db.close()
    return answer


# delete message
# DELETE /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message/3c10a84c-c9af-4ab1-84fe-ea0c8d5f2f0f


@chats.delete("/g/s/chat/thread/{chatId}/message/{messageId}")
@chats.post("/g/s/chat/thread/{chatId}/message/{messageId}/{admin}")
@chats.delete("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/message/{messageId}/{admin}")
async def delete_message(
    request: Request, chatId: str, messageId: str, ndcId: int = 0, admin: str = ""
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]
    work = False

    db = await Database().init()
    table = db.get(f"x{ndcId}", f"_Chat:{chatId}")
    original_message = await table.find_one({"messageId": messageId})
    if admin.lower() == "admin":  # note: looks stupid
        xndc_users = db.get(f"x{ndcId}", "Users")

        user = await xndc_users.find_one({"id": trigger_uid})
        if user and user.get("role", 0) in [100, 101, 102, 250, 251, 555]:
            await table.delete_one({"messageId": messageId})

            # todo add it to moderation logs maybe?

            db.close()
            return Base.Answer(spent_time=timestamp() - t1)

    if original_message["authorId"] != trigger_uid:
        chat = db.get(f"x{ndcId}", "Chats")
        chat_info = await chat.find_one({"id": chatId})
        if (
            trigger_uid not in chat_info.get("cohostsIds", [])
            and trigger_uid != chat_info["hostId"]
        ):
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        else:
            work = True
        if chat_info["chatType"] == 0 or chat_info["chatType"] == 1:
            work = True
    else:
        work = True

    if work:
        await table.update_one(
            {"messageId": messageId}, {"$set": {"content": None, "messageType": 100}}
        )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


# update message
# POST /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message/3c10a84c-c9af-4ab1-84fe-ea0c8d5f2f0f

# to reduce complexity it will be in send message later
# like, "if you have valid message id - sure, we will update message for ya"

# get chat members
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/member?type=default&start=0&size=40


@chats.get("/g/s/chat/thread/{chatId}/member")
@chats.get("/x{ndcId}/s/chat/thread/{chatId}/member")
async def get_chat_members(
    request: Request,
    chatId: str,
    type: str = "default",
    start: int = 0,
    size: int = 25,
    ndcId: int = 0,
    q: str = "",
    pageToken: str | None = None,
):
    t1 = timestamp()

    if type not in ["default", "co-host", "at", "organizer-transfer-candidates"]:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    chat_table = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one({"id": chatId})

    if not chat_info:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    xndc_users = connection.get(f"x{ndcId}", "Users")

    if pageToken:
        start = parse_page_token(pageToken, start)

    if type == "default":
        chat_info = await chat_table.find_one(
            {"id": chatId}, {"memberList": 1, "invitedList": 1}
        )
        if not chat_info:
            connection.close()
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        members_in_chat = chat_info.get("memberList", [])
        invited_in_chat = chat_info.get("invitedList", [])
        all_ids = members_in_chat + invited_in_chat
        target_ids = all_ids[start : start + size]

        users_data = {
            u["id"]: u async for u in xndc_users.find({"id": {"$in": target_ids}})
        }

        member_list = []
        for uid in target_ids:
            if uid in users_data:
                udata = users_data[uid]
                async with await StoreService.create(uid, ndcId) as svc:
                    udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))

                member_list.append(
                    User.GetUserInfo(
                        udata,
                        membershipStatus=(1 if uid in members_in_chat else 2),
                        ndcId=ndcId,
                    )
                )

    elif type == "at":
        chat_info = await chat_table.find_one({"id": chatId}, {"memberList": 1})
        if not chat_info:
            connection.close()
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        members_in_chat = chat_info.get("memberList", [])
        query = {"id": {"$in": members_in_chat}}
        if q:
            query["nickname"] = {"$regex": f"^{regex_escape(q)}", "$options": "i"}

        member_list = []
        async for u in xndc_users.find(query).skip(start).limit(size):
            async with await StoreService.create(u["id"], ndcId) as svc:
                u["iconFrame"] = await svc.frame_icon(u.get("frameId"))

            member_list.append(User.GetUserInfo(u, membershipStatus=1, ndcId=ndcId))

    elif type == "co-host":
        chat_info = await chat_table.find_one(
            {"id": chatId}, {"memberList": 1, "cohostsIds": 1}
        )
        if not chat_info:
            connection.close()
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        members_in_chat = chat_info.get("memberList", [])
        cohosts_in_chat = chat_info.get("cohostsIds", [])

        temp_ids = []
        seen_ids = set()
        for uid in members_in_chat + cohosts_in_chat:
            if uid not in seen_ids:
                temp_ids.append(uid)
                seen_ids.add(uid)

        target_ids = [
            uid
            for uid in temp_ids
            if not (uid in members_in_chat and uid in cohosts_in_chat)
        ][start : start + size]

        query = {"id": {"$in": target_ids}}
        if q:
            query["nickname"] = {"$regex": f"^{regex_escape(q)}", "$options": "i"}

        users_data = {u["id"]: u async for u in xndc_users.find(query)}
        member_list = []

        for uid in target_ids:
            if uid in users_data:
                udata = users_data[uid]
                async with await StoreService.create(uid, ndcId) as svc:
                    udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))

                member_list.append(
                    User.GetUserInfo(udata, membershipStatus=1, ndcId=ndcId)
                )

    elif type == "organizer-transfer-candidates":
        chat_info = await chat_table.find_one(
            {"id": chatId}, {"memberList": 1, "cohostsIds": 1, "hostId": 1}
        )
        if not chat_info:
            connection.close()
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        members_in_chat = chat_info.get("memberList", [])
        cohosts_in_chat = chat_info.get("cohostsIds", [])
        all_ids = members_in_chat + cohosts_in_chat
        target_ids = all_ids[start : start + size]

        query = {"id": {"$in": target_ids}}
        if q:
            query["nickname"] = {"$regex": f"^{regex_escape(q)}", "$options": "i"}

        users_data = {u["id"]: u async for u in xndc_users.find(query)}

        member_list = []
        _temp = set()
        for uid in target_ids:
            if uid not in users_data or uid == chat_info.get("hostId") or uid in _temp:
                continue
            udata = users_data[uid]
            async with await StoreService.create(uid, ndcId) as svc:
                udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))
            user = User.GetUserInfo(
                udata,
                membershipStatus=(1 if uid in members_in_chat else 2),
                ndcId=ndcId,
            )
            user["isAvailableCandidate"] = True
            member_list.append(user)
            _temp.add(uid)

    else:
        connection.close()
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    answer = Base.Answer(
        {
            "memberList": member_list,
            "paging": calculate_page_tokens(start, size, member_list),
        },
        spent_time=timestamp() - t1,
    )
    connection.close()
    return answer


# get cohosts
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host&start=0&size=40


@chats.get("/g/s/chat/thread/{chatId}/co-host")
@chats.get("/x{ndcId}/s/chat/thread/{chatId}/co-host")
async def get_chat_cohosts(
    request: Request,
    chatId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
    ndcId: int = 0,
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, start)
    trigger_uid = request.state.session["uid"]

    connection = await Database().init()
    chat_table = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one(
        {"id": chatId}, {"cohostsIds": 1, "hostId": 1}
    )

    if not chat_info:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    if trigger_uid != chat_info["hostId"]:
        connection.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    cohosts_ids_all = chat_info.get("cohostsIds", [])
    cohosts_ids_sliced = cohosts_ids_all[start : start + size]
    xndc_users = connection.get(f"x{ndcId}", "Users")

    users_data = {
        u["id"]: u async for u in xndc_users.find({"id": {"$in": cohosts_ids_sliced}})
    }
    user_list = []
    for uid in cohosts_ids_sliced:
        udata = users_data[uid]
        if uid in users_data:
            async with await StoreService.create(uid, ndcId) as svc:
                udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))
            user_list.append(User.GetUserInfo(udata, membershipStatus=1, ndcId=ndcId))

    answer = Base.Answer(
        {
            "userProfileList": user_list,
            "paging": calculate_page_tokens(start, size, user_list),
        },
        spent_time=timestamp() - t1,
    )
    connection.close()
    return answer


# set cohosts
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host


@chats.post("/g/s/chat/thread/{chatId}/co-host")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/co-host")
async def set_cohosts(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    data = await request.json()
    trigger_uid = request.state.session["uid"]
    new_cohosts = data.get("uidList", [])

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})
    if not chat_info:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    if trigger_uid != chat_info["hostId"]:
        sensitive_table = connection.get(table="Users")

        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    await chat.update_one(
        {"id": chatId}, {"$push": {"cohostsIds": {"$each": new_cohosts}}}
    )

    xndc_users = connection.get(f"x{ndcId}", "Users")
    users_data = {
        u["id"]: u async for u in xndc_users.find({"id": {"$in": new_cohosts}})
    }

    user_profile_list = []
    for uid in new_cohosts:
        udata = users_data[uid]
        if uid in users_data:
            async with await StoreService.create(uid, ndcId) as svc:
                udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))
            user_profile_list.append(
                User.GetUserInfo(udata, membershipStatus=1, ndcId=ndcId)
            )

    answer = Base.Answer(
        {"userProfileList": user_profile_list, "paging": {}},
        spent_time=timestamp() - t1,
    )

    connection.close()
    return answer


# remove cohost
# [delete] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host/010a4dd5-290f-404d-a671-a7048199d83f


@chats.delete("/g/s/chat/thread/{chatId}/co-host/{uid}")
@chats.delete("/x{ndcId}/s/chat/thread/{chatId}/co-host/{uid}")
async def del_cohosts(request: Request, chatId: str, uid: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})
    if not chat_info:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    if trigger_uid != chat_info["hostId"]:
        sensitive_table = connection.get(table="Users")
        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    await chat.update_one({"id": chatId}, {"$pull": {"cohostsIds": uid}})

    chat_info = await chat.find_one({"id": chatId})
    cohosts = chat_info.get("cohostsIds", [])
    xndc_users = connection.get(f"x{ndcId}", "Users")

    users_data = {u["id"]: u async for u in xndc_users.find({"id": {"$in": cohosts}})}

    user_profile_list = []
    for uid in cohosts:
        udata = users_data[uid]
        if uid in users_data:
            async with await StoreService.create(uid, ndcId) as svc:
                udata["iconFrame"] = await svc.frame_icon(udata.get("frameId"))
            user_profile_list.append(
                User.GetUserInfo(udata, membershipStatus=1, ndcId=ndcId)
            )

    answer = Base.Answer(
        {"userProfileList": user_profile_list, "paging": {}},
        spent_time=timestamp() - t1,
    )

    connection.close()
    return answer


# TODO: We will need to create a system for sending and receiving requests to assume the host role—though it is not yet clear exactly how.
@chats.post("/g/s/chat/thread/{chatId}/transfer-organizer")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/transfer-organizer")
async def transfer_host(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    data = await request.json()
    trigger_uid = request.state.session["uid"]
    host_candidates = data.get("uidList", [])
    if not host_candidates:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if isinstance(host_candidates, str):
        host_candidates = [host_candidates]

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})
    if not chat_info:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    if trigger_uid != chat_info["hostId"]:
        sensitive_table = connection.get(f"x{ndcId}", "Users")
        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or (
            not UserRole.is_global_staff(user.get("role", 0))
            and not UserRole.is_local_staff(user.get("role", 0))
        ):
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    reset_tip_info = {
        "tipOptionList": [
            {"value": 2, "icon": "https://media.altamino.top/monetization/coins.png"},
            {
                "value": 10,
                "icon": "https://media.altamino.top/monetization/stack_of_coins.png",
            },
            {
                "value": 50,
                "icon": "https://media.altamino.top/monetization/tall_stack_of_coins.png",
            },
        ],
        "tipMaxCoin": 500,
        "tippersCount": 0,
        "tippable": True,
        "tipMinCoin": 1,
        "tipCustomOption": {
            "value": None,
            "icon": "https://media.altamino.top/monetization/bag_of_coins.png",
        },
        "tippedCoins": 0,
        "tippersList": [],
    }

    await chat.update_one(
        {"id": chatId},
        {"$set": {"hostId": host_candidates[0], "tipInfo": reset_tip_info}},
    )
    answer = Base.Answer(
        spent_time=timestamp() - t1,
    )

    connection.close()
    return answer


@chats.post("/x{ndcId}/s/chat/thread/{chatId}/tipping")
@chats.post("/g/s/chat/thread/{chatId}/tipping")
async def tip_chat(request: Request, chatId: str, ndcId: int = 0):
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

    connection = await Database().init()
    users_table = connection.get(table="Users")
    sender = await users_table.find_one({"id": trigger_uid})
    if sender is None:
        connection.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    if sender.get("coins", 0.0) < coins:
        connection.close()
        return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)

    chat_table = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one({"id": chatId})
    if chat_info is None:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    host_id = chat_info.get("hostId")

    # Deduct from sender and credit chat host
    await users_table.update_one({"id": trigger_uid}, {"$inc": {"coins": -coins}})
    if host_id:
        await users_table.update_one({"id": host_id}, {"$inc": {"coins": coins}})

    # Update chat tipInfo leaderboard
    tip_info = chat_info.get("tipInfo", {})
    tippers_list = tip_info.get("tippersList", [])

    tipper_entry = next((t for t in tippers_list if t.get("uid") == trigger_uid), None)
    if tipper_entry:
        tipper_entry["totalTippedCoins"] = round(
            tipper_entry.get("totalTippedCoins", 0.0) + coins, 2
        )
    else:
        ndc_users = connection.get(f"x{ndcId}", "Users")
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
        "tipOptionList": [
            {"value": 2, "icon": "https://media.altamino.top/monetization/coins.png"},
            {
                "value": 10,
                "icon": "https://media.altamino.top/monetization/stack_of_coins.png",
            },
            {
                "value": 50,
                "icon": "https://media.altamino.top/monetization/tall_stack_of_coins.png",
            },
        ],
        "tipMaxCoin": 500,
        "tippersCount": len(tippers_list),
        "tippable": True,
        "tipMinCoin": 1,
        "tipCustomOption": {
            "value": None,
            "icon": "https://media.altamino.top/monetization/bag_of_coins.png",
        },
        "tippedCoins": new_tipped_coins,
        "tippersList": tippers_list,
    }

    await chat_table.update_one({"id": chatId}, {"$set": {"tipInfo": updated_tip_info}})

    g_table = connection.get(table="Users")
    table = connection.get(database=f"x{ndcId}", table="Users")

    row2 = await table.find_one({"id": trigger_uid})
    if row2 is not None:
        global_row = await g_table.find_one({"id": trigger_uid})
        if global_row:
            row2["tagList"] = list(
                set(global_row.get("tagList", []) + row2.get("tagList", []))
            )

            row2["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)

            if "isTeamMember" in global_row:
                row2["isTeamMember"] = global_row["isTeamMember"]

            if "isVerified" in global_row:
                row2["isVerified"] = global_row["isVerified"]
            if global_row.get("status", 0) in [9, 10]:
                row2["status"] = global_row["status"]
            if global_row.get("extensions", {}).get("__disabledLevel__"):
                row2["extensions"]["__disabledLevel__"] = global_row["extensions"][
                    "__disabledLevel__"
                ]

            if ndcId == 0:
                row2 = global_row | row2

        connection.close()
        async with await StoreService.create(trigger_uid, ndcId) as svc:
            row2["iconFrame"] = await svc.frame_icon(row2.get("frameId"))

        message = ModelFabric.Construct(
            Community.Message,
            authorId=trigger_uid,
            messageType=120,
            extensions={"tippingCoins": coins},
        )

        message["threadId"] = chatId
        message["author"] = User.GetUserInfo(
                    row2,
                    triggerUserId=trigger_uid,
                    extensions=row2.get("extensions"),
                    ndcId=ndcId,
                )

        ws_send_obj = {
            "t": 1000,
            "o": {
                "ndcId": ndcId,
                "membershipStatus": 1,
                "chatMessage": message
            }
        }
        ws_send_obj["o"]["chatMessage"]["type"] = ws_send_obj["o"]["chatMessage"].pop("messageType")

        target = chat_info.get("memberList", []) + chat_info.get("invitedList", [])
        asyncio.get_event_loop().create_task(send_admin_ws(ws_send_obj, target))

    return Base.Answer({"tipInfo": updated_tip_info}, spent_time=timestamp() - t1)

async def _tip_log_list_response(connection, ndcId: str, chatId: str, start: int, size: int, t1):
    chat_table = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one({"id": chatId})
    if chat_info is None:
        return None

    tip_info = chat_info.get("tipInfo", {})
    tippers_list = tip_info.get("tippersList", [])

    return {
        "tipSummary": {
            "tippersCount": tip_info.get("tippersCount", len(tippers_list)),
            "totalCoins": tip_info.get("tippedCoins", 0),
        },
        "globalTipSummary": {
            "tippersCount": 0,
            "totalCoins": 0,
        },
        "paging": {
            "nextPageToken": str(start + size) if start + size < len(tippers_list) else None,
            "prevPageToken": str(max(start - size, 0)) if start > 0 else None,
        },
    }

@chats.get("/x{ndcId}/s/chat/thread/{chatId}/tipping/tipped-users")
@chats.get("/g/s/chat/thread/{chatId}/tipping/tipped-users")
async def tipped_users(request: Request, chatId: str, ndcId: int = 0, start: int = 0, size: int = 25):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    connection = await Database().init()
    chat_table = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat_table.find_one({"id": chatId})
    print(chatId,": ",chat_info)
    if chat_info is None:
        connection.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    tip_info = chat_info.get("tipInfo", {})
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


@chats.get("/x{ndcId}/s/chat/thread/{chatId}/tipping/tipped-users-summary")
@chats.get("/g/s/chat/thread/{chatId}/tipping/tipped-users-summary")
async def tipped_users_summary(request: Request, chatId: str, ndcId: int = 0, start: int = 0, size: int = 15):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    result = await _tip_log_list_response(connection, ndcId, chatId, start, size, t1)
    connection.close()
    if result is None:
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    return Base.Answer(result, spent_time=timestamp() - t1)

# invite to chat
# /g/s/chat/thread/9978643e-5fa5-4b0b-82a4-70a5c71e32b1/member/invite


@chats.post("/g/s/chat/thread/{chatId}/member/invite")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/member/invite")
@strike_check
async def invite_to_chat(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    data = await request.json()
    uid = request.state.session["uid"]
    toInvite = data.get("uids", [])

    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})
    staff = [chat_info["hostId"]] + chat_info.get("cohostsId", [])
    if uid not in staff or uid not in chat_info["memberList"]:
        if not data.get("canMembersInvite", True):
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    actuallyInvite = []
    for member in toInvite:
        if member in chat_info["bannedUids"] and uid != chat_info["hostId"]:
            continue
        if member in chat_info["invitedList"] or member in chat_info["memberList"]:
            continue
        actuallyInvite.append(member)

    users = connection.get(f"x{ndcId}", "Users")
    g_users = connection.get(table="Users")
    row2 = await users.find_one({"id": uid})

    if row2 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    global_row = await g_users.find_one({"id": uid})

    if global_row:
        if not row2.get("tagList"):
            global_tag_list = global_row.get("tagList")
            if global_tag_list:
                row2["tagList"] = global_tag_list

        if "isTeamMember" in global_row:
            row2["isTeamMember"] = global_row["isTeamMember"]

        if "isVerified" in global_row:
            row2["isVerified"] = global_row["isVerified"]
        if global_row.get("status", 0) in [9, 10]:
            row2["status"] = global_row["status"]
        if global_row.get("extensions", {}).get("__disabledLevel__"):
            row2["extensions"]["__disabledLevel__"] = global_row["extensions"][
                "__disabledLevel__"
            ]

        if ndcId == 0:
            row2 = global_row | row2

    async with await StoreService.create(uid, ndcId) as svc:
        row2["iconFrame"] = await svc.frame_icon(row2.get("frameId"))

    inviter = User.GetUserInfo(
        row2, triggerUserId=uid, extensions=row2.get("extensions"), ndcId=ndcId
    )

    await chat.update_one(
        {"id": chatId}, {"$push": {"invitedList": {"$each": actuallyInvite}}}
    )

    connection.close()
    asyncio.get_event_loop().create_task(
        send_admin_ws(
            {
                "ndcId": ndcId,
                "threadId": chatId,
                "inviter": inviter,
                "threadType": chat_info["chatType"],
            },
            actuallyInvite,
            ApiBroadcastType.InviteChatPush,
        )
    )
    return Base.Answer(spent_time=timestamp() - t1)


# join chat
# /g/s/chat/thread/a8b4942e-58e7-4699-957c-6dde40f2f5e8/member/9b1ef6f0-707c-4bc2-979f-a5650109a6c0


@chats.post("/g/s/chat/thread/{chatId}/member/{userId}")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/member/{userId}")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="jl-chat")
async def join_chat(request: Request, chatId: str, userId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]

    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    if userId != uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})
    if userId in chat_info["memberList"]:
        connection.close()
        return Base.Answer({"membershipStatus": 1}, timestamp() - t1)
    if userId in chat_info["bannedUids"]:
        connection.close()
        return Errors.RemovedFromChat(timestamp() - t1, lang=request.state.lang)

    messageId = str(uuid4())

    table = connection.get(f"x{ndcId}", f"_Chat:{chatId}")
    message = ModelFabric.Construct(
        Community.Message,
        messageId=messageId,
        authorId=userId,
        messageType=101,
        clientRefId=0,
        content=None,
    )
    await table.insert_one(message)

    await chat.update_one(
        {"id": chatId},
        {
            "$push": {"memberList": userId},
            "$pull": {"invitedList": userId},
            "$set": {
                "lastMessageId": messageId,
                "lastMessageTimestamp": message["timestamp"],
                f"lastReadedList.{userId}": message["createdTime"],
            },
        },
    )

    xndc_users = connection.get(f"x{ndcId}", "Users")
    messageObj = await Chat.LongMessage(message, chatId, xndc_users, ndcId=ndcId)
    ws_send_obj = {
        "t": 1000,
        "o": {
            "ndcId": ndcId,
            "chatMessage": messageObj,
            "alertOption": 1,
            "membershipStatus": 1,
        },
    }
    target = chat_info.get("memberList", []) + chat_info.get("invitedList", [])
    asyncio.get_event_loop().create_task(send_admin_ws(ws_send_obj, target))

    connection.close()
    return Base.Answer({"membershipStatus": 1}, timestamp() - t1)


# leave chat
# /g/s/chat/thread/a8b4942e-58e7-4699-957c-6dde40f2f5e8/member/9b1ef6f0-707c-4bc2-979f-a5650109a6c0


@chats.delete("/g/s/chat/thread/{chatId}/member/{userId}")
@chats.delete("/x{ndcId}/s/chat/thread/{chatId}/member/{userId}")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="jl-chat")
async def leave_chat(
    request: Request, chatId: str, userId: str, allowRejoin: int = 0, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]
    messageId = str(uuid4())
    work = False
    ban = False

    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    chat_info = await chat.find_one({"id": chatId})

    if userId == uid:
        print("user leaving")
        work = True

    if userId != uid:
        print("user not leaving, its kick")
        if userId == chat_info["hostId"]:
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        elif uid not in chat_info.get("cohostsIds", []) and uid != chat_info["hostId"]:
            connection.close()
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        else:
            work = True

    if allowRejoin != 1:
        print("allow rejoin obviously not 1")
        if uid in chat_info.get("cohostsIds", []) or uid == chat_info["hostId"]:
            print("ok you have rights")
            ban = True
        else:
            print("haha you havent rights")
            ban = False
    if ban is True and userId == uid:
        print("ok ban urself is bad")
        ban = False

    if work:
        table = connection.get(f"x{ndcId}", f"_Chat:{chatId}")
        message = ModelFabric.Construct(
            Community.Message,
            messageId=messageId,
            authorId=userId,
            messageType=102,
            clientRefId=0,
            content=None,
        )
        await table.insert_one(message)

        isBan = {"$push": {"bannedUids": userId}} if ban else {}
        await chat.update_one(
            {"id": chatId},
            {
                "$pull": {"memberList": userId, "invitedList": userId},
                "$set": {
                    "lastMessageId": messageId,
                    "lastMessageTimestamp": message["timestamp"],
                },
            }
            | isBan,
        )

        xndc_users = connection.get(f"x{ndcId}", "Users")
        messageObj = await Chat.LongMessage(message, chatId, xndc_users, ndcId=ndcId)
        ws_send_obj = {
            "t": 1000,
            "o": {
                "ndcId": ndcId,
                "chatMessage": messageObj,
                "alertOption": 1,
                "membershipStatus": 1,
            },
        }

        target = chat_info.get("memberList", []) + chat_info.get("invitedList", [])
        asyncio.get_event_loop().create_task(send_admin_ws(ws_send_obj, target))

    connection.close()
    return Base.Answer({"membershipStatus": 0}, spent_time=timestamp() - t1)


# mark chat as read
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/mark-as-read


@chats.post("/g/s/chat/thread/{chatId}/mark-as-read")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/mark-as-read")
async def mark_as_read(request: Request, chatId: str, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]

    try:
        data = await request.json()
        if not data.get("messageId") or not data.get("createdTime"):
            raise Exception()
    except Exception:
        return Errors.InvalidMessage(timestamp() - t1, lang=request.state.lang)

    connection = await Database().init()
    chat = connection.get(f"x{ndcId}", "Chats")
    history = connection.get(f"x{ndcId}", f"_Chat:{chatId}")
    msg = await history.find_one({"messageId": data["messageId"]})
    if msg:
        readTimestamp = msg["createdTime"]
        await chat.update_one(
            {"id": chatId}, {"$set": {f"lastReadedList.{uid}": readTimestamp}}
        )

        connection.close()
        return Base.Answer({"lastReadTime": readTimestamp}, spent_time=timestamp() - t1)

    connection.close()
    return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)


# toggle things
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/view-only/enable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/view-only/disable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/members-can-invite/enable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/members-can-invite/disable


@chats.post("/g/s/chat/thread/{chatId}/{parameter}/{mode}")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/{parameter}/{mode}")
async def toggle_things(
    chatId: str, mode: str, parameter: str, request: Request, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    if mode not in ["disable", "enable"]:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if parameter not in ["members-can-invite", "view-only"]:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Chats")
    chat_info = await table.find_one({"id": chatId})

    if chat_info["hostId"] == trigger_uid or trigger_uid in chat_info.get(
        "cohostsIds", []
    ):
        if parameter == "view-only":
            await table.update_one(
                {"id": chatId},
                {"$set": {"isViewMode": True if mode == "enable" else False}},
            )

            history = db.get(f"x{ndcId}", f"_Chat:{chatId}")
            messageId = str(uuid4())
            message = ModelFabric.Construct(
                Community.Message,
                messageId=messageId,
                authorId=trigger_uid,
                messageType=125 if mode == "enable" else 126,
            )
            await history.insert_one(message)
            await table.update_one(
                {"id": chatId},
                {
                    "$set": {
                        "lastMessageId": messageId,
                        "lastMessageTimestamp": message["timestamp"],
                        f"lastReadedList.{trigger_uid}": message["createdTime"],
                    }
                },
            )

            xndc_users = db.get(f"x{ndcId}", "Users")
            user = await xndc_users.find_one({"id": message["authorId"]}) or {}

            globalBubbleId = user.get("bubbleId")
            chatBubbleId = user.get("chatBubbles", {}).get(chatId)

            bubbleId = chatBubbleId or globalBubbleId
            bubbleVersion = None

            if bubbleId:
                bubbles_table = db.get(table="ChatBubbles")
                bubble = await bubbles_table.find_one({"bubbleId": bubbleId}) or {}
                bubbleVersion = bubble.get("version", 1)

            messageObj = await Chat.LongMessage(
                message,
                chatId,
                xndc_users,
                ndcId=ndcId,
                chatBubbleVersion=bubbleVersion,
                chatBubbleId=bubbleId,
            )

            ws_send_obj = {
                "t": 1000,
                "o": {
                    "ndcId": ndcId,
                    "chatMessage": messageObj,
                    "alertOption": 1,
                    "membershipStatus": 1,
                },
            }
            target = chat_info.get("memberList", []) + chat_info.get("invitedList", [])
            asyncio.get_event_loop().create_task(send_admin_ws(ws_send_obj, target))
        elif parameter == "members-can-invite":
            await table.update_one(
                {"id": chatId},
                {"$set": {"canMembersInvite": True if mode == "enable" else False}},
            )

        db.close()
        return Base.Answer(spent_time=timestamp() - t1)

    else:
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)


@chats.post("/g/s/chat/thread/{chatId}/member/{userId}/alert")
@chats.post("/x{ndcId}/s/chat/thread/{chatId}/member/{userId}/alert")
async def chat_alert_options(
    chatId: str, userId: str, request: Request, ndcId: int = 0
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]
    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    if uid != userId:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    data = await request.json()
    alert_option = data.get("alertOption")

    if alert_option not in (ChatAlertOptions.ON, ChatAlertOptions.OFF):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    chat = db.get(f"x{ndcId}", "Chats")
    await chat.update_one(
        {"id": chatId}, {"$set": {f"alertOptions.{uid}": alert_option}}
    )
    db.close()
    return Base.Answer(spent_time=timestamp() - t1)
