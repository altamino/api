from base64 import b85encode, b85decode, b64decode
from pymongo import ASCENDING, DESCENDING
from string import ascii_letters, digits
from re import compile as regex_compile
from fastapi import APIRouter, Request
from time import time as timestamp
from datetime import datetime
from random import choice
from uuid import uuid4
import asyncio

from boto3 import resource

#import sys
#sys.path.append('../')
from objects import *
from helpers.config import Config
from helpers.database.mongo import *
from helpers.adminWS import send_admin_ws
from helpers.imageTools import ImageTools
from helpers.routers.cachable import CachableRoute

chats = APIRouter()
chats.route_class = CachableRoute

# chat search
# /g/s/chat/thread/explore/search?q=Hello&size=25

@chats.get("/g/s/chat/thread/explore/search")
async def user_search(request: Request, q: str = "", size: int = 25, pageToken: str | None = None):
    t1 = timestamp()
    size = size if 0 > size > 101 else 25

    # parse page token
    if pageToken:
        try: start = int(b85decode(pageToken).decode())
        except: start = 0
    else: start = 0

    db = await Database().init()
    table = await db.get("x0", "Chats")
    query = {"title": regex_compile(r"{}".format(q))}
    chats = [item async for item in table.find(query).skip(start).limit(size).sort("timestamp", DESCENDING)]  
    
    if len(chats) > 0:
        answer = Base.Answer({
            "threadListWrapper": {
                "threadList": [
                    await Chat.Info(item['id'], db)
                    for item in chats
                ],
                "userInfoInThread": {
                    item['id']: {
                        "userProfileCount": 0,
                        "userProfileList": []
                    }
                    for item in chats
                },
                "paging": {
                    "nextPageToken": b85encode(str(size+start).encode()).decode(),
                    "prevPageToken": b85encode(("0" if start - size <= 0 else str(start-size)).encode()).decode()
                },
                "playlistInThreadList": {}
            },
            "communityInfoMapping": {}
        }, spent_time=timestamp()-t1)
        await db.close()
        return answer
    else:
        await db.close()
        return Base.Answer({
            "messageList": [],
            "paging": {}
        }, spent_time=timestamp()-t1)

# get global recommended chats
# /g/s/live-layer/public-chats

@chats.get("/g/s/live-layer/public-chats")
async def get_recommended_chats(request: Request):
    t1 = timestamp()
    
    trigger_uid = request.state.session.get('uid')
    con = await Database().init()

    answer = {
        "threadList": [
            await Chat.Info("e92cde26-3067-457f-930a-0be3b99dc9b5", trigger_uid=trigger_uid, connection=con),
            await Chat.Info("0f668f3a-c5f5-42e0-b552-58b270e7841c", trigger_uid=trigger_uid, connection=con)
        ]
    }
    await con.close()
    return Base.Answer(answer, spent_time=timestamp()-t1)

# get chat info
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d

