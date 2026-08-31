from datetime import UTC, datetime
from typing import Union

# import sys
# sys.path.append('../')
from helpers.database.mongo import Database
from helpers.store import build_chat_bubble_object
from services.store import StoreService
from .user import User


class Chat:
    BoilerplateMessage = {
        "messageId": "00000000-0000-0000-0000-000000000",
        "authorId": "00000000-0000-0000-0000-000000000",
        "messageType": 100,
        "clientRefId": 0,
        "content": "",
        "mediaType": 0,
        "mediaValue": None,
        "timestamp": 0,
        "createdTime": "1970-01-01T00:00:00Z",
        "extensions": {"mentionedArray": []},
    }

    @staticmethod
    async def GetMemberInfo(
        memberId: str, xndc_users, membershipStatus: bool = True, ndcId: int = 0
    ):
        xndc_data = await xndc_users.find_one({"id": memberId}) or {}
        async with await StoreService.create(memberId, ndcId) as svc:
            xndc_data["iconFrame"] = await svc.frame_icon(xndc_data.get("frameId"))
        return User.GetUserInfo(
            xndc_data, membershipStatus=1 if membershipStatus else 2, ndcId=ndcId
        )

    @staticmethod
    def Member_ShortInfo(
        data: dict,
        role: Union[int, None] = None,
        is_invited: bool = False,
        ndcId: int = 0,
    ):
        return {
            "status": data["status"],
            "uid": data["id"],
            "ndcId": ndcId,
            "isGlobal": ndcId == 0,
            "membershipStatus": int(is_invited),
            "role": role or data.get("role", 0),
            "nickname": data["nickname"],
            "icon": data["icon"],
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
                "icon": f"ndcsticker://e/{sticker_id}",
            },
            "originalStickerId": f"e/{sticker_id}",
        }

    @staticmethod
    async def LongMessage(
        data: dict,
        threadId: str,
        xndc_users,
        ndcId: int = 0,
        mentionedArray: list = [],
        history_table=None,
        chatBubbleVersion=None,
        chatBubbleId=None,
        global_user=None
    ):
        extensions = data.get("extensions", {})
        if extensions is None:
            extensions = {}

        if extensions.get("replyMessageId"):
            if history_table is None:
                con = await Database().init()
                history_table = con.get(f"x{ndcId}", f"_Chat:{threadId}")

            reply_msg_data = await history_table.find_one(
                {"messageId": extensions["replyMessageId"]}
            )
            if reply_msg_data:
                extensions.update(
                    {
                        "replyMessage": await Chat.LongMessage(
                            reply_msg_data,
                            threadId,
                            xndc_users,
                            ndcId=ndcId,
                            history_table=history_table,
                        )
                    }
                )

        xndc_data = await xndc_users.find_one({"id": data["authorId"]}) or {}

        if global_user is not None:
            global_row = await global_user.find_one({"id": data["authorId"]})
            xndc_data["tagList"] = list(
                set(global_row.get("tagList", []) + xndc_data.get("tagList", []))
            )

            xndc_data["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)

            if "isTeamMember" in global_row:
                xndc_data["isTeamMember"] = global_row["isTeamMember"]

            if "isVerified" in global_row:
                xndc_data["isVerified"] = global_row["isVerified"]
            if global_row.get("status", 0) in [9, 10]:
                xndc_data["status"] = global_row["status"]
            if global_row.get("extensions", {}).get("__disabledLevel__"):
                xndc_data["extensions"]["__disabledLevel__"] = global_row["extensions"][
                    "__disabledLevel__"
                ]



        async with await StoreService.create(data["authorId"], ndcId) as svc:
            xndc_data["iconFrame"] = await svc.frame_icon(xndc_data.get("frameId"))






        result = {
            "includedInSummary": True,
            "uid": data["authorId"],
            "author": User.GetUserInfo(xndc_data, ndcId=ndcId),
            "isHidden": False,
            "messageId": data["messageId"],
            "mediaType": data.get("mediaType", 0),
            "content": data["content"],
            "clientRefId": data.get("clientRefId", 0),
            "threadId": threadId,
            "ndcId": ndcId,
            "createdTime": data["createdTime"],
            "extensions": {"mentionedArray": mentionedArray} | extensions,
            "type": data["messageType"],
            "mediaValue": data.get("mediaValue"),
        }

        if chatBubbleId:
            result["chatBubbleId"] = chatBubbleId
            result["chatBubbleVersion"] = chatBubbleVersion or 1


        return result

    @staticmethod
    def ShortMessage(data: dict):
        return {
            "uid": data["authorId"],
            "type": data["messageType"],
            "mediaType": data.get("mediaType", 0),
            "content": data["content"],
            "messageId": data["messageId"],
            "createdTime": data["createdTime"],
            "isHidden": False,
            "mediaValue": data.get("mediaValue"),
        }

    @staticmethod
    async def resolve_chat_bubbles(
        db, ndc_id: int, chat_id: str, member_uids: list[str]
    ) -> dict:
        if not member_uids:
            return {}

        try:
            users_col = db.get(f"x{ndc_id}", "Users")
            docs = await users_col.find(
                {"id": {"$in": member_uids}},
                {"_id": 0, "id": 1, f"chatBubbles.{chat_id}": 1, "bubbleId": 1},
            ).to_list(length=None)

            uid_to_bid = {}
            for u in docs:
                bid = (u.get("chatBubbles") or {}).get(chat_id) or u.get("bubbleId")
                if bid:
                    uid_to_bid[u["id"]] = bid

            if not uid_to_bid:
                return {}

            bubbles_col = db.get(table="ChatBubbles")
            bubble_docs = await bubbles_col.find(
                {"bubbleId": {"$in": list(set(uid_to_bid.values()))}},
                {"_id": 0},
            ).to_list(length=None)
            bubbles_by_id = {
                b["bubbleId"]: build_chat_bubble_object(b) for b in bubble_docs
            }

            return {
                uid: bubbles_by_id[bid]
                for uid, bid in uid_to_bid.items()
                if bid in bubbles_by_id
            }
        except Exception as e:
            print(e)
            return {}

    @staticmethod
    async def Info(
        chatId: str | dict,
        connection=None,
        ndcId: int = 0,
        trigger_uid: Union[str, None] = None,
        xndc_users=None,
    ):
        if not connection:
            connection = await Database().init()

        if isinstance(chatId, str):
            chats = connection.get(f"x{ndcId}", "Chats")
            data = await chats.find_one({"id": chatId})
        else:
            data = chatId
            chatId = data.get("id")

        if data is None:
            return (
                None  # because /s/live-layer/public-chats returns error on custom apis
            )

        try:
            messages = connection.get(f"x{ndcId}", f"_Chat:{chatId}")
            message = await messages.find_one({"messageId": data["lastMessageId"]})
            if message is None:
                message = Chat.BoilerplateMessage
        except Exception as e:
            message = Chat.BoilerplateMessage
            print("Can't get message for chat:", e)

        if xndc_users is not None:
            host_xndcId = await xndc_users.find_one({"id": data["hostId"]}) or {}
        else:
            xndc_users = connection.get(f"x{ndcId}", "Users")
            host_xndcId = await xndc_users.find_one({"id": data["hostId"]}) or {}

        if host_xndcId:
            async with await StoreService.create(data["hostId"], ndcId) as svc:
                host_xndcId["iconFrame"] = await svc.frame_icon(
                    host_xndcId.get("frameId")
                )

        membershipStatus = 0
        if trigger_uid in data["memberList"]:
            membershipStatus = 1
        elif trigger_uid in data["invitedList"]:
            membershipStatus = 2
        alert_options = data.get("alertOptions", {})
        return {
            "userAddedTopicList": [],
            "uid": data["hostId"],
            "chatBubbles": await Chat.resolve_chat_bubbles(
                connection, ndcId, chatId, data["memberList"]
            ),
            "membersQuota": 9999,
            "membersSummary": [
                Chat.Member_ShortInfo(i, ndcId=ndcId)
                async for i in xndc_users.find(
                    {"id": {"$in": data["memberList"]}}
                ).limit(10)
            ],
            "threadId": data["id"],
            "keywords": None,
            "membersCount": len(data["memberList"] + data["invitedList"]),
            "strategyInfo": "{}",
            "isPinned": False,
            "title": data.get("title"),
            "tipInfo": data.get(
                "tipInfo",
                {
                    "tipOptionList": [
                        {
                            "value": 2,
                            "icon": "https://media.altamino.top/monetization/coins.png",
                        },
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
                },
            ),
            "membershipStatus": membershipStatus,
            "content": data.get("description"),
            "needHidden": False,
            "alertOption": alert_options.get(trigger_uid, 1),
            "lastReadTime": data["lastReadedList"].get(
                trigger_uid,
                datetime.fromtimestamp(0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            "type": data["chatType"],
            "status": data["status"],
            "modifiedTime": data["modifiedTime"],
            "lastMessageSummary": Chat.ShortMessage(message),
            "condition": 1 if data["chatType"] == 2 else 0,
            "icon": data.get("icon"),
            "latestActivityTime": message["createdTime"],
            "author": User.GetUserInfo(host_xndcId, ndcId=ndcId),
            "extensions": {
                "viewOnly": data.get("isViewMode", False),
                "coHost": data["cohostsIds"],
                "language": "en",
                "membersCanInvite": data["canMembersInvite"],
                "screeningRoomPermission": {"action": 2},
                "bm": [100, data["background"], None, None, None, {}],
                "bannedMemberUidList": data["bannedUids"],
                "visibility": 2,
                "lastMembersSummaryUpdateTime": 1703655999,
                "fansOnly": False,
                "vvChatJoinType": 1,
                "channelType": data.get("channelType", 0),
                "announcement": data["announcement"],
                "pinAnnouncement": data["pinAnnouncement"],
            },
            "ndcId": ndcId,
            "isGlobal": ndcId == 0,
            "createdTime": data["createdTime"],
        }
