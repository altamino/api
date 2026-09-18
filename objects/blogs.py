from typing import Union

from .medialist import MediaList
from .user import User
from services.store import StoreService


from datetime import datetime, timezone, timedelta

def compute_poll_end_time(data: dict) -> str | None:
    poll_timestamp = data.get("pollTimestamp") 
    poll_duration = data.get("pollDuration")
    if not poll_timestamp or not poll_duration:
        return None

    start = datetime.fromtimestamp(poll_timestamp / 1000, timezone.utc)
    end = start + timedelta(days=poll_duration)

    if end <= datetime.now(timezone.utc):
        return None

    return end.strftime("%Y-%m-%dT%H:%M:%SZ")


class Blog:
    @staticmethod
    def PollOption(data: dict, uid: str):
        return {
            "polloptId": data.get("polloptId"),
            "title": data["title"],
            "status": data.get("status", 0),
            "mediaList": data.get("mediaList", []),
            "votesSum": len(data.get("voted", [])),
            "votedValue": int(uid in data.get("voted", [])),
            "votesCount": len(data.get("voted", [])),
            "globalVotedValue": 0,
            "globalVotedCount": 0,
            "type": data.get("type", 0),
            "parentType": 0,
            "refObjectType": 0,
        }
    @staticmethod
    def QuizQuestion(data: dict, blog_id: str, can_see_answers: bool):
        opt_list = []
        for opt in data.get("extensions", {}).get("quizQuestionOptList", []):
            entry = {
                "optId": opt["optId"],
                "title": opt.get("title"),
                "mediaList": MediaList.List(opt.get("mediaList", [])),
            }
            if can_see_answers:
                entry["isCorrect"] = bool(opt.get("isCorrect", False))
            opt_list.append(entry)

        return {
            "quizQuestionId": data["quizQuestionId"],
            "title": data.get("title"),
            "mediaList": MediaList.List(data.get("mediaList", [])),
            "parentId": blog_id,
            "parentType": 1,
            "extensions": {
                "quizAnswerExplanation": data.get("extensions", {}).get(
                    "quizAnswerExplanation", ""
                ),
                "quizQuestionOptList": opt_list,
                "style": data.get("extensions", {}).get("style", {}),
            },
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

        # --- QUIZ ---
        quiz_extra = {}
        if data["blogType"] == 6:  # BlogType.Quiz
            quiz_results = data.get("quizResults", {})
            user_result = quiz_results.get(trigger_uid) if trigger_uid else None
            is_author = trigger_uid is not None and trigger_uid == data.get("authorId")
            # ответы видны автору и тем, кто уже прошёл квиз в normal-режиме
            can_see_answers = is_author or bool(
                user_result and user_result.get("normal", {}).get("isFinished")
            )

            quiz_question_list = [
                Blog.QuizQuestion(q, data["id"], can_see_answers)
                for q in data.get("quizQuestionList", [])
            ]

            quiz_result_of_current_user = None
            if user_result:
                normal = user_result.get("normal", {})
                hell = user_result.get("hell", {})
                quiz_result_of_current_user = {
                    "highestMode": 0,
                    "highestScore": normal.get("highestScore", 0),
                    "latestMode": 0,
                    "latestScore": normal.get("latestScore", 0),
                    "totalTimes": normal.get("totalTimes", 0),
                    "isFinished": normal.get("isFinished", False),
                    "hellIsFinished": hell.get("isFinished", False),
                    "beatRate": 0.0,
                    "lastBeatRate": 0.0,
                }

            quiz_extra = {
                "quizQuestionList": quiz_question_list,
                "quizResultOfCurrentUser": quiz_result_of_current_user,
                "totalQuizPlayCount": data.get("quizPlayedTimes", 0),
            }
            extensions = {
                **extensions,
                "quizTotalQuestionCount": len(quiz_question_list),
                "quizPlayedTimes": data.get("quizPlayedTimes", 0),
                "quizInBestQuizzes": extensions.get("quizInBestQuizzes", False),
            }

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
            "endTime": compute_poll_end_time(data),
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
        } | quiz_extra