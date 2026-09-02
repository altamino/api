import random
from datetime import UTC, datetime, timedelta
from re import escape as regex_escape
from time import time as timestamp
from uuid import uuid4
from fastapi import APIRouter, Request
from pymongo import DESCENDING
from services.store import StoreService
import asyncio
from helpers.config import Config
from helpers.decorators.validauth import validauth_required
from helpers.adminWS import send_ws_message as send_admin_ws
from helpers.adminWS import ApiBroadcastType


from helpers.checkins import (
    CHECKIN_COIN_REWARDS,
    CHECKIN_COIN_WEIGHTS,
    LOTTERY_REWARDS,
    LOTTERY_WEIGHTS,
    REPAIR_COIN_COST,
    REPAIR_WINDOW_SIZE,
    REPAIR_METHOD_COIN,
    REPAIR_METHOD_AMINOPLUS,
    local_date,
    date_str,
    iso_to_unix,
    get_tz,
    earned_rep,
    compute_streak,
    compute_broken_streaks,
    has_check_in_today,
    build_history_b64,
    build_checkin_history_obj,
    build_reminder_result,
)


from helpers.database.models import Community, ModelFabric
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.strikecheck import strike_check
from helpers.functions import calculate_page_tokens, parse_page_token
from helpers.routers.cachable import CachableRoute
from objects import Base, Comments, Errors, User, MediaList

profile_methods = APIRouter()
profile_methods.route_class = CachableRoute


@profile_methods.post("/g/s/account/change-amino-id")
@turtlelimiter(limit=1, period=TurtleTime.minute, tag="amino-id-change")
async def change_aminoId(request: Request):
    t1 = timestamp()

    data = await request.json()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(table="Users")

    possible_find = await table.find_one(
        {"aminoId": {"$regex": regex_escape(data["aminoId"]), "$options": "i"}}
    )
    if possible_find:
        db.close()
        return Errors.AminoIdWasTaken()

    await table.update_one({"id": uid}, {"$set": {"aminoId": data["aminoId"]}})
    db.close()

    return Base.Answer(spent_time=timestamp() - t1)


@profile_methods.get("/g/s/user-profile/search")
@profile_methods.get("/x{ndcId}/s/user-profile/search")
async def user_search(
    request: Request,
    q: str = "",
    size: int = 25,
    pageToken: str | None = None,
    ndcId: int = 0,
):
    t1 = timestamp()

    q_stripped = q.strip()
    if q_stripped == "":
        return Base.Answer(
            {"userProfileList": [], "paging": {}, "userProfileCount": 0},
            spent_time=timestamp() - t1,
        )

    size = size if 0 < size < 101 else 25
    start = parse_page_token(pageToken, 0)

    try:
        db = await Database().init()
        g_users = db.get(table="Users")
        xndc_users = db.get(f"x{ndcId}", "Users")

        nickname_query = regex_escape(q_stripped)
        query = {"nickname": {"$regex": nickname_query, "$options": "i"}}

        users = [
            item
            async for item in xndc_users.find(query)
            .skip(start)
            .limit(size)
            .sort("timestamp", DESCENDING)
        ]

        if ndcId == 0:
            query = {"aminoId": {"$regex": nickname_query, "$options": "i"}}

            temp = [
                item["id"]
                async for item in g_users.find(query)
                .skip(start)
                .limit(size)
                .sort("timestamp", DESCENDING)
            ]

            users += [
                item
                async for item in xndc_users.find({"id": {"$in": temp}})
                .skip(start)
                .limit(size)
                .sort("timestamp", DESCENDING)
            ]

        seen = set()
        unique_users = []
        for item in users:
            if item["id"] not in seen:
                seen.add(item["id"])
                unique_users.append(item)

        userProfileList = []
        for item in unique_users:
            g_row = await g_users.find_one({"id": item["id"]})
            print("status:", g_row.get("status", 0))
            merged = (g_row or {}) | item
            if g_row.get("status") != 0 :
                merged["status"] = g_row.get("status", 0)
            print("merged status:", merged.get("status", 0))

            async with await StoreService.create(item["id"], ndcId) as svc:
                merged["iconFrame"] = await svc.frame_icon(merged.get("frameId"))

            userProfileList.append(User.GetUserInfo(merged, ndcId=ndcId))

        if userProfileList:
            return Base.Answer(
                {
                    "userProfileList": userProfileList,
                    "paging": calculate_page_tokens(start, size, userProfileList),
                    "userProfileCount": await xndc_users.count_documents(query),
                },
                spent_time=timestamp() - t1,
            )
        else:
            return Base.Answer(
                {"userProfileList": [], "paging": {}, "userProfileCount": 0},
                spent_time=timestamp() - t1,
            )
    finally:
        db.close()


