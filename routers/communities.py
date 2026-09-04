from re import escape as regex_escape
from time import time as timestamp
from pymongo import DESCENDING
from fastapi import APIRouter, Request
from datetime import datetime, timezone, timedelta, UTC
from uuid import uuid4
import asyncio

from helpers.aioyaml import aioyaml
from helpers.database.models import dttmn
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.validauth import validauth_required
from helpers.functions import calculate_page_tokens, is_app_link, parse_page_token
from helpers.routers.cachable import CachableRoute
from objects import Base, Communities, Errors, User
from objects.types import UserGroupType
from objects.types.blogs import BlogType
from helpers.database.redis import get as get_redis
from helpers.config import Config

from helpers.adminWS import send_ws_message as send_admin_ws
from helpers.adminWS import ApiBroadcastType
from services.store import StoreService
from objects.types import UserRole, OnlineStatus
from objects.types.store import StoreItemType
from helpers.store import _iso
from helpers.tipping_limiter import check_and_increment_tipping_limit


communities = APIRouter()
communities.route_class = CachableRoute


@communities.get("/g/s/chat/thread-check/human-readable")
async def humanreadable(request: Request, ndcIds: str = ""):
    chunks = ndcIds.split(",")

    return Base.Answer(
        {
            "treatedNdcIds": [int(chunk) for chunk in chunks],
            "threadCheckResultInCommunities": {chunk: [] for chunk in chunks},
        }
    )


# communities you currently in
@communities.get("/g/s/community/joined")
async def joined_communities(
    request: Request,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
    q: str = "",
):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Base.Answer(
            {
                "communityList": [],
                "userInfoInCommunities": {},
                "showStoreBadge": False,
            },
            spent_time=timestamp() - t1,
        )
    # parse page token
    if pageToken:
        start = parse_page_token(pageToken, start)
    uid = request.state.session["uid"]
    size = size if 0 < size < 101 else 25
    db = await Database().init()
    try:
        table = db.get(table="Users")
        row1 = await table.find_one({"id": uid})
        if row1 is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        table = db.get("x0", "Users")
        row2 = await table.find_one({"id": uid})
        if row2 is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        table = db.get(table="Communities")
        all_joined_ids = row1.get("communityList", [])

        q = q.strip()
        if q:
            # фильтруем id по совпадению имени, сохраняя исходный порядок
            matched_cursor = table.find(
                {
                    "id": {"$in": all_joined_ids},
                    "name": {"$regex": regex_escape(q), "$options": "i"},
                },
                {"id": 1},
            )
            matched_ids = {doc["id"] async for doc in matched_cursor}
            filtered_ids = [ndcId for ndcId in all_joined_ids if ndcId in matched_ids]
        else:
            filtered_ids = all_joined_ids

        cl_needed = filtered_ids[start : start + size]

        items_by_id = {}
        async for item in table.find({"id": {"$in": cl_needed}}):
            info = await Communities.Info(item, db, uid) | {"membershipStatus": 1}
            items_by_id[item["id"]] = info

        communityList = [
            items_by_id[ndcId] for ndcId in cl_needed if ndcId in items_by_id
        ]

        result = {
            "communityList": communityList,
            "userInfoInCommunities": {
                str(item): {
                    "userProfile": User.OwnNonSensetiveProfile(
                        row2, ndcId=item, membershipStatus=1
                    )
                    | {
                        "ndcId": item,
                        "isCurrentUserJoined": True,
                        "joined": True,
                        "membershipStatus": 1,
                        "accountMembershipStatus": 1,
                    }
                }
                | {
                    "ndcId": item,
                    "isCurrentUserJoined": True,
                    "joined": True,
                    "membershipStatus": 1,
                    "accountMembershipStatus": 1,
                }
                for item in cl_needed
            },
            "tags": "fancysomemore",
            "paging": calculate_page_tokens(start, size, communityList),
            "showStoreBadge": False,
        }
    finally:
        db.close()
    # print(result)
    return Base.Answer(
        result,
        spent_time=timestamp() - t1,
    )


