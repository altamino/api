from .user import User
from typing import Union
from datetime import datetime

#import sys
#sys.path.append('../')
from helpers.database.mongo import Database

class Chat:
    @staticmethod
    async def GetMemberInfo(memberId: str, g_users, xndc_users, membershipStatus: bool = True):
        return User.GetUserInfo(
            await g_users.find_one({"id": memberId})|await xndc_users.find_one({"id": memberId}),
            membershipStatus=1 if membershipStatus else 2
        )

    @staticmethod
    def Member_ShortInfo(data: dict, role: Union[int, None] = None, is_invited: bool = False):
        return {
            "status": data['status'],
            "uid": data['id'],
            "membershipStatus": int(is_invited),
            "role": role or data.get('role', 0),
            "nickname": data['nickname'],
            "icon": data['icon']
        }
    
    @staticmethod
    def InternalSticker(sticker_id: str):
        return {
            "sticker": {
                "status": 0,
                "iconV2": f"ndcsticker://e/{sticker_id}",
                "name": None,
                "stickerId": f"e/{sticker_id}",
                "smallIconV2": None,
                "smallIcon": None,
                "stickerCollectionId": None,
                "mediumIcon": None,
                "extensions": None,
                "usedCount": 0,
                "mediumIconV2": None,
                "createdTime": None,
                "icon": f"ndcsticker://e/{sticker_id}"
            },
            "originalStickerId": f"e/{sticker_id}"
        }

    @staticmethod
    async def LongMessage(data: dict, threadId: str, g_users, xndc_users, mentionedArray: list = [], history_table = None):
        extensions = data.get("extensions", {})
        if extensions == None: extensions = {}

        if extensions.get("replyMessageId"):
            if history_table == None:
                con = await Database().init()
                history_table = await con.get("x0", f"_Chat:{threadId}")
            extensions.update({
                "replyMessage": await Chat.LongMessage(
                    await history_table.find_one({"messageId": extensions['replyMessageId']}),
                    threadId, g_users, xndc_users, history_table=history_table
                )
            })

        return {
            "includedInSummary": True,
            "uid": data['authorId'],
            "author": User.GetUserInfo(await g_users.find_one({"id": data['authorId']}) | await xndc_users.find_one({"id": data['authorId']})),
            "isHidden": False,
            "messageId": data['messageId'],
            "mediaType": data.get('mediaType', 0),
            "content": data['content'],
            "clientRefId": data.get("clientRefId", 0),
            "threadId": threadId,
            "createdTime": data['createdTime'],
            "extensions": {
                "mentionedArray": mentionedArray
            } | extensions,
            "type": data['messageType'],
            "mediaValue": data.get('mediaValue')
        }    
    
    @staticmethod
    def ShortMessage(data: dict):
        return {
            "uid": data['authorId'],
            "type": data['messageType'],
            "mediaType": data.get('mediaType', 0),
            "content": data['content'],
            "messageId": data['messageId'],
            "createdTime": data['createdTime'],
            "isHidden": False,
            "mediaValue": data.get('mediaValue')
        }
    
    @staticmethod
    async def Info(chatId: str, connection = None, ndcId: int = 0, trigger_uid: Union[str, None] = None, g_users = None, xndc_users = None):
        if not connection:
            connection = await Database().init()
        chats = await connection.get(f"x{ndcId}", "Chats")
        data = await chats.find_one({"id": chatId})
        
        messages = await connection.get(f"x{ndcId}", f"_Chat:{data['id']}")
        message = await messages.find_one({"messageId": data['lastMessageId']})
        if message == None:
            message = {
                "messageId": "00000000-0000-0000-0000-000000000",
                "authorId": "00000000-0000-0000-0000-000000000",
                "messageType": 100,
                "clientRefId": 0,
                "content": "",
                "mediaType": 0,
                "mediaValue": None,
                "timestamp": 0,
                "createdTime": "1970-01-01T00:00:00Z",
                "extensions": {
                    "mentionedArray": []
                }
            }
            
        if g_users != None:
            users = g_users
            host_global = await users.find_one({"id": data['hostId']})
        else:
            users = await connection.get(table="Users")
            host_global = await users.find_one({"id": data['hostId']})
        
        if xndc_users != None:
            users = xndc_users
            host_xndcId = await users.find_one({"id": data['hostId']})
        else:
            users = await connection.get(f"x{ndcId}", "Users")
            host_xndcId = await users.find_one({"id": data['hostId']})

        membershipStatus = 0
        if trigger_uid in data['memberList']:
            membershipStatus = 1
        elif trigger_uid in data['invitedList']:
            membershipStatus = 2

        return {
            "userAddedTopicList": [],
            "uid": data['hostId'],
            "chatBubbles": {},
            "membersQuota": 9999,
            "membersSummary": [
                Chat.Member_ShortInfo(i) async for i in users.find({"id": {"$in": data['memberList']}}).limit(10)
            ],
            "threadId": data['id'],
            "keywords": None,
            "membersCount": len(data['memberList']+data['invitedList']),
            "strategyInfo": "{}",
            "isPinned": False,
            "title": data.get('title'),
            "tipInfo": {
                "tipOptionList": [
                    {
                        "value": 2,
                        "icon": "https://media.altamino.top/monetization/coins.png"
                    },
                    {
                        "value": 10,
                        "icon": "https://media.altamino.top/monetization/stack_of_coins.png"
                    },
                    {
                        "value": 50,
                        "icon": "https://media.altamino.top/monetization/tall_stack_of_coins.png"
                    }
                ],
                "tipMaxCoin": 500,
                "tippersCount": 0,
                "tippable": False,
                "tipMinCoin": 1,
                "tipCustomOption": {
                    "value": None,
                    "icon": "https://media.altamino.top/monetization/bag_of_coins.png"
                },
                "tippedCoins": 0
            },
            "membershipStatus": membershipStatus,
            "content": data.get('description'),
            "needHidden": False,
            "alertOption": 1,
            "lastReadTime": data['lastReadedList'].get(trigger_uid, datetime.fromtimestamp(0).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "type": data['chatType'],
            "status": data['status'],
            "modifiedTime": data['modifiedTime'],
            "lastMessageSummary": Chat.ShortMessage(message),
            "condition": 1 if data['chatType'] == 2 else 0,
            "icon": data.get('icon'),
            "latestActivityTime": message['createdTime'],
            "author": User.GetUserInfo(host_global|host_xndcId),
            "extensions": {
                "viewOnly": data.get("isViewMode", False),
                "coHost": data['cohostsIds'],
                "language": "en",
                "membersCanInvite": data['canMembersInvite'],
                "screeningRoomPermission": {
                    "action": 2
                },
                "bm": [
                    100,
                    data['background'],
                    None,
                    None,
                    None,
                    {}
                ],
                "bannedMemberUidList": data['bannedUids'],
                "visibility": 2,
                "lastMembersSummaryUpdateTime": 1703655999,
                "fansOnly": False,
                "vvChatJoinType": 1,
                "announcement": data['announcement'],
                "pinAnnouncement": data['pinAnnouncement']
            },
            "ndcId": ndcId,
            "createdTime": data['createdTime']
        }
            