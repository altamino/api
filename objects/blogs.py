from typing import Union

from .medialist import MediaList
from .user import User
from services.store import StoreService


class Blog:
    @staticmethod
    def PollOption(data: dict, uid: str):
        return {
            "title": data["title"],
            "status": data.get("status", 0),
            "mediaList": data.get("mediaList", []),
            "votesSum": len(data.get("voted", [])),
            "votedValue": int(uid in data.get("voted", [])),
            "votesCount": len(data.get("voted", [])),
            "globalVotedValue": 0,
            "globalVotedCount": 0,
            "type": 0,
            "parentType": 0,
            "refObjectType": 0,
        }

    @staticmethod
    async def Info(
        blogId: str | dict,
        connection,
        ndcId: int = 0,
        trigger_uid: Union[str, None] = None,
        xndc_users=None,
    ):
        if isinstance(blogId, str):
            blogs = connection.get(f"x{ndcId}", "Blogs")
            data = await blogs.find_one({"id": blogId})
        else:
            data = blogId

        if xndc_users is not None:
            author_data = await xndc_users.find_one({"id": data["authorId"]}) or {}
        else:
            xndc_users = connection.get(f"x{ndcId}", "Users")
            author_data = await xndc_users.find_one({"id": data["authorId"]}) or {}

        comments = connection.get(f"x{ndcId}", "Comments")
        commentsCount = await comments.count_documents({"rootId": f"blog:{data['id']}"})

        if author_data:
            async with await StoreService.create(data["authorId"], ndcId) as svc:
                author_data["iconFrame"] = await svc.frame_icon(
                    author_data.get("frameId")
                )

        if data["blogType"] == 2:
            base = {
                "itemId": data["id"],
                "label": data.get("title"),
            }
        else:
            base = {
                "blogId": data["id"],
                "title": data.get("title"),
            }

        extensions = data.get("extensions", {})
        return base | {
            "author": User.GetUserInfo(
                author_data, ndcId=ndcId, triggerUserId=trigger_uid
            ),
            "content": data.get("content"),
            "type": data["blogType"],
            "status": data.get("status", 0),
            "votesCount": len(data.get("upvote", [])) - len(data.get("downvote", [])),
            "commentsCount": commentsCount,
            "ndcId": ndcId,
            "createdTime": data["createdTime"],
            "modifiedTime": data["modifiedTime"],
            "extensions": {
                "featuredType": data.get("featuredType", 0),
                "privilegeOfCommentOnPost": data.get("commentAllowance", 1),
                "pollSettings": {"polloptType": 0, "joinEnabled": False},
                "props": data.get("props", []),
            }
            | extensions,
            "mediaList": MediaList.List(data.get("mediaList", [])),
            "votedValue": (
                4
                if trigger_uid in data.get("upvote", [])
                else -1
                if trigger_uid in data.get("downvote", [])
                else 0
            ),
            "keywords": data.get("keywords"),
            "viewCount": 0,
            "timestamp": data.get("pollTimestamp"),
            "durationInDays": data.get("pollDuration"),
            "polloptList": [
                Blog.PollOption(item, trigger_uid) for item in data["pollOptions"]
            ]
            if "pollOptions" in data
            else None,
            "tipInfo": data.get(
                "tipInfo",
                {
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
        }
