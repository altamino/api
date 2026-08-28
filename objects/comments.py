from .user import User
from .medialist import MediaList
from services.store import StoreService


class Comments:
    @staticmethod
    async def Parent(
        row,
        xndcid_users,
        itemId: str,
        itemType: int = 2,
        ndcId: int = 0,
        triggerUserId: str | None = None,
        subcommentsCount: int = 0,
        extensions: dict = {},
    ):
        upvotes = row.get("upvotes", [])
        downvotes = row.get("downvotes", [])

        votesSum = len(upvotes) - len(downvotes)
        voteValue = (
            1 if triggerUserId in upvotes else -1 if triggerUserId in downvotes else 0
        )

        author = await xndcid_users.find_one({"id": row["authorId"]}) or {}
        async with await StoreService.create(row["authorId"], ndcId) as svc:
            author["iconFrame"] = await svc.frame_icon(author.get("frameId"))

        return {
            "modifiedTime": row["modifiedTime"],
            "ndcId": ndcId,
            "votedValue": voteValue,
            "parentType": itemType,
            "commentId": row["commentId"],
            "parentNdcId": ndcId,
            "mediaList": MediaList.List(row.get("mediaList", [])),
            "votesSum": votesSum,
            "subcommentsPreview": [],
            "author": User.GetUserInfo(author, ndcId),
            "content": row["content"],
            "extensions": {} | extensions,
            "parentId": itemId,
            "createdTime": row["createdTime"],
            "subcommentsCount": subcommentsCount,
            "type": 0,
        }

    @staticmethod
    async def Son(
        row,
        xndcid_users,
        itemId: str,
        itemType: int = 2,
        ndcId: int = 0,
        triggerUserId: str | None = None,
        extensions: dict = {},
    ):
        upvotes = row.get("upvotes", [])
        downvotes = row.get("downvotes", [])

        votesSum = len(upvotes) - len(downvotes)
        voteValue = (
            1 if triggerUserId in upvotes else -1 if triggerUserId in downvotes else 0
        )

        author = await xndcid_users.find_one({"id": row["authorId"]}) or {}
        async with await StoreService.create(row["authorId"], ndcId) as svc:
            author["iconFrame"] = await svc.frame_icon(author.get("frameId"))

        return {
            "headCommentId": row.get("parentId"),
            "modifiedTime": row["modifiedTime"],
            "ndcId": ndcId,
            "votedValue": voteValue,
            "parentType": itemType,
            "commentId": row["commentId"],
            "parentNdcId": ndcId,
            "mediaList": MediaList.List(row.get("mediaList", [])),
            "votesSum": votesSum,
            "author": User.GetUserInfo(author, ndcId),
            "content": row["content"],
            "extensions": {} | extensions,
            "parentId": itemId,
            "createdTime": row["createdTime"],
            "subcommentsCount": 0,
            "type": 0,
        }
