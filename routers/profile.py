from pymongo import DESCENDING, ASCENDING
from base64 import b85decode, b85encode
from re import compile as regex_compile
from fastapi import APIRouter, Request
from time import time as timestamp
from datetime import datetime
from typing import Union

import sys
sys.path.append('../')
from objects import *
from helpers.database.mongo import *
from helpers.routers.cachable import CachableRoute

profile_methods = APIRouter()
profile_methods.route_class = CachableRoute

@profile_methods.post("/g/s/account/change-amino-id")
async def change_aminoId(request: Request):
    t1 = timestamp()
    
    data = await request.json()
    if not request.state.session['validsession']:
        return Errors.InvalidSession()
    
    uid = request.state.session['uid']

    db = await Database().init()
    table = await db.get(table="Users")
    await table.update_one(
        {"id": uid},
        {"$set": {"aminoId": data['aminoId']}}
    )
    await db.close()

    return Base.Answer(spent_time=timestamp()-t1)


# user search
# /g/s/user-profile/search?q=Hello&pagingType=t&size=25

@profile_methods.get("/g/s/user-profile/search")
async def user_search(request: Request, q: str = "", size: int = 25, pageToken: str | None = None):
    t1 = timestamp()
    
    if q.strip() == "":
        return Base.Answer({
            "userProfileList": [
            ],
            "paging": {
            },
            "userProfileCount": 0
        }, spent_time=timestamp()-t1)

    size = size if 0 > size > 101 else 25

    # parse page token
    if pageToken:
        try: start = int(b85decode(pageToken).decode())
        except: start = 0
    else: start = 0

    db = await Database().init()
    g_users, xndc_users = await db.get(table="Users"), await db.get("x0", "Users")
    query = {"nickname": regex_compile(r"{}".format(q))}
    users = [item async for item in xndc_users.find(query).skip(start).limit(size).sort("timestamp", DESCENDING)]  
    
    if len(users) > 0:
        answer = Base.Answer({
            "userProfileList": [
                User.GetUserInfo(await g_users.find_one({"id": item['id']}) | item)
                for item in users
            ],
            "paging": {
                "nextPageToken": b85encode(str(size+start).encode()).decode(),
                "prevPageToken": b85encode(("0" if start - size <= 0 else str(start-size)).encode()).decode()
            },
            "userProfileCount": await xndc_users.count_documents(query)
        }, spent_time=timestamp()-t1)
        await db.close()
        return answer
    else:
        await db.close()
        return Base.Answer({
            "messageList": [],
            "paging": {}
        }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/user-profile/reminder-stat")
async def get_visits(request: Request):
    return Base.Answer({
        "visitorsCount": 0,
        "unreadVisitorsCount": 0
    })

# following 
# /g/s/user-profile/{userId}/joined?start={start}&size={size}
@profile_methods.get("/g/s/user-profile/{uid}/joined")
async def get_user_following(uid, request: Request, start: int = 0, size: int = 25):
    t1 = timestamp()

    db = await Database().init()
    xndcid_table = await db.get("x0", "Users")
    global_table = await db.get(table="Users")
    row = await xndcid_table.find_one({"id": uid})
    following = row['following'][start:start+size]
    following_list = [
        User.GetUserInfo(await global_table.find_one({"id": item}) | await xndcid_table.find_one({"id": item}))
        for item in following
    ]

    await db.close()
    return Base.Answer({
        "userProfileList": following_list
    }, spent_time=timestamp()-t1)

# followers
# /g/s/user-profile/{userId}/member?start={start}&size={size}

@profile_methods.get("/g/s/user-profile/{uid}/member")
async def get_user_followers(uid, request: Request, start: int = 0, size: int = 25):
    t1 = timestamp()
    
    db = await Database().init()
    xndcid_table = await db.get("x0", "Users")
    global_table = await db.get(table="Users")
    row = await xndcid_table.find_one({"id": uid})
    followers = row['whoFollows'][start:start+size]
    followers_list = [
        User.GetUserInfo(await global_table.find_one({"id": item}) | await xndcid_table.find_one({"id": item}))
        for item in followers
    ]

    await db.close()
    return Base.Answer({
        "userProfileList": followers_list
    }, spent_time=timestamp()-t1)

# get wall
# /g/s/user-profile/8cee99d4-1b19-42b5-8e21-7c196dbe0aae/g-comment?size=25&sort=newest

@profile_methods.get("/g/s/user-profile/{uid}/g-comment")
async def get_user_wall(uid, request: Request, start: int = 0, size: int = 25, sort: str = "newest"):
    t1 = timestamp()

    trigger_uid = request.state.session.get('uid')

    def listed(result: dict):
        return list(result.items())

    db = await Database().init()
    xndcid_table = await db.get("x0", "Users")
    global_table = await db.get(table="Users")
    row = await xndcid_table.find_one({"id": uid})
    if sort == "newest":
        all_wall_comments = listed(row['wall'])
        all_wall_comments.reverse()
    elif sort == "vote":
        all_wall_comments = sorted(listed(row['wall']), key=lambda d: len(d[1]["votes"]), reverse=True)
    else:
        all_wall_comments = listed(row['wall'])

    wall_comments = []
    for _comment_id, _comment_info in all_wall_comments:
        if _comment_info['isSubWM'] == False:
            wall_comments.append((_comment_id, _comment_info))

    wall_comments = wall_comments[start:start+size]
    wc_list = [
        await Comments.Parent(item[1], item[0], uid, global_table, xndcid_table, trigger_uid)
        for item in wall_comments
    ]

    await db.close()
    return Base.Answer({
        "commentList": wc_list
    }, spent_time=timestamp()-t1)

# get answers to wall comment
# /g/s/user-profile/8cee99d4-1b19-42b5-8e21-7c196dbe0aae/g-comment/4751702a-0713-483e-8e33-1ffb61f98e64/response?start=0&size=27

@profile_methods.get("/g/s/user-profile/{uid}/g-comment/{commentId}")
@profile_methods.get("/g/s/user-profile/{uid}/g-comment/{commentId}/response")
async def get_user_wall(uid, commentId, request: Request):
    t1 = timestamp()
    
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    db = await Database().init()
    xndcid_table = await db.get("x0", "Users")
    global_table = await db.get(table="Users")
    row = await xndcid_table.find_one({"id": uid})
    all_wall = row['wall']
    comment_thread = all_wall[commentId]['subWMs']
    certain_wall = []
    for _comment_id, _comment_info in all_wall.items():
        if _comment_id in comment_thread:
            certain_wall.append((_comment_id, _comment_info))

    wc_list = [
        await Comments.Son(item[1], item[0], commentId, uid, global_table, xndcid_table, trigger_uid)
        for item in certain_wall
    ]

    await db.close()
    return Base.Answer({
        "commentList": wc_list
    }, spent_time=timestamp()-t1)

# delete message from wall
# /g/s/user-profile/8cee99d4-1b19-42b5-8e21-7c196dbe0aae/g-comment/{commentId}

@profile_methods.delete("/g/s/user-profile/{uid}/g-comment/{commentId}")
async def delete_post_from_wall(request: Request, uid: str, commentId: str):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    if uid == trigger_uid:
        db = await Database().init()
        table = await db.get("x0", "Users")
        user_info = await table.find_one({"id": uid})

        wall = user_info.get('wall')
        if wall.get(commentId):
            unsetDict = {f'wall.{commentId}': ""}
            if len(wall.get(commentId, {}).get("subWMs", [])) > 0:
                for key in commentId.get("subWMs", []):
                    if key in wall.keys():
                        unsetDict.update({ f'wall.{key}': "" })

            await table.update_many(
                {'id': uid },
                { '$unset': unsetDict }
            )

        await db.close()
    return Base.Answer(spent_time=timestamp()-t1)


# post on wall
# /g/s/user-profile/8cee99d4-1b19-42b5-8e21-7c196dbe0aae/g-comment

@profile_methods.post("/g/s/user-profile/{uid}/g-comment")
async def post_on_user_wall(uid, request: Request, start: int = 0, size: int = 25, sort: str = "newest"):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    data = await request.json()
    try:
        if not data['content']:
            raise Exception()
    except Exception as e:
        return Errors.InvalidRequest(timestamp()-t1)

    db = await Database().init()
    xndcid_table = await db.get("x0", "Users")
    global_table = await db.get(table="Users")
    
    commentUid = str(uuid4())
    wm = ModelFabric.Construct(
        Community.WallMessage,
        authorId = trigger_uid,
        content = data['content'],
        mediaList = data.get('mediaList', []),
        isSubWM = True if data.get("respondTo") else False
    )

    if data.get("respondTo"):
        await xndcid_table.update_one(
            {"id": uid},
            {"$push": { f"wall.{data['respondTo']}.subWMs": commentUid }}
        )
        commentObj = await Comments.Son(wm, commentUid, data['respondTo'], uid, global_table, xndcid_table, trigger_uid)
    await xndcid_table.update_one(
        {"id": uid},
        {"$set": { f"wall.{commentUid}": wm }}
    )
    commentObj = await Comments.Parent(wm, commentUid, uid, global_table, xndcid_table, trigger_uid)

    await db.close()
    return Base.Answer({
        "comment": commentObj
    }, spent_time=timestamp()-t1)

# ban
# [POST] /g/s/user-profile/632fac88-f43b-4d4c-8f89-7e8fca65323a/member

@profile_methods.post("/g/s/user-profile/{uid}/ban")
async def ban_user(uid, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    target_user = request.state.session['uid']

    db = await Database().init()
    table = await db.get("x0", "Users")
    gl_table = await db.get(table="Users")
    inited_user = await gl_table.find_one({"id": target_user})
    if inited_user['role'] in [555, '555', 254, '254']:
        await table.update_one(
            {'id': uid },
            { '$set': { 'status': 9 } }
        )
        await gl_table.update_one(
            {'id': uid },
            { '$set': { 'status': 9 } }
        )
        await db.close()
        return Base.Answer(spent_time=timestamp()-t1)
    else:
        await db.close()
        return Errors.NotEnoughRights(spent_time=timestamp()-t1)

# unban
# [POST] /g/s/user-profile/632fac88-f43b-4d4c-8f89-7e8fca65323a/member

@profile_methods.post("/g/s/user-profile/{uid}/unban")
async def unban_user(uid, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    target_user = request.state.session['uid']

    db = await Database().init()
    table = await db.get("x0", "Users")
    gl_table = await db.get(table="Users")
    inited_user = await table.find_one({"id": target_user})
    if inited_user['role'] in [555, '555', 254, '254']:
        await table.update_one(
            {'id': uid },
            { '$set': { 'status': 0 } }
        )
        await gl_table.update_one(
            {'id': uid },
            { '$set': { 'status': 0 } }
        )

        await db.close()
        return Base.Answer(spent_time=timestamp()-t1)
    else:
        await db.close()
        return Errors.NotEnoughRights(spent_time=timestamp()-t1)

# follow
# [POST] /g/s/user-profile/632fac88-f43b-4d4c-8f89-7e8fca65323a/member

@profile_methods.post("/g/s/user-profile/{uid}/member")
async def follow_user(uid, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    suid = request.state.session['uid']

    db = await Database().init()
    table = await db.get("x0", "Users")
    target_user = await table.find_one({"id": uid})
    inited_user = await table.find_one({"id": suid})
    if suid not in target_user['whoFollows'] or uid not in inited_user['following']:
        await table.update_one(
            {'id': uid },
            { '$push': { 'whoFollows': suid } }
        )
        await table.update_one(
            {'id': suid },
            { '$push': { 'following': uid } }
        )

    await db.close()
    return Base.Answer(spent_time=timestamp()-t1)

# unfollow
# [POST] /g/s/user-profile/632fac88-f43b-4d4c-8f89-7e8fca65323a/member

@profile_methods.post("/g/s/user-profile/{uid}/member/{inited_uid}")
async def follow_user(uid: str, inited_uid: str, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    suid = request.state.session['uid']
    if suid != inited_uid:
        return Errors.InvalidRequest(timestamp()-t1)

    db = await Database().init()
    table = await db.get("x0", "Users")
    target_user = await table.find_one({"id": uid})
    inited_user = await table.find_one({"id": suid})
    if suid in target_user['whoFollows'] and uid in inited_user['following']:
        await table.update_one(
            {'id': uid },
            { '$pull': { 'whoFollows': suid } }
        )
        await table.update_one(
            {'id': suid },
            { '$pull': { 'following': uid } }
        )

    await db.close()
    return Base.Answer(spent_time=timestamp()-t1)

@profile_methods.get("/g/s/user-profile/{uid}")
async def get_user_info(uid, request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    db = await Database().init()
    table = await db.get(table="Users")
    row1 = await table.find_one({"id": uid})
    if row1 == None:
        return Errors.AccountNotExist(timestamp()-t1)
    table = await db.get(database="x0", table="Users")
    row2 = await table.find_one({"id": uid})
    if row2 == None:
        return Errors.AccountNotExist(timestamp()-t1)
    await db.close()
    return Base.Answer({
        "userProfile": User.GetUserInfo(row1|row2, triggerUserId=trigger_uid)
    }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/account")
async def get_self_info(request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    uid = request.state.session['uid']

    db = await Database().init()
    table = await db.get(table="Users")
    row1 = await table.find_one({"id": uid})
    if row1 == None:
        return Errors.AccountNotExist(timestamp()-t1)
    table = await db.get(database="x0", table="Users")
    row2 = await table.find_one({"id": uid})
    if row2 == None:
        return Errors.AccountNotExist(timestamp()-t1)
    await db.close()
    return Base.Answer({
        "userProfile": User.GetUserInfo(row1|row2)
    }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/blog")
async def get_user_stories(request: Request, q: Union[str, None] = None):
    t1 = timestamp()

    return Base.Answer({
        "communityInfoMapping": {},
        "paging": {},
        "blogList": []
    }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/community/joined")
async def joined_communities(request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    return Base.Answer({
        "communityList": [] #"communityList": [0]
        ,
        "userInfoInCommunities": {},
        "showStoreBadge": True
    }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/wallet")
async def get_wallet_info(request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    db = await Database().init()
    table = await db.get(table="Users")
    row = await table.find_one({"id": trigger_uid})
    if row == None:
        return Errors.AccountNotExist(timestamp()-t1)
    await db.close()
    return Base.Answer({
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
                "watchedVideoCount": 0
            },
            "totalCoins": int(row['coins']),
            "totalCoinsFloat": row['coins'],
            "adsEnabled": False,
            "totalBusinessCoins": 0,
            "totalBusinessCoinsFloat": 0
        }
    }, spent_time=timestamp()-t1)

@profile_methods.get("/g/s/wallet/setting/ads")
async def get_wallet_ads_info(request: Request):
    t1 = timestamp()
    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']

    db = await Database().init()
    table = await db.get(table="Users")
    row = await table.find_one({"id": trigger_uid})
    if row == None:
        return Errors.AccountNotExist(timestamp()-t1)
    await db.close()
    return Base.Answer({
        "estimatedCoinsEarnedByAds": 0,
        "coinsEarnedByAds": {
            "total": 0,
            "weekly": 0
        }
    }, spent_time=timestamp()-t1)

@profile_methods.post("/g/s/user-profile/{uid}")
async def edit_user_info(uid, request: Request):
    t1 = timestamp()
    data = await request.json()

    if not request.state.session['validsession']:
        return Errors.InvalidSession(timestamp()-t1)

    trigger_uid = request.state.session['uid']
    if trigger_uid != uid:
        return Errors.InvalidRequest(timestamp()-t1)

    preparedQueries = {"modifiedTime": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    if isinstance(data.get("nickname"), str):
        if len(data['nickname'].strip()) == 0: return Errors.InvalidRequest(timestamp()-t1)
        preparedQueries.update({"nickname": data['nickname']})
    if isinstance(data.get("content"), str):
        preparedQueries.update({"description": data['content']})
    if isinstance(data.get("icon"), str):
        if data['icon'].startswith("https://media.altamino.top/"):
            preparedQueries.update({"icon": data['icon']})
    if data.get("extensions"):
        extensions = data['extensions']
        if isinstance(extensions.get("defaultBubbleId"), str):
            pass # [TODO]: implement default bubble id
        if extensions.get("style"):
            style = extensions['style']
            if isinstance(style.get('backgroundColor'), str):
                preparedQueries.update({"backgroundColor": style['backgroundColor']})
            if isinstance(style.get('backgroundMediaList'), list):
                mediaList = [item[1] for item in style['backgroundMediaList']]
                preparedQueries.update({"backgroundMediaList": mediaList})

    if len(preparedQueries) == 0:
        return Base.Answer({"exceptions": "No data provided."})

    db = await Database().init()
    table = await db.get(database="x0", table="Users")

    await table.update_one({"id": uid}, {"$set": preparedQueries})
    row2 = await table.find_one({"id": uid})
    table = await db.get(table="Users")
    row1 = await table.find_one({"id": uid})

    await db.close()
    
    if row1 == None or row2 == None:
        return Errors.AccountNotExist(timestamp()-t1)
        
    return Base.Answer({
        "userProfile": User.GetUserInfo(row1|row2)
    }, spent_time=timestamp()-t1)