@profile_methods.get("/g/s/user-profile/reminder-stat")
async def get_visits(request: Request):
    return Base.Answer({"visitorsCount": 0, "unreadVisitorsCount": 0})


@profile_methods.get("/g/s/account/affiliations")
async def affiliations_config(request: Request):
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    table = db.get(table="Users")

    info = await table.find_one({"id": trigger_uid})
    if info is None:
        return Errors.AccountNotExist()

    return Base.Answer({"affiliations": info.get("communityList", [])})


@profile_methods.get("/x{ndcId}/s/user-profile/recommended")
async def get_recommended_profiles(request: Request, ndcId: int):
    return Base.Answer({"userProfileList": []})


@profile_methods.get("/g/s/reminder/check")
@profile_methods.get("/x{ndcId}/s/reminder/check")
@validauth_required
async def reminder_configs(
    request: Request,
    ndcId: int = 0,
    ndcIds: str = "",
    ignoreUnreadChatThreadsCount: bool = False,
):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    tz = await get_tz(request)
    today = local_date(tz)

    chunks: list[int] = []
    if ndcIds:
        for c in ndcIds.split(","):
            c = c.strip()
            if c:
                try:
                    chunks.append(int(c))
                except ValueError:
                    pass

    db = await Database().init()
    try:
        if ndcId:
            row = await db.get(f"x{ndcId}", table="Users").find_one({"id": trigger_uid})
        else:
            row = await db.get(table="Users").find_one({"id": trigger_uid})
        main_result = build_reminder_result(row, today)

        per_community = {}
        for cid in chunks:
            c_row = await db.get(f"x{cid}", table="Users").find_one({"id": trigger_uid})
            per_community[str(cid)] = build_reminder_result(c_row, today)
    finally:
        db.close()

    return Base.Answer(
        {
            "reminderCheckResult": main_result,
            "treatedNdcIds": chunks,
            "reminderCheckResultInCommunities": per_community,
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/x{ndcId}/s/check-in/history")
async def check_in_history(
    request: Request,
    startTime: int,
    ndcId: int,
    stopTime: int | None = None,
    timezone: int = 0,
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(f"x{ndcId}", table="Users")
    row = await table.find_one({"id": trigger_uid})
    if row is None:
        db.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    db.close()

    if not stopTime:
        stopTime = int(timestamp())
    start_dt = datetime.fromtimestamp(startTime, UTC) + timedelta(minutes=timezone)
    stop_dt = datetime.fromtimestamp(stopTime, UTC) + timedelta(minutes=timezone)

    history = row.get("checkInHistory", {}) or {}
    today = local_date(timezone)

    return Base.Answer(
        {
            "checkInHistory": {
                "joinedTime": iso_to_unix(row.get("createdTime")),
                "startTime": startTime,
                "stopTime": stopTime,
                "consecutiveCheckInDays": compute_streak(history, today),
                "hasCheckInToday": has_check_in_today(history, today),
                "hasAnyCheckIn": bool(history),
                "history": build_history_b64(history, start_dt, stop_dt),
                "streakRepairCoinCost": REPAIR_COIN_COST,
                "streakRepairWindowSize": REPAIR_WINDOW_SIZE,
            },
            "brokenStreaks": compute_broken_streaks(history, row, today),
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/x{ndcId}/s/community/general-check")
@profile_methods.post("/x{ndcId}/s/community/general-check")
async def community_general_check(request: Request, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]

    tz = await get_tz(request)
    today = local_date(tz)
    today_str = date_str(today)

    db = await Database().init()
    try:
        com_table = db.get(table="Communities")
        community = await com_table.find_one({"id": ndcId})
        if community is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        table = db.get(f"x{ndcId}", table="Users")
        global_table = db.get(table="Users")
        row = await table.find_one({"id": trigger_uid})
        gl_row = await global_table.find_one({"id": trigger_uid})
    finally:
        db.close()

    if row is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    if row.get("banned"):
        return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

    history = row.get("checkInHistory", {}) or {}
    checked_in_today = has_check_in_today(history, today)

    async with await StoreService.create(trigger_uid, ndcId) as svc:
        row["iconFrame"] = await svc.frame_icon(row.get("frameId"))

    return Base.Answer(
        {
            "hasCheckInToday": checked_in_today,
            "consecutiveCheckInDays": compute_streak(history, today),
            "canPlayLottery": gl_row.get("lastLotteryDate") != today_str,
            "userProfile": User.GetUserInfo(row, ndcId=ndcId),
            "notificationsCount": 0,
            "noticesCount": 0,
            "hasPendingReviewRequest": False,
            "promotion": None,
            "communityMembershipRequestStatus": 0,
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/x{ndcId}/s/user-profile/{userId}/achievements")
async def get_user_achievements(request: Request, userId: str, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    table = db.get(f"x{ndcId}", table="Users")
    row = await table.find_one({"id": userId})
    if row is None:
        db.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    blogs_table = db.get(f"x{ndcId}", table="Blogs")
    blogs_count = await blogs_table.count_documents({"authorId": userId, "status": 0})
    db.close()

    return Base.Answer(
        {
            "achievements": {
                "numberOfPostsCreated": blogs_count,
                "numberOfMembersCount": len(row.get("whoFollows", [])),
                "secondsSpentOfLast24Hours": int(row.get("minutesPerDay", 0) * 60),
                "secondsSpentOfLast7Days": int(row.get("minutesPerWeek", 0) * 60),
            }
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.post("/g/s/wallet/daily-reward")
@profile_methods.post("/x{ndcId}/s/check-in")
async def claim_daily_reward(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]

    tz = await get_tz(request)
    now_local = local_date(tz)
    today_str = date_str(now_local)

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", table="Users")
        global_table = db.get(table="Users")

        row = await table.find_one({"id": trigger_uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        if (row.get("checkInHistory", {}) or {}).get(today_str):
            return Errors.AlreadyClaimed(timestamp() - t1, lang=request.state.lang)

        coins = round(
            random.choices(CHECKIN_COIN_REWARDS, CHECKIN_COIN_WEIGHTS, k=1)[0], 2
        )

        result = await table.update_one(
            {"id": trigger_uid, f"checkInHistory.{today_str}": {"$ne": 1}},
            {"$set": {f"checkInHistory.{today_str}": 1}},
        )
        if result.modified_count == 0:
            return Errors.AlreadyClaimed(timestamp() - t1, lang=request.state.lang)

        updated_row = await table.find_one({"id": trigger_uid})
        history = updated_row.get("checkInHistory", {}) or {}
        streak = compute_streak(history, now_local)
        rep = earned_rep(streak)

        await table.update_one({"id": trigger_uid}, {"$inc": {"reputation": rep}})

        await global_table.update_one({"id": trigger_uid}, {"$inc": {"coins": coins}})

        global_row = await global_table.find_one({"id": trigger_uid})
    finally:
        db.close()

    updated_coins = round(float((global_row or {}).get("coins", 0.0)), 2)

    return Base.Answer(
        {
            "claimedCoins": coins,
            "totalCoins": int(updated_coins),
            "totalCoinsFloat": updated_coins,
            "consecutiveCheckInDays": streak,
            "canPlayLottery": updated_row.get("lastLotteryDate") != today_str,
            "earnedReputationPoint": rep,
            "additionalReputationPoint": 0,
            "checkInHistory": build_checkin_history_obj(updated_row, tz),
            "userProfile": User.GetUserInfo(updated_row, ndcId=ndcId),
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.post("/g/s/check-in/lottery")
@profile_methods.post("/x{ndcId}/s/check-in/lottery")
async def claim_daily_lottery(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]

    tz = await get_tz(request)
    now_local = local_date(tz)
    today_str = date_str(now_local)

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", table="Users")
        global_table = db.get(table="Users")

        row = await table.find_one({"id": trigger_uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        gl_row = await global_table.find_one({"id": trigger_uid})
        if gl_row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        if not (row.get("checkInHistory", {}) or {}).get(today_str):
            return Errors.LotteryNotAvailable(timestamp() - t1, lang=request.state.lang)

        if gl_row.get("lastLotteryDate") == today_str:
            return Errors.LotteryPlayed(timestamp() - t1, lang=request.state.lang)

        award = round(random.choices(LOTTERY_REWARDS, LOTTERY_WEIGHTS, k=1)[0], 2)

        result = await global_table.update_one(
            {"id": trigger_uid, "lastLotteryDate": {"$ne": today_str}},
            {"$set": {"lastLotteryDate": today_str}},
        )
        if result.modified_count == 0:
            return Errors.LotteryPlayed(timestamp() - t1, lang=request.state.lang)

        await global_table.update_one({"id": trigger_uid}, {"$inc": {"coins": award}})

        updated_row = await table.find_one({"id": trigger_uid})
    finally:
        db.close()

    return Base.Answer(
        {
            "lotteryLog": {
                "awardValue": int(award),
                "awardType": 1,
                "parentId": None,
                "parentType": 0,
                "objectId": str(uuid4()),
                "objectType": 0,
                "createdTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "refObject": None,
            },
            "userProfile": User.GetUserInfo(updated_row, ndcId=ndcId),
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.post("/g/s/check-in/repair")
@profile_methods.post("/x{ndcId}/s/check-in/repair")
@validauth_required
async def check_in_repair(request: Request, ndcId: int = 0):
    t1 = timestamp()
    trigger_uid = request.state.session["uid"]

    try:
        body = await request.json()
    except Exception:
        body = {}
    repair_method = int(body.get("repairMethod", REPAIR_METHOD_COIN))
    tz = await get_tz(request)
    now_local = local_date(tz)
    date_str(now_local)

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", table="Users")
        global_table = db.get(table="Users")

        row = await table.find_one({"id": trigger_uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        global_row = await global_table.find_one({"id": trigger_uid}) or {}
        history = row.get("checkInHistory", {}) or {}
        joined = None
        joined_unix = iso_to_unix(row.get("createdTime"))
        if joined_unix:
            joined = datetime.fromtimestamp(joined_unix, UTC).date()

        missed = []
        for i in range(1, REPAIR_WINDOW_SIZE + 1):
            day = now_local - timedelta(days=i)
            if joined and day.date() < joined:
                break
            day_str = date_str(day)
            if not history.get(day_str):
                missed.append(day_str)

        if not missed:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        repair_day = missed[0]

        if repair_method == REPAIR_METHOD_COIN:
            cost = REPAIR_COIN_COST
            balance = round(float(global_row.get("coins", 0.0)), 2)
            if balance < cost:
                return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)

            res = await global_table.update_one(
                {"id": trigger_uid, "coins": {"$gte": cost}},
                {"$inc": {"coins": -cost}},
            )
            if res.modified_count == 0:
                return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)

        elif repair_method == REPAIR_METHOD_AMINOPLUS:
            if not global_row.get("isPaidSubscriber"):
                return Errors.MembershipRequired(
                    timestamp() - t1, lang=request.state.lang
                )

            last_free = global_row.get("lastFreeStreakRepair")
            if last_free:
                last_dt = datetime.fromisoformat(last_free.replace("Z", "+00:00"))
                if (datetime.now(UTC) - last_dt) < timedelta(days=30):
                    return Errors.RepairAlreadyUsed(
                        timestamp() - t1, lang=request.state.lang
                    )

            await global_table.update_one(
                {"id": trigger_uid},
                {
                    "$set": {
                        "lastFreeStreakRepair": datetime.now(UTC).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    }
                },
            )
        else:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        await table.update_one(
            {"id": trigger_uid},
            {"$set": {f"checkInHistory.{repair_day}": 1}},
        )

        updated_row = await table.find_one({"id": trigger_uid})
    finally:
        db.close()

    return Base.Answer(
        {"checkInHistory": build_checkin_history_obj(updated_row, tz)},
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/g/s/user-profile/{uid}/joined")
@profile_methods.get("/x{ndcId}/s/user-profile/{uid}/joined")
async def get_user_following(
    uid: str, request: Request, ndcId: int = 0, start: int = 0, size: int = 25
):
    t1 = timestamp()

    db = await Database().init()
    xndcid_table = db.get(f"x{ndcId}", "Users")
    row = await xndcid_table.find_one({"id": uid})
    following = row["following"][start : start + size]

    following_list = []
    for item in following:
        user = await xndcid_table.find_one({"id": item})
        async with await StoreService.create(item, ndcId) as svc:
            user["iconFrame"] = await svc.frame_icon(user.get("frameId"))

        following_list.append(User.GetUserInfo(user, ndcId=ndcId))

    db.close()
    return Base.Answer({"userProfileList": following_list}, spent_time=timestamp() - t1)


@profile_methods.get("/g/s/user-profile/{uid}/member")
@profile_methods.get("/x{ndcId}/s/user-profile/{uid}/member")
async def get_user_followers(
    uid: str, request: Request, ndcId: int = 0, start: int = 0, size: int = 25
):
    t1 = timestamp()

    db = await Database().init()
    xndcid_table = db.get(f"x{ndcId}", "Users")
    row = await xndcid_table.find_one({"id": uid})
    followers = row["whoFollows"][start : start + size]
    followers_list = []
    for item in followers:
        user = await xndcid_table.find_one({"id": item})
        async with await StoreService.create(item, ndcId) as svc:
            user["iconFrame"] = await svc.frame_icon(user.get("frameId"))

        followers_list.append(User.GetUserInfo(user, ndcId=ndcId))

    db.close()
    return Base.Answer({"userProfileList": followers_list}, spent_time=timestamp() - t1)


@profile_methods.post("/g/s/user-profile/{uid}/member")
@profile_methods.post("/x{ndcId}/s/user-profile/{uid}/member")
async def follow_user(uid: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    suid = request.state.session["uid"]
    if suid == uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Users")
    target_user = await table.find_one({"id": uid})
    inited_user = await table.find_one({"id": suid})
    if suid not in target_user["whoFollows"] or uid not in inited_user["following"]:
        await table.update_one({"id": uid}, {"$push": {"whoFollows": suid}})
        await table.update_one({"id": suid}, {"$push": {"following": uid}})

    async with await StoreService.create(suid, ndcId) as svc:
        inited_user["iconFrame"] = await svc.frame_icon(inited_user.get("frameId"))

    inviter = User.GetUserInfo(inited_user, triggerUserId=uid, ndcId=ndcId)

    asyncio.get_event_loop().create_task(
        send_admin_ws(
            {
                "ndcId": ndcId,
                "user": inviter,
            },
            [uid],
            ApiBroadcastType.NewFollowerPush,
        )
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@profile_methods.delete("/g/s/user-profile/{uid}/member/{inited_uid}")
@profile_methods.delete("/x{ndcId}/s/user-profile/{uid}/member/{inited_uid}")
async def unfollow_user(uid: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    suid = request.state.session["uid"]
    if suid == uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    table = db.get(f"x{ndcId}", "Users")
    await table.update_one({"id": uid}, {"$pull": {"whoFollows": suid}})
    await table.update_one({"id": suid}, {"$pull": {"following": uid}})

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@profile_methods.get("/g/s/user-profile/{uid}")
@profile_methods.get("/x{ndcId}/s/user-profile/{uid}")
async def get_user_info(uid: str, request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session["uid"]
    db = await Database().init()
    g_table = db.get(table="Users")
    table = db.get(database=f"x{ndcId}", table="Users")
    row2 = await table.find_one({"id": uid})
    if row2 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    comments_table = db.get(f"x{ndcId}", "Comments")
    row2["commentsCount"] = await comments_table.count_documents({"rootId": f"profile:{uid}"})

    global_row = await g_table.find_one({"id": uid})
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

    db.close()
    async with await StoreService.create(trigger_uid, ndcId) as svc:
        row2["iconFrame"] = await svc.frame_icon(row2.get("frameId"))
    
    return Base.Answer(
        {
            "userProfile": User.GetUserInfo(
                row2,
                triggerUserId=trigger_uid,
                extensions=row2.get("extensions"),
                ndcId=ndcId,
            )
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.post("/g/s/user-profile/{uid}")
@profile_methods.post("/x{ndcId}/s/user-profile/{uid}")
@profile_methods.post("/g/s/account/{uid}")
@profile_methods.post("/x{ndcId}/s/account/{uid}")
async def edit_user_info(uid, request: Request, ndcId=0):
    t1 = timestamp()
    data = await request.json()

    lang = None

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]
    if trigger_uid != uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    preparedQueries = {"modifiedTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}

    if isinstance(data.get("nickname"), str):
        if len(data["nickname"].strip()) == 0:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        preparedQueries.update(
            {"nickname": data["nickname"][:64]}
        )  # finally hard limiting this

    if isinstance(data.get("content"), str):
        preparedQueries.update({"description": data["content"]})

    if isinstance(data.get("icon"), str):
        if data["icon"].startswith("https://media.altamino.top/"):
            preparedQueries.update({"icon": data["icon"]})

    if data.get("mediaList"):
        mediaList = MediaList.List(data["mediaList"])
        preparedQueries.update({"mediaList": mediaList})

    if data.get("extensions"):
        extensions = data["extensions"]
        if isinstance(extensions.get("defaultBubbleId"), str):
            preparedQueries.update({"bubbleId": extensions.get("defaultBubbleId")})
        if extensions.get("contentLanguage", "en") in Config.LANG_SEGMENTS:
            lang = {"lang": extensions.get("contentLanguage", "en")}
        if extensions.get("style"):
            style = extensions["style"]

            # background!
            preparedQueries.update({"backgroundColor": style.get("backgroundColor")})
            if isinstance(style.get("backgroundMediaList"), list):
                mediaList = MediaList.List(style["backgroundMediaList"])
                preparedQueries.update({"backgroundMediaList": mediaList})
            else:
                preparedQueries.update({"backgroundMediaList": None})

    if len(preparedQueries) == 0 and lang is None:
        return Base.Answer({"exceptions": "No data provided."})



    db = await Database().init()

    if len(preparedQueries) > 1:
        table = db.get(database=f"x{ndcId}", table="Users")
        await table.update_one({"id": uid}, {"$set": preparedQueries})

    if "customTitles" in data.get("extensions", {}):
        customTitles = data["extensions"]["customTitles"]
        table = db.get(database=f"x{ndcId}", table="Users")
        await table.update_one(
            {"id": uid},
            {"$set": {"titles": customTitles}},
        )
    if lang:
        table = db.get(table="Users")
        await table.update_one({"id": uid}, {"$set": lang})

    table = db.get(database=f"x{ndcId}", table="Users")
    row2 = await table.find_one({"id": uid})

    db.close()

    if row2 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    async with await StoreService.create(uid, ndcId) as svc:
        row2["iconFrame"] = await svc.frame_icon(row2.get("frameId"))

    return Base.Answer(
        {"userProfile": User.GetUserInfo(row2, ndcId=ndcId)},
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/g/s/account")
@profile_methods.get("/x{ndcId}/s/account")
async def get_self_info(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(table="Users")
    row1 = await table.find_one({"id": uid})
    if row1 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    table = db.get(database=f"x{ndcId}", table="Users")
    row2 = await table.find_one({"id": uid})
    if row2 is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    row = row1 | row2
    db.close()
    async with await StoreService.create(row, ndcId) as svc:
        row["iconFrame"] = await svc.frame_icon(row.get("frameId"))

    return Base.Answer(
        {"userProfile": User.GetUserInfo(row, ndcId=ndcId)},
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/g/s/wallet")
@profile_methods.get("/x{ndcId}/s/wallet")
async def get_wallet_info(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(table="Users")
    row = await table.find_one({"id": trigger_uid})
    if row is None:
        db.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    db.close()
    current_coins = round(float(row.get("coins", 0.0)), 2)
    return Base.Answer(
        {
            "wallet": {
                "businessCoinsEnabled": False,
                "newUserCoupon": None,
                "adsFlags": 2147483647,
                "adsVideoStats": {
                    "canWatchVideo": False,
                    "canEarnedCoins": 0,
                    "canNotWatchVideoReason": None,
                    "watchVideoMaxCount": 0,
                    "nextWatchVideoInterval": 0,
                    "watchedVideoCount": 0,
                },
                "totalCoins": int(current_coins),
                "totalCoinsFloat": current_coins,
                "adsEnabled": False,
                "totalBusinessCoins": 0,
                "totalBusinessCoinsFloat": 0,
            }
        },
        spent_time=timestamp() - t1,
    )


@profile_methods.get("/g/s/wallet/setting/ads")
async def get_wallet_ads_info(request: Request):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    table = db.get(table="Users")
    row = await table.find_one({"id": trigger_uid})
    if row is None:
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
    db.close()
    return Base.Answer(
        {"estimatedCoinsEarnedByAds": 0, "coinsEarnedByAds": {"total": 0, "weekly": 0}},
        spent_time=timestamp() - t1,
    )