# communities search
@communities.get("/g/s/community/search")
async def search_community(
    request: Request,
    q: str = "",
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
    language: str = "en",
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    if pageToken:
        start = parse_page_token(pageToken, start)

    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(table="Communities")
        query = {
            "name": {"$regex": regex_escape(q.strip()), "$options": "i"},
            "lang": language,
            "hidden": {"$ne": True},
        }
        total_count = await table.count_documents(query)
        items = [item async for item in table.find(query).skip(start).limit(size)]
        communityList = [await Communities.Info(item, db, uid) for item in items]
        return Base.Answer(
            {
                "communityList": communityList,
                "paging": calculate_page_tokens(start, size, communityList),
                "allItemCount": total_count,
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


# all communities available
@communities.get("/g/s/topic/0/feed/community")
@communities.get("/g/s/community/trending")
@communities.get("/g/s/community/suggested")
async def all_communities_list(
    request: Request,
    language: str = "en",
    size: int = 25,
    start: int = 0,
    pageToken: str | None = None,
):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    start = parse_page_token(pageToken, start)

    db = await Database().init()
    try:
        table = db.get(table="Communities")

        items = [
            item
            async for item in table.find({"lang": language}).skip(start).limit(size)
        ]
        communityList = [await Communities.Info(item, db, uid) for item in items]
        return Base.Answer(
            {
                "communityList": communityList,
                "paging": calculate_page_tokens(start, size, communityList),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


# community search by aminoid
@communities.get("/g/s/search/amino-id-and-link")
async def search_community_by_amino_id(
    request: Request,
    q: str = "",
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    size = size if 0 < size < 101 else 25
    if pageToken:
        start = parse_page_token(pageToken, start)

    q = q.strip()

    if is_app_link(q) and "/c/" in q:
        q = q[q.find("/c/") + 3 :]
        q = q.split("/")[0].split("?")[0].strip()

    if not q:
        return Base.Answer(
            {"resultList": [], "paging": calculate_page_tokens(start, size, [])},
            spent_time=timestamp() - t1,
        )

    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(table="Communities")
        query = {"aminoId": {"$regex": regex_escape(q), "$options": "i"}}
        items = [item async for item in table.find(query).skip(start).limit(size)]
        communityList = [
            {"refObject": await Communities.Info(item, db, uid)} for item in items
        ]
        return Base.Answer(
            {
                "resultList": communityList,
                "paging": calculate_page_tokens(start, size, communityList),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


# community join
@communities.post("/x{ndcId}/s/community/join")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="jl-community")
async def join_community(request: Request, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    try:
        # checking if user is banned globally
        table_accounts = db.get(table="Users")
        account = await table_accounts.find_one({"id": trigger_uid})
        if account and account.get("status") == 9:
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

        table_communities = db.get(table="Communities")
        community = await table_communities.find_one({"id": ndcId})
        if not community:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        # adding profile info if not exist
        table_community_users = db.get(f"x{ndcId}", "Users")
        user_info = await table_community_users.find_one({"id": trigger_uid})

        if user_info and user_info.get("status") == 9:
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

        if not user_info:
            g_table = db.get("x0", "Users")
            g_data = await g_table.find_one({"id": trigger_uid})
            if not g_data:
                return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

            # prepare new profile data
            new_profile = g_data.copy()
            new_profile["whoFollows"] = []
            new_profile["following"] = []
            new_profile["wall"] = {}
            new_profile["reputation"] = 0

            new_profile["role"] = (
                0 if new_profile["role"] not in [555] else new_profile["role"]
                # new_profile["role"] if role in [200, 201, 254] profile will be like "amino team" with altamino avatar ect in android
            )
            for field in ["_id", "createdTime", "modifiedTime"]:
                new_profile.pop(field, None)

            new_timestamp = dttmn()
            new_profile["createdTime"] = new_timestamp
            new_profile["modifiedTime"] = new_timestamp

            await table_community_users.insert_one(new_profile)
            user_info = new_profile

        # update community profile that user joined
        await table_community_users.update_one(
            {"id": trigger_uid}, {"$set": {"status": 0}}
        )

        if account.get("isVerified"):
            await table_community_users.update_one(
                {"id": trigger_uid},
                {"$set": {"isVerified": True, "tagList": account.get("tagList", [])}},
            )

        # update community
        await table_communities.update_one(
            {"id": ndcId},
            [
                {
                    "$set": {
                        "memberList": {
                            "$setUnion": [
                                {"$ifNull": ["$memberList", []]},
                                [trigger_uid],
                            ]
                        }
                    }
                },
                {"$set": {"membersCount": {"$size": "$memberList"}}},
            ],
        )

        # update global user info
        table_global_users = db.get(table="Users")
        await table_global_users.update_one(
            {"id": trigger_uid}, {"$addToSet": {"communityList": ndcId}}
        )

        asyncio.get_event_loop().create_task(
            send_admin_ws(
                {"ndcId": ndcId, "user": User.GetUserInfo(user_info, ndcId)},
                None,
                ApiBroadcastType.ChatMessagePush,
            )
        )

        return Base.Answer(
            {"userProfile": User.OwnNonSensetiveProfile(user_info, ndcId)},
            spent_time=timestamp() - t1,
        )
    except Exception as e:
        print(f"Error in join_community: {e}")
        return Errors.InternalServerError(timestamp() - t1, lang=request.state.lang)
    finally:
        db.close()


# community leave
@communities.post("/x{ndcId}/s/community/leave")
@turtlelimiter(limit=1, period=TurtleTime.second, tag="jl-community")
async def leave_community(request: Request, ndcId: int):
    t1 = timestamp()
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    try:
        table_communities = db.get(table="Communities")
        community = await table_communities.find_one({"id": ndcId})

        if not community:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        if trigger_uid == community.get("agent") or ndcId == 0:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        if trigger_uid not in community.get("memberList", []):
            return Base.Answer(
                {"api:warning": "You was never part of this community."},
                spent_time=timestamp() - t1,
            )

        # Update community: remove member
        await table_communities.update_one(
            {"id": ndcId},
            [
                {
                    "$set": {
                        "memberList": {
                            "$setDifference": [
                                {"$ifNull": ["$memberList", []]},
                                [trigger_uid],
                            ]
                        }
                    }
                },
                {"$set": {"membersCount": {"$size": "$memberList"}}},
            ],
        )

        # update global user info
        table_global_users = db.get(table="Users")
        await table_global_users.update_one(
            {"id": trigger_uid}, {"$pull": {"communityList": ndcId}}
        )

        # update community user info
        table_xndc_users = db.get(f"x{ndcId}", "Users")
        user_info = await table_xndc_users.find_one({"id": trigger_uid})
        role = (
            0
            if not user_info or user_info["role"] not in [200, 201, 254, 555]
            else user_info["role"]
        )
        new_status = (
            user_info.get("status", 0)
            if user_info and user_info.get("status") in (9, 11)
            else 5
        )
        await table_xndc_users.update_one(
            {"id": trigger_uid},
            {"$set": {"role": role, "status": new_status}},
        )

        return Base.Answer({}, spent_time=timestamp() - t1)
    except Exception as e:
        print(f"Error in leave_community: {e}")
        return Errors.InternalServerError(timestamp() - t1, lang=request.state.lang)
    finally:
        db.close()


# get community info
# [GET] /g/s/community/{ndcId}


@communities.get("/g/s/community/info")
@communities.get("/x{ndcId}/s/community/info")
@communities.get("/g/s-x{ndcId}/community/info")
async def get_community_info(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session.get("uid")

    db = await Database().init()
    try:
        ndc_info = await Communities.Info(ndcId, db, uid)
        if not ndc_info:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        users_table = db.get(f"x{ndcId}", "Users")
        user_info = await users_table.find_one({"id": uid})
        if not user_info:
            full_user_data = None
        else:
            full_user_data = User.GetUserInfo(user_info, triggerUserId=uid, ndcId=ndcId)

        return Base.Answer(
            {
                "community": ndc_info,
                "isCurrentUserJoined": bool(ndc_info.get("membershipStatus", 0)),
                "currentUserInfo": {"userProfile": full_user_data},
                #| {"membershipStatus": ndc_info.get("membershipStatus", 0)},
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


# guidelines
@communities.get("/g/s/community/official-guideline")
@communities.get("/x{ndcId}/s/community/official-guideline")
async def get_official_guidelines(
    request: Request, ndcId: int = 0, language: str = "en"
):
    try:
        file = await aioyaml("files/guidelines.yaml")
        language = (
            language.lower() if language.lower() in Config.LANG_SEGMENTS else "en"
        )
        try:
            guideline = file[language]
        except Exception:
            guideline = file.get("en", "Error loading file.")
    except Exception as e:
        print("Cant get official guidelines via yaml!:", e)
        guideline = "[b]Oh no!\nSomething went wrong. Please try again later."
        # maybe do not hardcode strings? we can parse ndclang, lookup i18n...

    return Base.Answer(
        {
            "officialGuideline": {
                "content": guideline,
                "mediaList": [],
            },
        },
    )


@communities.get("/g/s/community/guideline")
@communities.get("/x{ndcId}/s/community/guideline")
@communities.get("/g/s-x{ndcId}/community/guideline")
async def get_community_guidelines(request: Request, ndcId: int = 0):
    t1 = timestamp()

    db = await Database().init()
    try:
        table = db.get(table="Communities")
        info = await table.find_one({"id": ndcId})

        if not info:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        return Base.Answer(
            {
                "communityGuideline": {
                    "content": info.get("guideline", ""),
                    "mediaList": info.get("guidelineMediaList", []),
                }
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@communities.get("/x{ndcId}/s/user-profile")
async def get_community_profiles(
    ndcId: int,
    request: Request,
    start: int = 0,
    size: int = 25,
    type: str = "",
):
    if type == "featured":
        return Base.Answer(
            {
                "userProfileCount": 0,
                "userProfileList": [],
            },
        )

    t1 = timestamp()
    size = size if 0 < size < 101 else 25

    queries = {
        "leaders": {"role": {"$in": [102, 100]}},
        "curators": {"role": 101},
        "recent": {"status": {"$nin": [9, 10, 5]}},
        "summary": {"status": {"$nin": [9, 10, 5]}},  # banned, deleted, leaved
    }

    query = queries.get(type)
    if query is None:
        return Errors.InvalidRequest()

    if type in ("recent", "summary"):
        sort_order = [("createdTime", DESCENDING)]
    else:
        sort_order = [("role", DESCENDING), ("createdTime", DESCENDING)]

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        g_table = db.get(table="Users")

        items = []
        total = await table.count_documents(query)



        
        async for item in table.find(query).skip(start).limit(size).sort(sort_order):
            async with await StoreService.create(item["id"], ndcId) as svc:
                item["iconFrame"] = await svc.frame_icon(item.get("frameId"))

            uid = item["id"]
            global_row = await g_table.find_one({"id": uid})
            if global_row:
                item["tagList"] = list(
                    set(global_row.get("tagList", []) + item.get("tagList", []))
                )

                item["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)

                if "isTeamMember" in global_row:
                    item["isTeamMember"] = global_row["isTeamMember"]

                if "isVerified" in global_row:
                    item["isVerified"] = global_row["isVerified"]
                if global_row.get("status", 0) in [9, 10]:
                    item["status"] = global_row["status"]
                if global_row.get("extensions", {}).get("__disabledLevel__"):
                    item["extensions"]["__disabledLevel__"] = global_row["extensions"][
                        "__disabledLevel__"
                    ]


            items.append(
                User.OwnNonSensetiveProfile(item, ndcId=ndcId, membershipStatus=1)
            )

        return Base.Answer(
            {
                "userProfileCount": total,
                "userProfileList": items,
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@communities.get("/g/s/user-group/{userGroupType}")
@communities.get("/x{ndcId}/s/user-group/{userGroupType}")
async def get_user_groups(
    request: Request,
    userGroupType: str,
    ndcId: int = 0,
    start: int = 0,
    size: int = 20,
    stoptime: str | None = None,
):
    t1 = timestamp()
    if userGroupType != UserGroupType.QuickAccess:
        return Base.Answer({"userProfileList": []}, spent_time=timestamp() - t1)

    size = size if 0 < size < 101 else 20
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        row = await table.find_one({"id": uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        favEntries = row.get("quickAccessList", [])
        favEntries = [
            e if isinstance(e, dict) else {"id": e, "addedAt": ""} for e in favEntries
        ]

        if stoptime:
            favEntries = [e for e in favEntries if e.get("addedAt", "") < stoptime]

        pageEntries = favEntries[start : start + size]
        favIds = [e["id"] for e in pageEntries]

        if not favIds:
            return Base.Answer({"userProfileList": []}, spent_time=timestamp() - t1)

        users_by_id = {}
        async for u in table.find({"id": {"$in": favIds}}):
            users_by_id[u["id"]] = User.GetUserInfo(u, ndcId=ndcId)

        userProfileList = [users_by_id[fid] for fid in favIds if fid in users_by_id]
    finally:
        db.close()

    return Base.Answer(
        {"userProfileList": userProfileList}, spent_time=timestamp() - t1
    )


@communities.post("/g/s/user-group/{userGroupType}/position")
@communities.post("/x{ndcId}/s/user-group/{userGroupType}/position")
async def reorder_user_group(request: Request, userGroupType: str, ndcId: int = 0):
    t1 = timestamp()
    if userGroupType != UserGroupType.QuickAccess:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    try:
        data = await request.json()
        uidList = data["uidList"]
        if not isinstance(uidList, list):
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        row = await table.find_one({"id": uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        favEntries = row.get("quickAccessList", [])
        favEntries = [
            e if isinstance(e, dict) else {"id": e, "addedAt": ""} for e in favEntries
        ]

        entries_by_id = {e["id"]: e for e in favEntries}

        seen = set()
        new_front = []
        for target_id in uidList:
            if target_id in entries_by_id and target_id not in seen:
                new_front.append(entries_by_id[target_id])
                seen.add(target_id)

        remaining = [e for e in favEntries if e["id"] not in seen]
        new_order = new_front + remaining

        await table.update_one({"id": uid}, {"$set": {"quickAccessList": new_order}})
    finally:
        db.close()

    return Base.Answer({}, spent_time=timestamp() - t1)


@communities.post("/g/s/user-group/{userGroupType}/{targetId}")
@communities.post("/x{ndcId}/s/user-group/{userGroupType}/{targetId}")
async def add_to_user_group(
    request: Request, userGroupType: str, targetId: str, ndcId: int = 0
):
    t1 = timestamp()
    if userGroupType != UserGroupType.QuickAccess:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        row = await table.find_one({"id": uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        target = await table.find_one({"id": targetId})
        if target is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        existing = row.get("quickAccessList", [])
        existing_ids = {(e["id"] if isinstance(e, dict) else e) for e in existing}
        if targetId in existing_ids:
            return Base.Answer({}, spent_time=timestamp() - t1)

        entry = {
            "id": targetId,
            "addedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        await table.update_one({"id": uid}, {"$push": {"quickAccessList": entry}})
    finally:
        db.close()

    return Base.Answer({}, spent_time=timestamp() - t1)


@communities.delete("/g/s/user-group/{userGroupType}/{targetId}")
@communities.delete("/x{ndcId}/s/user-group/{userGroupType}/{targetId}")
async def remove_from_user_group(
    request: Request, userGroupType: str, targetId: str, ndcId: int = 0
):
    t1 = timestamp()
    if userGroupType != UserGroupType.QuickAccess:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        row = await table.find_one({"id": uid})
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        await table.update_one(
            {"id": uid},
            {"$pull": {"quickAccessList": targetId}},
        )
        await table.update_one(
            {"id": uid},
            {"$pull": {"quickAccessList": {"id": targetId}}},
        )
    finally:
        db.close()

    return Base.Answer({}, spent_time=timestamp() - t1)


async def _get_online_uids(ndcId: int) -> list[str]:
    redis = get_redis()
    pattern = f"x{ndcId}:online:*"
    uids = []
    async for key in redis.scan_iter(pattern):
        # key format is x{ndcId}:online:{uid}
        uids.append(key.split(":")[-1])
    return uids


async def _get_profiles_for_live_layer(ndcId: int, uids: list[str]) -> list[dict]:
    if not uids:
        return []
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "Users")
        g_table = db.get(table="Users")
        cursor = table.find({
            "id": {"$in": uids},
            "onlineStatus": {"$ne": OnlineStatus.OFFLINE}
        })
        rows_by_id = {row["id"]: row async for row in cursor}
        result = []
        for u in uids:
            if u in rows_by_id:
                row = rows_by_id[u]
                async with await StoreService.create(u, ndcId) as svc:
                    row["iconFrame"] = await svc.frame_icon(row.get("frameId"))


                uid = row["id"]
                global_row = await g_table.find_one({"id": uid})
                if global_row:
                    row["tagList"] = list(
                        set(global_row.get("tagList", []) + row.get("tagList", []))
                    )

                    row["isPaidSubscriber"] = global_row.get("isPaidSubscriber", False)

                    if "isTeamMember" in global_row:
                        row["isTeamMember"] = global_row["isTeamMember"]

                    if "isVerified" in global_row:
                        row["isVerified"] = global_row["isVerified"]
                    if global_row.get("status", 0) in [9, 10]:
                        row["status"] = global_row["status"]
                    if global_row.get("extensions", {}).get("__disabledLevel__"):
                        row["extensions"]["__disabledLevel__"] = global_row["extensions"][
                            "__disabledLevel__"
                        ]
                row["onlineStatus"] = row.get("onlineStatus", OnlineStatus.ONLINE)




                result.append(
                    User.OwnNonSensetiveProfile(row, ndcId=ndcId, membershipStatus=1)
                )
        return result
    finally:
        db.close()


@communities.get("/g/s/live-layer")
@communities.get("/x{ndcId}/s/live-layer")
async def live_layer_topic(
    request: Request,
    ndcId: int = 0,
    topic: str | None = None,
    start: int = 0,
    size: int = 20,
):
    if topic is None:
        return Errors.InvalidRequest()

    effective_ndcId = ndcId
    if not effective_ndcId and topic:
        parts = topic.split(":")
        if len(parts) >= 2:
            ndc_part = parts[1]
            if ndc_part.startswith("x"):
                try:
                    effective_ndcId = int(ndc_part[1:])
                except ValueError:
                    pass

    all_uids = await _get_online_uids(effective_ndcId)
    profiles = await _get_profiles_for_live_layer(effective_ndcId, all_uids)
    total = len(profiles)
    page_profiles = profiles[start : start + size]

    return Base.Answer(
        Base.LiveLayerTopic(
            topic_name=topic,
            users_count=total,
            users_list=page_profiles,
        )
    )


@communities.get("/g/s/live-layer/homepage")
@communities.get("/x{ndcId}/s/live-layer/homepage")
async def live_layer(request: Request, ndcId: int = 0):
    uids = await _get_online_uids(ndcId)
    profiles = await _get_profiles_for_live_layer(ndcId, uids)

    return Base.Answer(
        {
            "liveLayerList": [
                Base.LiveLayerTopic(
                    topic_name=f"ndtopic:x{ndcId}:online-members",
                    users_count=len(profiles),
                    users_list=profiles,
                ),
                Base.LiveLayerTopic(
                    topic_name=f"ndtopic:x{ndcId}:watching",
                ),
            ]
        }
    )


@communities.post("/g/s/community/joined/reorder")
async def reorder_communities(request: Request):
    t1 = timestamp()
    uid = request.state.session["uid"]
    data = await request.json()
    ndcIdList = data.get("ndcIdList", [])
    if not ndcIdList:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        table = db.get(table="Users")
        row1 = await table.find_one({"id": uid})
        if row1 is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        current_order = row1.get("communityList", [])

        new_front = [ndcId for ndcId in ndcIdList if ndcId in current_order]
        new_front_set = set(new_front)

        remaining = [ndcId for ndcId in current_order if ndcId not in new_front_set]

        new_order = new_front + remaining

        await table.update_one({"id": uid}, {"$set": {"communityList": new_order}})
    finally:
        db.close()

    return Base.Answer(
        spent_time=timestamp() - t1,
    )


# looks like this request allows precheck if you can do it
# for now it will be mocked
# GET /api/v1/x1/s/user-profile/de838eb4-312c-4ba0-9d81-9aad3fc984e1/compose-eligible-check?objectType=chat-thread&objectSubtype=public
@communities.get("/x{ndcId}/s/user-profile/{uid}/compose-eligible-check")
@validauth_required
async def compose_eligible_check(request: Request, ndcId: int, uid: str):
    trigger_uid = request.state.session["uid"]
    if trigger_uid != uid:
        return Errors.InvalidRequest()

    return Base.Answer()


# leaders choice
@communities.get("/g/s/community/kindred")
@communities.get("/x{ndcId}/s/community/kindred")
@communities.get("/g/s-x{ndcId}/community/kindred")
async def get_leaders_choice(request: Request, ndcId: int = 0):
    return Base.Answer()


@communities.get("/x{ndcId}/s/community/user-titles")
async def get_community_titles(request: Request, ndcId: int = 0):
    t1 = timestamp()
    db = await Database().init()
    titles = []
    try:
        table = db.get(f"x{ndcId}", "Users")
        user = await table.find_one({})
        titles = user.get("titles", []) if user else []
    finally:
        db.close()
    return Base.Answer({"userTitleList": titles}, spent_time=timestamp() - t1)


REP_PER_MINUTE = 0.5
MAX_ACTIVE_SECONDS_PER_DAY = 16 * 3600
MAX_REP_PER_DAY_FROM_ACTIVE_TIME = REP_PER_MINUTE * 60 * MAX_ACTIVE_SECONDS_PER_DAY
MIN_SECONDS_BETWEEN_REPORTS = 20


def _week_key(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


@communities.post("/x{ndcId}/s/community/stats/user-active-time")
async def count_user_active_time(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if ndcId == 0:
        return Base.Answer({})

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    chunk_list = body.get("userActiveTimeChunkList") or []
    if not chunk_list:
        return Base.Answer({})

    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    today_str = now.strftime("%Y-%m-%d")
    week_str = _week_key(now)

    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", table="Users")

        row = await table.find_one({"id": trigger_uid})
        if row is None:
            return Base.Answer({}, spent_time=timestamp() - t1)

        last_report_ts = row.get("lastActiveReportTs", 0)
        if now_ts - last_report_ts < MIN_SECONDS_BETWEEN_REPORTS:
            return Base.Answer({}, spent_time=timestamp() - t1)

        already_reported = set(row.get("reportedChunkHashes", []) or [])
        new_hashes = []
        total_seconds = 0

        for chunk in chunk_list:
            start = chunk.get("start")
            end = chunk.get("end")
            if start is None or end is None:
                continue
            delta = end - start
            if delta <= 0 or delta > 3600:
                continue
            if end > now_ts + 60:
                continue

            chunk_hash = f"{start}:{end}"
            if chunk_hash in already_reported:
                continue

            new_hashes.append(chunk_hash)
            total_seconds += delta

        if total_seconds <= 0:
            return Base.Answer({}, spent_time=timestamp() - t1)

        last_active_day = row.get("lastActiveDay")
        last_active_week = row.get("lastActiveWeek")
        day_changed = last_active_day != today_str
        week_changed = last_active_week != week_str

        active_time_today_before = (
            0 if day_changed else (row.get("activeTime", {}) or {}).get(today_str, 0)
        )
        minutes_per_day_before = 0 if day_changed else row.get("minutesPerDay", 0)
        minutes_per_week_before = 0 if week_changed else row.get("minutesPerWeek", 0)

        remaining_daily_cap = max(
            MAX_ACTIVE_SECONDS_PER_DAY - active_time_today_before, 0
        )
        capped_seconds = min(total_seconds, remaining_daily_cap)

        set_fields = {
            "lastActiveTime": now_ts,
            "lastActiveReportTs": now_ts,
            "lastActiveDay": today_str,
            "lastActiveWeek": week_str,
        }

        if capped_seconds <= 0:
            if day_changed:
                set_fields["minutesPerDay"] = 0
            if week_changed:
                set_fields["minutesPerWeek"] = 0

            update_ops = {"$set": set_fields}
            if new_hashes:
                update_ops["$addToSet"] = {"reportedChunkHashes": {"$each": new_hashes}}
            await table.update_one({"id": trigger_uid}, update_ops)
            return Base.Answer({}, spent_time=timestamp() - t1)

        capped_minutes = capped_seconds / 60

        rep_already_given_today = min(
            active_time_today_before / 60 * REP_PER_MINUTE,
            MAX_REP_PER_DAY_FROM_ACTIVE_TIME,
        )
        active_time_today_after = active_time_today_before + capped_seconds
        rep_should_have_today = min(
            active_time_today_after / 60 * REP_PER_MINUTE,
            MAX_REP_PER_DAY_FROM_ACTIVE_TIME,
        )
        rep_to_add = round(max(rep_should_have_today - rep_already_given_today, 0), 2)

        set_fields["minutesPerDay"] = round(minutes_per_day_before + capped_minutes, 2)
        set_fields["minutesPerWeek"] = round(
            minutes_per_week_before + capped_minutes, 2
        )

        inc_fields = {
            "activeTimeTotal": capped_seconds,
            f"activeTime.{today_str}": capped_seconds,
        }
        if rep_to_add > 0:
            inc_fields["reputation"] = rep_to_add

        update_ops = {"$set": set_fields, "$inc": inc_fields}
        if new_hashes:
            update_ops["$addToSet"] = {"reportedChunkHashes": {"$each": new_hashes}}

        await table.update_one({"id": trigger_uid}, update_ops)
    finally:
        db.close()

    return Base.Answer({}, spent_time=timestamp() - t1)


# ----stickers

"""
types:
community-shared
my-active-collection
my-favorite-collection
my-collection
"""


async def _shape_collection(db, doc: dict, ndcId: int, includeStickers: bool) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)

    sticker_list = doc.get("stickerList", [])
    for sticker in sticker_list:
        sticker.pop("_id", None)

    doc["stickerList"] = sticker_list if includeStickers else []

    author = None
    creator_id = doc.get("creatorId")
    if not doc.get("availableNdcIds", []):
        doc["availableNdcIds"] = [ndcId]
    if creator_id:
        author_doc = await db.get("x0", table="Users").find_one(
            {"id": creator_id}, projection={"_id": 0}
        )
        if author_doc:
            author = User.GetUserInfo(author_doc, ndcId=ndcId)

    doc["author"] = author
    return doc


async def _is_owned(db, uid: str, collectionId: str) -> dict | None:
    return await db.get(table="UserStoreItems").find_one(
        {
            "uid": uid,
            "objectType": StoreItemType.StickerCollection,
            "objectId": collectionId,
        }
    )


async def _grant_ownership(
    db, uid: str, collectionId: str, isActivated: bool = True
) -> None:
    owned = db.get(table="UserStoreItems")
    existing = await owned.find_one(
        {
            "uid": uid,
            "objectType": StoreItemType.StickerCollection,
            "objectId": collectionId,
        }
    )
    if existing:
        return

    await owned.insert_one(
        {
            "uid": uid,
            "objectId": collectionId,
            "objectType": StoreItemType.StickerCollection,
            "isActivated": isActivated,
            "ownershipInfo": {
                "createdTime": _iso(),
                "expiredTime": None,
                "isAutoRenew": False,
                "ownershipStatus": 1,
            },
            "createdTime": _iso(),
        }
    )


@communities.post("/g/s/sticker-collection/creatable-check")
@communities.post("/x{ndcId}/s/sticker-collection/creatable-check")
async def sticker_creatable_check(
    request: Request,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")
        g_user = await sensitive_table.find_one({"id": trigger_uid})

        if ndcId == 0:
            if not g_user or not UserRole.is_global_staff(g_user.get("role", 0)):
                return Errors.NotEnoughRights(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

        try:
            body = await request.json()
        except Exception:
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        _timestamp = body.get("timestamp")
        collectionType = body.get("collectionType")
    finally:
        db.close()

    return Base.Answer(spent_time=timestamp() - t1)


@communities.get("/g/s/sticker-collection/{collectionId}")
@communities.get("/x{ndcId}/s/sticker-collection/{collectionId}")
async def get_sticker_collection(
    request: Request,
    collectionId: str,
    includeStickers: bool = False,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        doc = await table.find_one({"collectionId": collectionId})

        if not doc:
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        collection = await _shape_collection(db, doc, ndcId, includeStickers)
    finally:
        db.close()

    return Base.Answer({"stickerCollection": collection}, spent_time=timestamp() - t1)


@communities.get("/g/s/sticker-collection")
@communities.get("/x{ndcId}/s/sticker-collection")
async def sticker_collections(
    request: Request,
    type: str | None = None,
    includeStickers: bool = False,
    start: int = 0,
    size: int = 20,
    stoptime: str | None = None,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]
    size = size if 0 < size < 101 else 20

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")

        if type in ("my-active-collection", "my-favorite-collection"):
            owned_query = {
                "uid": trigger_uid,
                "objectType": StoreItemType.StickerCollection,
            }
            if type == "my-active-collection":
                owned_query["isActivated"] = True

            owned_docs = (
                await db.get(table="UserStoreItems")
                .find(owned_query, {"_id": 0, "objectId": 1})
                .to_list(length=None)
            )
            owned_ids = [d["objectId"] for d in owned_docs]

            query = {"status": 0, "collectionId": {"$in": owned_ids}}

        elif type == "my-collection":
            query = {"status": 0, "creatorId": trigger_uid}

        elif type == "community-shared":
            query = {"status": 0, "isShared": True, "ndcId": ndcId}

        else:
            query = {"status": 0, "ndcId": ndcId}

        if stoptime:
            query["createdTime"] = {"$lt": stoptime}

        total = await table.count_documents(query)
        items = []
        async for doc in (
            table.find(query).sort([("createdTime", -1)]).skip(start).limit(size)
        ):
            items.append(await _shape_collection(db, doc, ndcId, includeStickers))
    finally:
        db.close()

    return Base.Answer(
        {"stickerCollectionCount": total, "stickerCollectionList": items},
        spent_time=timestamp() - t1,
    )


@communities.post("/g/s/sticker-collection")
@communities.post("/x{ndcId}/s/sticker-collection")
async def create_sticker_collection(
    request: Request,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]

    try:
        body = await request.json()
    except Exception:
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    description = body.get("description", "")
    collection_icon_index = body.get("iconSourceStickerIndex", 0)
    collection_type = body.get("collectionType")
    collection_name = body.get("name", "Sticker Collection Fallback Name")
    sticker_list = body.get("stickerList", [])

    if not sticker_list or not isinstance(sticker_list, list):
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    if not isinstance(collection_icon_index, int) or isinstance(
        collection_icon_index, bool
    ):
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    if not (0 <= collection_icon_index < len(sticker_list)):
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    if collection_type is not None and (
        isinstance(collection_type, bool) or not isinstance(collection_type, int)
    ):
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    collection_id = str(uuid4())

    prepared_stickers = []
    for sticker in sticker_list:
        if not isinstance(sticker, dict):
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        name = sticker.get("name")
        icon = sticker.get("icon")

        if not isinstance(name, str) or not name.strip():
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        if not isinstance(icon, str) or not icon.strip():
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        prepared_stickers.append(
            {
                "stickerId": str(uuid4()),
                "stickerCollectionId": collection_id,
                "name": name.strip(),
                "icon": icon.strip(),
                "iconV2": icon.strip(),
                "smallIcon": icon.strip(),
                "smallIconV2": icon.strip(),
                "mediumIcon": icon.strip(),
                "mediumIconV2": icon.strip(),
                "usedCount": 0,
                "status": 0,
                "extensions": {},
                "createdTime": now,
            }
        )

    icon_sticker = prepared_stickers[collection_icon_index]

    collection = {
        "collectionId": collection_id,
        "ndcId": ndcId,
        "creatorId": trigger_uid,
        "name": collection_name.strip()
        if isinstance(collection_name, str)
        else "Sticker Collection Fallback Name",
        "description": description if isinstance(description, str) else "",
        "collectionType": collection_type,
        "icon": icon_sticker["icon"],
        "smallIcon": icon_sticker["icon"],
        "bannerUrl": None,
        "stickersCount": len(prepared_stickers),
        "usedCount": 0,
        "status": 0,
        "isShared": False,
        "availableNdcIds": [ndcId] if ndcId else [],
        "extensions": {"iconSourceStickerId": icon_sticker["stickerId"]},
        "discountStatus": 0,
        "discountValue": 0,
        "ownerType": 0,
        "restrictType": 1,
        "price": 0,
        "restrictValue": None,
        "availableDuration": 0,
        "stickerList": prepared_stickers,
        "createdTime": now,
        "modifiedTime": now,
    }

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        await table.insert_one(dict(collection))

        # автор сразу владеет и активирует собственный пак
        await _grant_ownership(db, trigger_uid, collection_id, isActivated=True)

        result = await _shape_collection(db, collection, ndcId, includeStickers=True)
    finally:
        db.close()

    return Base.Answer({"stickerCollection": result}, spent_time=timestamp() - t1)


@communities.post("/g/s/sticker-collection/{collectionId}")
@communities.post("/x{ndcId}/s/sticker-collection/{collectionId}")
async def edit_sticker_collection(
    request: Request,
    collectionId: str,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]

    try:
        body = await request.json()
    except Exception:
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        doc = await table.find_one({"collectionId": collectionId})

        if not doc:
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        is_owner = doc.get("creatorId") == trigger_uid
        is_allowed = is_owner

        if not is_allowed:
            sensitive_table = db.get(table="Users")
            global_user = await sensitive_table.find_one({"id": trigger_uid})
            if global_user and UserRole.is_global_staff(global_user.get("role", 0)):
                is_allowed = True

        if not is_allowed:
            return Errors.NotEnoughRights(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        existing_stickers = {
            s["stickerId"]: s for s in doc.get("stickerList", []) if s.get("stickerId")
        }

        set_ops = {}

        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip():
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )
            set_ops["name"] = name.strip()

        if "description" in body:
            description = body["description"]
            if not isinstance(description, str):
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )
            set_ops["description"] = description

        if "collectionType" in body:
            collection_type = body["collectionType"]
            if collection_type is not None and (
                isinstance(collection_type, bool)
                or not isinstance(collection_type, int)
            ):
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )
            set_ops["collectionType"] = collection_type

        prepared_stickers = None
        if "stickerList" in body:
            sticker_list = body["stickerList"]
            if not sticker_list or not isinstance(sticker_list, list):
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            prepared_stickers = []

            for sticker in sticker_list:
                if not isinstance(sticker, dict):
                    return Errors.InvalidRequest(
                        spent_time=timestamp() - t1, lang=request.state.lang
                    )

                name = sticker.get("name")
                icon = sticker.get("icon")

                if not isinstance(name, str) or not name.strip():
                    return Errors.InvalidRequest(
                        spent_time=timestamp() - t1, lang=request.state.lang
                    )

                if not isinstance(icon, str) or not icon.strip():
                    return Errors.InvalidRequest(
                        spent_time=timestamp() - t1, lang=request.state.lang
                    )

                sticker_id = sticker.get("stickerId")
                existing = existing_stickers.get(sticker_id) if sticker_id else None

                if existing:
                    prepared_stickers.append(
                        {
                            "stickerId": existing["stickerId"],
                            "stickerCollectionId": collectionId,
                            "name": name.strip(),
                            "icon": icon.strip(),
                            "iconV2": icon.strip(),
                            "smallIcon": icon.strip(),
                            "smallIconV2": icon.strip(),
                            "mediumIcon": icon.strip(),
                            "mediumIconV2": icon.strip(),
                            "usedCount": existing.get("usedCount", 0),
                            "status": existing.get("status", 0),
                            "extensions": existing.get("extensions", {}),
                            "createdTime": existing.get("createdTime", now),
                        }
                    )
                else:
                    prepared_stickers.append(
                        {
                            "stickerId": str(uuid4()),
                            "stickerCollectionId": collectionId,
                            "name": name.strip(),
                            "icon": icon.strip(),
                            "iconV2": icon.strip(),
                            "smallIcon": icon.strip(),
                            "smallIconV2": icon.strip(),
                            "mediumIcon": icon.strip(),
                            "mediumIconV2": icon.strip(),
                            "usedCount": 0,
                            "status": 0,
                            "extensions": {},
                            "createdTime": now,
                        }
                    )

            set_ops["stickerList"] = prepared_stickers
            set_ops["stickersCount"] = len(prepared_stickers)

        if "iconSourceStickerIndex" in body:
            icon_index = body["iconSourceStickerIndex"]
            if not isinstance(icon_index, int) or isinstance(icon_index, bool):
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

            reference_stickers = (
                prepared_stickers
                if prepared_stickers is not None
                else doc.get("stickerList", [])
            )

            if not (0 <= icon_index < len(reference_stickers)):
                return Errors.InvalidRequest(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

            icon_sticker = reference_stickers[icon_index]
            set_ops["icon"] = icon_sticker["icon"]
            set_ops["smallIcon"] = icon_sticker["icon"]
            set_ops["extensions"] = {
                **doc.get("extensions", {}),
                "iconSourceStickerId": icon_sticker["stickerId"],
            }

        if not set_ops:
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        set_ops["modifiedTime"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        await table.update_one({"collectionId": collectionId}, {"$set": set_ops})
        updated = await table.find_one({"collectionId": collectionId})
        collection = await _shape_collection(db, updated, ndcId, includeStickers=True)
    finally:
        db.close()

    return Base.Answer({"stickerCollection": collection}, spent_time=timestamp() - t1)


@communities.delete("/g/s/sticker-collection/{collectionId}")
@communities.delete("/x{ndcId}/s/sticker-collection/{collectionId}")
async def delete_sticker_collection(
    request: Request,
    collectionId: str,
    ndcId: int = 0,
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        doc = await table.find_one({"collectionId": collectionId})

        if not doc:
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        is_owner = doc.get("creatorId") == trigger_uid
        is_allowed = is_owner

        if not is_allowed:
            sensitive_table = db.get(table="Users")
            global_user = await sensitive_table.find_one({"id": trigger_uid})
            if global_user and UserRole.is_global_staff(global_user.get("role", 0)):
                is_allowed = True

        if not is_allowed:
            return Errors.NotEnoughRights(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        await table.delete_one({"collectionId": collectionId})

        # чистим владение у всех, кто добавил себе этот пак
        await db.get(table="UserStoreItems").delete_many(
            {"objectType": StoreItemType.StickerCollection, "objectId": collectionId}
        )
    finally:
        db.close()

    return Base.Answer(spent_time=timestamp() - t1)


@communities.post("/g/s/sticker-collection/{collectionId}/activate")
@communities.post("/x{ndcId}/s/sticker-collection/{collectionId}/activate")
async def activate_sticker_collection(
    request: Request,
    collectionId: str,
    ndcId: int = 0,
):
    return await _set_collection_activation(request, collectionId, ndcId, True)


@communities.post("/g/s/sticker-collection/{collectionId}/deactivate")
@communities.post("/x{ndcId}/s/sticker-collection/{collectionId}/deactivate")
async def deactivate_sticker_collection(
    request: Request,
    collectionId: str,
    ndcId: int = 0,
):
    return await _set_collection_activation(request, collectionId, ndcId, False)


async def _set_collection_activation(
    request: Request, collectionId: str, ndcId: int, activate: bool
):
    t1 = timestamp()

    if not request.state.session["validsession"]:
        return Errors.InvalidSession(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    trigger_uid = request.state.session["uid"]

    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        doc = await table.find_one({"collectionId": collectionId})

        if not doc:
            return Errors.DataNotExist(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        owned = db.get(table="UserStoreItems")
        existing = await owned.find_one(
            {
                "uid": trigger_uid,
                "objectType": StoreItemType.StickerCollection,
                "objectId": collectionId,
            }
        )

        if existing:
            await owned.update_one(
                {
                    "uid": trigger_uid,
                    "objectType": StoreItemType.StickerCollection,
                    "objectId": collectionId,
                },
                {"$set": {"isActivated": activate}},
            )
        elif activate:
            # юзер жмёт "активировать" на паке, которого у него ещё нет —
            # трактуем как "добавить себе и включить" (аналог purchase для free-item)
            await _grant_ownership(db, trigger_uid, collectionId, isActivated=True)
        else:
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

        collection = await _shape_collection(db, doc, ndcId, includeStickers=True)
    finally:
        db.close()

    return Base.Answer({"stickerCollection": collection}, spent_time=timestamp() - t1)







@communities.post("/x{ndcId}/s/tipping")
@communities.post("/g/s/blog/tipping")
@turtlelimiter(limit=5, period=TurtleTime.minute, tag="tip")
async def tipping(request: Request, ndcId: int = 0):
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

    objectId = data.get("objectId")
    objectType = data.get("objectType")
    if not objectId or not objectType:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    transactionId = data.get("tippingContext", {}).get("transactionId", str(uuid4()))

    #remake it later
    tables = {}
    for x in [BlogType.Basic, BlogType.Wiki, BlogType.Question, BlogType.Vote, BlogType.Image]:
        tables[x] = f"Blogs"

    table = tables.get(objectType)
    if not table:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    

    
    db = await Database().init()
    users_table = db.get(table="Users")
    sender = await users_table.find_one({"id": trigger_uid})
    if sender is None:
        db.close()
        return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

    if sender.get("coins", 0.0) < coins:
        db.close()
        return Errors.NotEnoughCoins(timestamp() - t1, lang=request.state.lang)

    blogs_table = db.get(f"x{ndcId}", table)
    _object = await blogs_table.find_one({"id": objectId})
    if _object is None:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    author_uid = _object.get("authorId")

    # Deduct from sender and credit author
    if author_uid:
        await users_table.update_one({"id": trigger_uid}, {"$inc": {"coins": -coins}})
        await users_table.update_one({"id": author_uid}, {"$inc": {"coins": coins}})
    else:
        db.close()
        return Errors.DataNotExist(spent_time=timestamp() - t1, lang=request.state.lang)

    # Update blog tipInfo leaderboard
    tip_info = _object.get("tipInfo", {})
    tippers_list = tip_info.get("tippersList", [])

    tipper_entry = next((t for t in tippers_list if t.get("uid") == trigger_uid), None)
    if tipper_entry:
        tipper_entry["totalTippedCoins"] = round(
            tipper_entry.get("totalTippedCoins", 0.0) + coins, 2
        )
    else:
        ndc_users = db.get(f"x{ndcId}", "Users")
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
        "tipMaxCoin": 500,
        "tippersCount": len(tippers_list),
        "tippable": True,
        "tipMinCoin": 1,
        "tippedCoins": new_tipped_coins,
        "tippersList": tippers_list,
    }

    await blogs_table.update_one(
        {"id": objectId}, {"$set": {"tipInfo": updated_tip_info}}
    )
    db.close()

    return Base.Answer({"tipInfo": updated_tip_info}, spent_time=timestamp() - t1)