@chats.get("/g/s/chat/thread/{chatId}")
async def get_chat_info(chatId: str, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    trigger_uid = request.state.session['uid']
    
    return Base.Answer({
        "thread": await Chat.Info(chatId, trigger_uid=trigger_uid)
    }, spent_time=timestamp()-t1)

# edit chat
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d

@chats.post("/g/s/chat/thread/{chatId}")
async def edit_chat(chatId: str, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    data = await request.json()
    trigger_uid = request.state.session['uid']
    
    db = await Database().init()
    table = await db.get("x0", "Chats")
    chat_info = await table.find_one({"id": chatId})
    
    if chat_info['hostId'] == trigger_uid or trigger_uid in chat_info['cohostsIds']:
        bg = data.get("extensions", {}).get("bm", [None, None])[1]

        update_chat = {}
        if data.get("content"):
            update_chat.update({"description": data['content']})
        if data.get("title"):
            update_chat.update({"title": data['title']})
        if data.get("icon"):
            update_chat.update({"icon": data['icon']})
        if bg:
            update_chat.update({"background": bg})
        if data.get("extensions", {}).get("pinAnnouncement"):
            update_chat.update({"pinAnnouncement": data['extensions']["pinAnnouncement"]})
        if data.get("extensions", {}).get("announcement"):
            update_chat.update({"announcement": data['extensions']["announcement"]})

        print(update_chat)

        if len(update_chat) > 1:
            await table.update_one(
                {"id": chatId},
                {"$set": update_chat}
            )

        answer = Base.Answer({
            "thread": await Chat.Info(chatId, trigger_uid=trigger_uid, connection=db)
        }, spent_time=timestamp()-t1)

        await db.close()
        return answer
    
    else:
        await db.close()
        return Errors.NotEnoughRights(timestamp()-t1)

# if chat exists + where user is

@chats.get("/g/s/chat/thread")
async def if_chat_exists(request: Request, type: str, q: str | None = None, size: int = 25, start: int = 0):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    uid = request.state.session['uid']
    if type == "exist-single" and q:

        db = await Database().init()
        table = await db.get("x0", "Chats")
        query = {
            "chatType": 0,
            '$or': [
                {'memberList': {'$all': [uid, q]}},
                {'invitedList': {'$all': [uid, q]}}
            ]
        }
        query = {
            "chatType": 0,
            '$or': [
                {"$and": [
                    {"memberList": uid},
                    {"invitedList": q}
                ]},
                {"$and": [
                    {"memberList": q},
                    {"invitedList": uid}
                ]},
                {"memberList": [q, uid]}
            ]
        }
        req = await table.find_one(query)
        if req != None:
            r = Base.Answer({
                "threadList": [
                    await Chat.Info(req['id'], db, trigger_uid=uid)
                ]
            })

            await db.close()
            return r
        else:
            return Errors.MythicData(timestamp()-t1)
    elif type == "exist-multi":
        return Base.Answer({
            "threadList": [],
            "playlistInThreadList": {}
        }, spent_time=timestamp()-t1)
    elif type == "joined-me" or (start and size):
        size = size if 0 > size > 101 else 25 

        db = await Database().init()
        table = await db.get(database="x0", table="Chats")
        joined = await table.find({"memberList": uid}).distinct("id")
        invited = await table.find({"invitedList": uid}).distinct("id")
        row = (joined+invited)[start:start+size]

        info = Base.Answer({
            "threadList": [await Chat.Info(chatId, db, trigger_uid=uid) for chatId in row]
        }, spent_time=timestamp()-t1)

        await db.close()
        return info
    else:
        return Errors.InvalidRequest(timestamp()-t1)

# create chat
# /g/s/chat/thread

@chats.post("/g/s/chat/thread")
async def create_chat(request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    data = await request.json()
    trigger_uid = request.state.session['uid']
    if data['type'] == 0 and (data.get('inviteeUids', []) == [] or len(data.get('inviteeUids', [])) != 1):
        return Errors.InvalidRequest(timestamp()-t1)
    
    if data['type'] == 1 and data.get('inviteeUids', []) == []:
        return Errors.InvalidRequest(timestamp()-t1)

    db = await Database().init()
    table = await db.get("x0", "Chats")

    if data['type'] == 0:
        query = {
            "chatType": 0,
            '$or': [
                {'memberList': {'$all': [trigger_uid]+data['inviteeUids']}},
                {'invitedList': {'$all': [trigger_uid]+data['inviteeUids']}}
            ]
        }
        req = await table.find_one(query)
    else:
        req = None

    if req != None:
        chatId = req['id']
        chatObj = req
    else:
        chatId = str(uuid4())
        if data['type'] == 2:
            bg = data.get("extensions", {}).get("bm", [None, None])[1]
            chatObj = ModelFabric.Construct(
                Community.Chats,
                chatType=data['type'],
                id = chatId,
                hostId = trigger_uid,
                invitedList = data.get('inviteeUids', []),
                memberList = [trigger_uid],
                background = bg if isinstance(bg, str) else "https://media.altamino.top/default-chat-room-background/10_00.png",
                title = data.get("title", "Unnamed chat"),
                description = data.get("content"),
                icon = data.get("icon")
            )
        else:
            chatObj = ModelFabric.Construct(
                Community.Chats,
                chatType=data['type'],
                id = chatId,
                hostId = trigger_uid,
                invitedList = data['inviteeUids'],
                memberList = [trigger_uid]
            )
    await table.insert_one(chatObj)

    lastMsgId = str(uuid4())
    messages = [
        ModelFabric.Construct(
            Community.Message,
            messageId=lastMsgId,
            authorId=trigger_uid,
            messageType=103
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
                content=data["initialMessageContent"]
            )
        )
    
    g_users, xndc_users = await db.get(table="Users"), await db.get("x0", "Users")
    history = await db.get("x0", f"_Chat:{chatId}")
    await history.insert_many(messages)
    await table.update_one({"id": chatId, "$set": {"lastMessageId": lastMsgId}})

    chatInfo_obj = await Chat.Info(chatId, db, trigger_uid=trigger_uid, g_users=g_users, xndc_users=xndc_users)
    messages_obj = [await Chat.LongMessage(message, chatId, g_users, xndc_users) for message in messages]

    await db.close()
    return Base.Answer({
        "thread": chatInfo_obj,
        "messageList": messages_obj
    }, spent_time=timestamp()-t1)

# get chat history
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message?pagingType=t&size=25

@chats.get("/g/s/chat/thread/{chatId}/message")
async def get_chat_messages(request: Request, chatId: str, size: int = 25, pageToken: str = None):
    t1 = timestamp()
    
    size = size if 0 > size > 101 else 25

    # parse page token
    if pageToken:
        try: start = int(b85decode(pageToken).decode())
        except: start = 0
    else: start = 0

    db = await Database().init()
    table = await db.get("x0", f"_Chat:{chatId}")
    messages = [item async for item in table.find().skip(start).limit(size).sort("timestamp", DESCENDING)]  
    g_users, xndc_users = await db.get(table="Users"), await db.get("x0", "Users")

    if len(messages) > 0:
        answer = Base.Answer({
            "messageList": [
                await Chat.LongMessage(message, chatId, g_users, xndc_users, history_table=table)
                for message in messages
            ],
            "paging": {
                "nextPageToken": b85encode(str(size+start).encode()).decode(),
                "prevPageToken": b85encode(("0" if start - size <= 0 else str(start-size)).encode()).decode()
            }
        }, spent_time=timestamp()-t1)
        await db.close()
        return answer
    else:
        await db.close()
        return Base.Answer({
            "messageList": [],
            "paging": {}
        }, spent_time=timestamp()-t1)

# send message
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message

@chats.post("/g/s/chat/thread/{chatId}/message")
async def send_message(request: Request, chatId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    data = await request.json()
    trigger_uid = request.state.session['uid']

    try:
        if ( 
            # [info] types in messagetypes.json
            data['type'] not in [0, 2, 3]
        ) or (
            data.get('mediaType') and data['mediaType'] != 113 and (
                not data.get('mediaUploadValue')
            )
        ) or (
            data.get('mediaType', 0) == 100
            and (
                not data.get('mediaUploadValueContentType', '').startswith("image")
                or data['type'] != 0
            )
        ) or (
            data.get('mediaType', 0) == 110
            and data['type'] != 2
        ) or (
            data['type'] != 0 and data.get('content') != None
        )  or (
            data['type'] == 3 and ( 
                not isinstance(data.get("stickerId"), str)
                or not data['stickerId'].startswith("e/")
            )
        ) or (
            data['type'] == 0
            and data.get('mediaType', 0) == 0
            and not isinstance(data.get('content'), str)
        ):
            raise Exception()
    except:
        return Errors.InvalidMessage(timestamp()-t1)

    db = await Database().init()
    chat = await db.get("x0", f"Chats")
    chat_info = (await chat.find_one({"id": chatId}))

    staff = [chat_info['hostId']] + chat_info['cohostsIds']
    if chat_info['isViewMode'] and trigger_uid not in staff:
        await db.close()
        return Errors.ViewModeEnabled(timestamp()-t1)

    if trigger_uid not in chat_info['memberList']:
        await db.close()
        return Errors.UserNotJoined(timestamp()-t1)
    
    if data.get('content'):
        if len(data['content']) > Config.MAX_TEXT_SIZE:
            await db.close()
            return Errors.BigMessage(timestamp()-t1)
        
    extensions = data.get("extensions", {})
    
    if data.get('mediaUploadValue'):
        try:
            if len(data.get("mediaUploadValue")) > Config.MAX_FILE_SIZE:
                await db.close()
                return Errors.BigMediaContent(timestamp()-t1)
            s3 = resource(
                service_name=Config.S3_SERVICE_NAME,
                aws_access_key_id=Config.S3_ACCESS_KEY,
                aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
                endpoint_url=Config.S3_ENDPOINT_URL
            )
            if data['mediaType'] == 100:
                filetype_dict = {
                    "image/jpg": ".jpg",
                    "image/jpeg": ".jpeg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                    "image/gif": ".gif"
                }
                filetype = filetype_dict.get(data.get('mediaUploadValueContentType'), "")
                if filetype == "":
                    return Errors.InvalidMediaContent(spent_time=timestamp()-t1)
                filename = ''.join([choice(ascii_letters+digits) for _ in range(64)])+filetype
                body = ImageTools.compress(b64decode(data['mediaUploadValue']), filetype[1:])
                s3.Bucket(Config.S3_BUCKET_NAME).put_object(
                    Key = filename,
                    Body = body
                )
                mediaLink = Config.MEDIA_BASE_URL + filename
            elif data['mediaType'] == 110:
                filename = ''.join([choice(ascii_letters+digits) for _ in range(64)])+".aac"
                extensions = extensions | {"duration": 0.00}
                s3.Bucket(Config.S3_BUCKET_NAME).put_object(
                    Key = filename,
                    Body = b64decode(data['mediaUploadValue'])
                )
                mediaLink = Config.MEDIA_BASE_URL + filename
            else:
                mediaLink = None
        except Exception as e:
            print(e)
            await db.close()
            return Errors.InvalidMessage(timestamp()-t1)
    else:
        mediaLink = None

    if data.get("extensions", {}).get("linkSnippetList") and len(data["extensions"]["linkSnippetList"]) >= 1:
        linksnippet = data["extensions"]["linkSnippetList"][0]
        s3 = resource(
            service_name=Config.S3_SERVICE_NAME,
            aws_access_key_id=Config.S3_ACCESS_KEY,
            aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
            endpoint_url=Config.S3_ENDPOINT_URL
        )
        filetype_dict = {
            "image/jpg": ".jpg",
            "image/jpeg": ".jpeg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif"
        }
        filetype = filetype_dict.get(linksnippet.get('mediaUploadValueContentType'), "")
        if filetype == "":
            return Errors.InvalidMediaContent(spent_time=timestamp()-t1)
        filename = ''.join([choice(ascii_letters+digits) for _ in range(64)])+filetype
        body = ImageTools.compress(b64decode(linksnippet['mediaUploadValue']), filetype[1:])
        s3.Bucket(Config.S3_BUCKET_NAME).put_object(
            Key = filename,
            Body = body
        )
        mediaLink = Config.MEDIA_BASE_URL + filename
        del data['extensions']['linkSnippetList']
        data['extensions']['linkSnippetList'] = [
            {
                "body": None,
                "title": None,
                "favicon": None,
                "source": None,
                "link": linksnippet['link'],
                "deepLink": None,
                "mediaList": [
                    [
                        100,
                        mediaLink,
                        None
                    ]
                ]
            }
        ]

    if data.get("replyMessageId"):
        extensions.update({"replyMessageId": data["replyMessageId"]})

    if data.get("stickerId") and data['stickerId'].startswith("e/"):
        extensions.update(Chat.InternalSticker(data['stickerId'][2:]))
        data['mediaType'] = 113
        mediaLink = f"ndcsticker://{data['stickerId']}"

    messageId = str(uuid4())
    g_users, xndc_users = await db.get(table="Users"), await db.get("x0", "Users")
    table = await db.get("x0", f"_Chat:{chatId}")
    message = ModelFabric.Construct(
        Community.Message,
        messageId = messageId,
        authorId = trigger_uid,
        messageType = data['type'],
        clientRefId = data.get('clientRefId', 0),
        content = data.get('content'),
        extensions = extensions,
        mediaType = data.get("mediaType", 0),
        mediaValue = mediaLink
    )
    await table.insert_one( message )
    await chat.update_one(
        {'id': chatId},
        { "$set":  { 'lastMessageId': messageId } }
    )

    messageObj = await Chat.LongMessage(message, chatId, g_users, xndc_users)
    answer = Base.Answer({
        "message": messageObj
    }, spent_time=timestamp()-t1)

    ws_send_obj = {
        "t": 1000,
        "o": {   
            "ndcId": 0,
            "chatMessage": messageObj,
            "alertOption": 1,
            "membershipStatus": 1
        }
    }
    asyncio.get_event_loop().create_task(send_admin_ws(chat_info['memberList'], ws_send_obj))

    await db.close()
    return answer

# delete message
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/message/3c10a84c-c9af-4ab1-84fe-ea0c8d5f2f0f

@chats.delete("/g/s/chat/thread/{chatId}/message/{messageId}")
async def delete_message(request: Request, chatId: str, messageId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    trigger_uid = request.state.session['uid']
    work = False

    db = await Database().init()
    table = await db.get("x0", f"_Chat:{chatId}")
    original_message = await table.find_one({"messageId": messageId})
    if original_message['authorId'] != trigger_uid:
        chat = await db.get("x0", f"Chats")
        chat_info = await chat.find_one({'id': chatId})
        if trigger_uid not in chat_info['cohostsIds'] and trigger_uid != chat_info['hostId']:
            return Errors.InvalidRequest(timestamp()-t1)
        else:
            work = True
        if chat_info['chatType'] == [0,1]:
            work = True
    else:
        work = True

    if work:
        await table.update_one(
            {"messageId": messageId},
            {"$set": {"content": None, "messageType": 100}}
        )

    await db.close()
    return Base.Answer(spent_time=timestamp()-t1)

# get chat members
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/member?type=default&start=0&size=40

@chats.get("/g/s/chat/thread/{chatId}/member")
async def get_chat_members(request: Request, chatId: str, type: str = "default", start: int = 0, size: int = 25):
    t1 = timestamp()
        
    if type not in ['default', 'co-host']:
        return Errors.InvalidRequest(timestamp()-t1)

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = (await chat.find_one({"id": chatId}))
    g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")
    if type == "default":
        members = chat_info['memberList']
        invited = chat_info['invitedList']
        all_members = (members + invited)[start:start+size]

        answer = Base.Answer({
            "memberList":
                [await Chat.GetMemberInfo(member, g_users, xndc_users, True if member in members else False) for member in all_members]
        }, spent_time=timestamp()-t1)
    elif type == "co-host":
        members = chat_info['memberList']
        co_hosts = chat_info['cohostsIds']

        non_cohosts = []
        for i in members+co_hosts:
            if i in members and i in co_hosts: continue
            non_cohosts.append(i)
        non_cohosts = non_cohosts[start:start+size]
        g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")

        answer = Base.Answer({
            "memberList":
                [await Chat.GetMemberInfo(member, g_users, xndc_users, True) for member in non_cohosts]
        }, spent_time=timestamp()-t1)
    else:
        answer = Errors.InvalidRequest(timestamp()-t1)

    await connection.close()
    return answer

# get cohosts
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host&start=0&size=40

@chats.get("/g/s/chat/thread/{chatId}/co-host")
async def get_chat_cohosts(request: Request, chatId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    trigger_uid = request.state.session['uid']

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = (await chat.find_one({"id": chatId}))
    if trigger_uid != chat_info['hostId']:
        await connection.close()
        return Errors.NotEnoughRights(timestamp()-t1) 
    
    members = chat_info['cohostsIds']
    g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")

    answer = Base.Answer({
        "userProfileList":
            [await Chat.GetMemberInfo(member, g_users, xndc_users, True) for member in members]
    }, spent_time=timestamp()-t1)
    await connection.close()
    return answer

# set cohosts
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host

@chats.post("/g/s/chat/thread/{chatId}/co-host")
async def set_cohosts(request: Request, chatId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    data = await request.json()
    trigger_uid = request.state.session['uid']
    cohosts = data.get('uidList', [])

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = (await chat.find_one({"id": chatId}))
    if trigger_uid != chat_info['hostId']:
        await connection.close()
        return Errors.NotEnoughRights(timestamp()-t1) 

    g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")
    answer = Base.Answer({
        "userProfileList":
            [await Chat.GetMemberInfo(member, g_users, xndc_users, True) for member in cohosts]
    }, spent_time=timestamp()-t1)
    
    await chat.update_one(
        {"id": chatId},
        {'$push': {'cohostsIds': {'$each': cohosts}}}
    )

    await connection.close()
    return answer

# remove cohost
# [delete] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/co-host/010a4dd5-290f-404d-a671-a7048199d83f

@chats.delete("/g/s/chat/thread/{chatId}/co-host/{uid}")
async def set_cohosts(request: Request, chatId: str, uid: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    trigger_uid = request.state.session['uid']

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = (await chat.find_one({"id": chatId}))
    if trigger_uid != chat_info['hostId']:
        await connection.close()
        return Errors.NotEnoughRights(timestamp()-t1) 
    
    await chat.update_one(
        {"id": chatId},
        {'$pull': {'cohostsIds': uid}}
    )

    chat_info = (await chat.find_one({"id": chatId}))
    cohosts = chat_info['cohostsIds']
    g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")
    answer = Base.Answer({
        "userProfileList":
            [await Chat.GetMemberInfo(member, g_users, xndc_users, True) for member in cohosts]
    }, spent_time=timestamp()-t1)
    
    await connection.close()
    return answer

# invite to chat
# /g/s/chat/thread/9978643e-5fa5-4b0b-82a4-70a5c71e32b1/member/invite

@chats.post("/g/s/chat/thread/{chatId}/member/invite")
async def join_chat(request: Request, chatId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    data = await request.json()
    uid = request.state.session['uid']
    toInvite = data.get('uids', [])

    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp()-t1)

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = await chat.find_one({'id': chatId})
    staff = [chat_info['hostId']] + chat_info['cohostsId']
    if uid not in staff or uid not in chat_info['memberList']:
        if not data['canMembersInvite']:
            await connection.close()
            return Errors.NotEnoughRights(timestamp()-t1)
    
    actuallyInvite = []
    for member in toInvite:
        if member in chat_info['bannedUids'] and uid != chat_info['hostId']: 
            continue
        if member in chat_info['invitedList'] or member in chat_info['memberList']:
            continue
        actuallyInvite.append(member)

    await chat.update_one(
        {'id': chatId},
        { '$push': { 'invitedList': {'$each': actuallyInvite}}}
    )

    await connection.close()
    return Base.Answer(timestamp()-t1)

# join chat
# /g/s/chat/thread/a8b4942e-58e7-4699-957c-6dde40f2f5e8/member/9b1ef6f0-707c-4bc2-979f-a5650109a6c0

@chats.post("/g/s/chat/thread/{chatId}/member/{userId}")
async def join_chat(request: Request, chatId: str, userId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    uid = request.state.session['uid']
    
    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp()-t1)

    if userId != uid:
        return Errors.InvalidRequest(timestamp()-t1)

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = await chat.find_one({'id': chatId})
    if userId in chat_info['memberList']:
        await connection.close()
        return Base.Answer({"membershipStatus": 1}, timestamp()-t1)
    if userId in chat_info['bannedUids']:
        await connection.close()
        return Errors.RemovedFromChat(timestamp()-t1)
    
    messageId = str(uuid4())

    await chat.update_one(
        {'id': chatId},
        {
            '$push': { 'memberList': userId },
            '$pull': { 'invitedList': userId },
            "$set":  { 'lastMessageId': messageId }
        }
    )

    table = await connection.get("x0", f"_Chat:{chatId}")
    message = ModelFabric.Construct(
        Community.Message,
        messageId = messageId,
        authorId = userId,
        messageType = 101,
        clientRefId = 0,
        content = None
    )
    await table.insert_one(
        message
    )
    g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")
    messageObj = await Chat.LongMessage(message, chatId, g_users, xndc_users)
    ws_send_obj = {
        "t": 1000,
        "o": {   
            "ndcId": 0,
            "chatMessage": messageObj,
            "alertOption": 1,
            "membershipStatus": 1
        }
    }
    asyncio.get_event_loop().create_task(send_admin_ws(chat_info['memberList'], ws_send_obj))

    await connection.close()
    return Base.Answer({"membershipStatus": 1}, timestamp()-t1)

# leave chat
# /g/s/chat/thread/a8b4942e-58e7-4699-957c-6dde40f2f5e8/member/9b1ef6f0-707c-4bc2-979f-a5650109a6c0

@chats.delete("/g/s/chat/thread/{chatId}/member/{userId}")
async def leave_chat(request: Request, chatId: str, userId: str, allowRejoin: int = 0):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    uid = request.state.session['uid']
    messageId = str(uuid4())
    work = False
    ban = False

    if uid in [None, "", False]:
        return Errors.InvalidSession(timestamp()-t1)

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    chat_info = await chat.find_one({'id': chatId})

    if userId == uid:
        print("user leaving")
        work = True

    if userId != uid:
        print("user not leaving, its kick")
        if userId == chat_info['hostId']:
            await connection.close()
            return Errors.NotEnoughRights(timestamp()-t1)
        elif uid not in chat_info['cohostsIds'] and uid != chat_info['hostId']:
            await connection.close()
            return Errors.NotEnoughRights(timestamp()-t1)
        else:
            work = True

    if allowRejoin != 1:
        print("allow rejoin obviously not 1")
        if uid in chat_info['cohostsIds'] or uid == chat_info['hostId']:
            print("ok you have rights")
            ban = True
        else:
            print("haha you havent rights")
            ban = False
    if ban == True and userId == uid:
        print("ok ban urself is bad")
        ban = False

    if work:
        table = await connection.get("x0", f"_Chat:{chatId}")
        message = ModelFabric.Construct(
            Community.Message,
            messageId = messageId,
            authorId = userId,
            messageType = 102,
            clientRefId = 0,
            content = None
        )
        await table.insert_one(
            message
        )

        isBan = {'$push': { 'bannedUids': userId }} if ban else {}
        await chat.update_one(
            {'id': chatId},
            {
                '$pull': { 'memberList': userId, 'invitedList': userId },
                "$set":  { 'lastMessageId': messageId }
            } | isBan
        )

        g_users, xndc_users = await connection.get(table="Users"), await connection.get("x0", "Users")
        messageObj = await Chat.LongMessage(message, chatId, g_users, xndc_users)
        ws_send_obj = {
            "t": 1000,
            "o": {   
                "ndcId": 0,
                "chatMessage": messageObj,
                "alertOption": 1,
                "membershipStatus": 1
            }
        }
        asyncio.get_event_loop().create_task(send_admin_ws(chat_info['memberList'], ws_send_obj))
    
    await connection.close()
    return Base.Answer({"membershipStatus": 0}, spent_time=timestamp()-t1)

# mark chat as read
# /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/mark-as-read

@chats.post("/g/s/chat/thread/{chatId}/mark-as-read")
async def mark_as_read(request: Request, chatId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    uid = request.state.session['uid']
    
    try:
        data = await request.json()
        if ( 
            not data.get('messageId') or not data.get("createdTime")
        ):
            raise Exception()
    except:
        return Errors.InvalidMessage(timestamp()-t1)

    connection = await Database().init()
    chat = await connection.get("x0", f"Chats")
    history = await connection.get("x0", f"_Chat:{chatId}")
    if await history.find_one({'messageId': data['messageId']}):
        readTimestamp = datetime.fromtimestamp(data['timestamp']/1000.0).strftime("%Y-%m-%dT%H:%M:%SZ")
        await chat.update_one(
            {"id": chatId},
            {"$set": { f"lastReadedList.{uid}": readTimestamp }}
        )
        
        await connection.close()
        return Base.Answer({
            "lastReadTime": readTimestamp
        }, spent_time=timestamp()-t1)
    
    await connection.close()
    return Errors.DataNotExist(spent_time=timestamp()-t1)

# toggle things
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/view-only/enable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/view-only/disable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/members-can-invite/enable
# [POST] /g/s/chat/thread/434cd5b4-a984-42c4-8375-46c1c6e0803d/members-can-invite/disable

@chats.post("/g/s/chat/thread/{chatId}/{parameter}/{mode}")
async def toggle_things(chatId: str, mode: str, parameter: str, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    if mode not in ['disable', 'enable']:
        return Errors.InvalidRequest(timestamp()-t1)
    if parameter not in ['members-can-invite', 'view-only']:
        return Errors.InvalidRequest(timestamp()-t1)

    trigger_uid = request.state.session['uid']
    
    db = await Database().init()
    table = await db.get("x0", "Chats")
    chat_info = await table.find_one({"id": chatId})
    
    if chat_info['hostId'] == trigger_uid or trigger_uid in chat_info['cohostsIds']:
        if parameter == "view-only":
            await table.update_one(
                {"id": chatId},
                {"$set": {"isViewMode": True if mode == "enable" else False}}
            )

            history = await db.get("x0", f"_Chat:{chatId}")
            messageId = str(uuid4())
            message = ModelFabric.Construct(
                Community.Message,
                messageId = messageId,
                authorId = trigger_uid,
                messageType = 125 if mode == "enable" else 126
            )
            await history.insert_one( message )
            await table.update_one(
                {'id': chatId},
                { "$set":  { 'lastMessageId': messageId } }
            )

            g_users, xndc_users = await db.get(table="Users"), await db.get("x0", "Users")
            messageObj = await Chat.LongMessage(message, chatId, g_users, xndc_users)
            ws_send_obj = {
                "t": 1000,
                "o": {   
                    "ndcId": 0,
                    "chatMessage": messageObj,
                    "alertOption": 1,
                    "membershipStatus": 1
                }
            }
            asyncio.get_event_loop().create_task(send_admin_ws(chat_info['memberList'], ws_send_obj))
        elif parameter == "members-can-invite":
            await table.update_one(
                {"id": chatId},
                {"$set": {"canMembersInvite": True if mode == "enable" else False}}
            )

        await db.close()
        return Base.Answer(spent_time=timestamp()-t1)
    
    else:
        await db.close()
        return Errors.NotEnoughRights(timestamp()-t1)
