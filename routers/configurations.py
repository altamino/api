from typing import Union
from uuid import uuid4
from time import time as timestamp
from helpers.functions import calculate_page_tokens, parse_page_token
from fastapi import APIRouter, Request

from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.config import Config
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors, Communities
from json import dumps

configurations = APIRouter()
configurations.route_class = CachableRoute


@configurations.post("/g/s/safe-browsing")
@configurations.post("/x{ndcId}/s/safe-browsing")
async def safe_browsing(request: Request, ndcId: int = 0):
    data = await request.json()
    url = data.get("url")
    if url is None:
        return Errors.InvalidRequest()

    return Base.Answer({})


@configurations.get("/g/s/community/configuration")
async def global_configs(request: Request):
    return Base.Answer(
        {
            "configuration": {
                "appearance": {},
                "page": {},
                "module": {
                    "post": {
                        "enabled": True,
                        "postType": {
                            "screeningRoom": {
                                "privilege": {"type": 5, "minLevel": 100},
                                "enabled": True,
                            },
                            "story": {"privilege": {"type": 1}, "enabled": True},
                            "liveMode": {
                                "privilege": {"type": 5, "minLevel": 100},
                                "enabled": True,
                            },
                            "publicChatRooms": {
                                "privilege": {"type": 5, "minLevel": 100},
                                "enabled": True,
                            },
                        },
                    },
                    "chat": {
                        "enabled": True,
                        "spamProtectionEnabled": True,
                        "avChat": {
                            "screeningRoomEnabled": False,
                            "audioEnabled": True,
                            "videoEnabled": False,
                            "audio2Enabled": True,
                        },
                        "publicChat": {
                            "privilege": {"type": 5, "minLevel": 100},
                            "enabled": True,
                        },
                    },
                },
                "general": {"videoUploadPolicy": 1},
            }
        }
    )


@configurations.get("/g/s/client-config/content-language-settings")
async def lang_configs(request: Request):
    uid = request.state.session.get("uid", str(uuid4()))

    db = await Database().init()
    table = db.get(table="Users")
    row = await table.find_one({"id": uid})
    if row is None:
        return Base.Answer({"contentLanguageSettings": {"language": "en"}})

    db.close()
    return Base.Answer({"contentLanguageSettings": {"language": row.get("lang", "en")}})


@configurations.get("/g/s/eventlog/profile")
@validauth_required
async def eventlog_config(request: Request):
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    uid = request.state.session.get("uid", str(uuid4()))

    return Base.Answer(
        {
            "globalStrategyInfo": '{"expIds": "landing_option_exp:EXP,community_members_common_channel:RESERVED,coupon_push:CONTROL,user_vector_community_similarity_channel:EXP,retention_sr_push:CONTROL,chat_members_common_channel:CONTROL,community_tab_exp:CONTROL"}',
            "uid": uid,
            "contentLanguage": "en",
            "signUpStrategy": 2,
            "landingOption": 4,
            "needsBirthDateUpdate": False,
            "interestPickerStyle": 2,
            "showStoreBadge": False,
            "auid": uid,
            "needTriggerInterestPicker": False,
            "participatedExperiments": {
                "retentionSrPush": 1,
                "couponPush": 2,
                "communityMembersCommonChannel": 3,
                "chatMembersCommonChannel": 1,
                "landingOptionExp": 2,
                "communityTabExp": 1,
                "userVectorCommunitySimilarityChannel": 2,
            },
        }
    )


@configurations.get("/g/s/community-collection/supported-languages")
async def supported_languages_config(request: Request):
    return Base.Answer({"supportedLanguages": Config.LANG_SEGMENTS})


@configurations.get("/g/s/membership")
async def membership_config(request: Request):
    return Base.Answer(
        {
            "accountMembershipEnabled": True,
            "hasAnyAppleSubscription": False,
            "hasAnyAndroidSubscription": False,
            "membership": None,
            "premiumFeatureEnabled": True,
        }
    )


@configurations.get("/g/s/client-config/appearance-settings")
async def appearance_configs(request: Request):
    return Base.Answer(
        {
            "appearanceSettings": {
                "backgroundMediaList": [
                    [
                        100,
                        "https://media.altamino.top/always-static/global-background.jpg",
                        None,
                    ]
                ],
                "primaryColor": "#000000",
            }
        }
    )


@configurations.get("/g/s/user-profile/reminder-stat")
@configurations.get("/x{ndcId}/s/user-profile/reminder-stat")
@validauth_required
async def reminder_stats(request: Request, ndcId: int = 0):
    return Base.Answer()


@configurations.get("/g/s/reminder/full-check")
@configurations.get("/x{ndcId}/s/reminder/full-check")
@validauth_required
async def full_reminder_configs(request: Request, ndcId: int = 0):
    return Base.Answer({"reminderFullCheckResult": {"hasReminder": False}})


@configurations.get("/g/s/auth/config-v2")
async def some_auth_config(request: Request):
    return Base.Answer(
        {"mobileSignUpProviderList": []}
    )  # [8] <- allow phone register & login


@configurations.post("/g/s/client-config")
async def client_configs(request: Request):
    # t1 = timestamp()
    # data = await request.json()

    return Base.Answer(
        {"clientConfig": {}},
        # spent_time=timestamp()-t1
    )


@configurations.get("/g/s/auid")
async def auid_check(deviceId: str, request: Request):
    uid = request.state.session.get("uid", str(uuid4()))

    return Base.Answer({"auid": uid})


"""
{
"createdTime": "2022-06-07T18:45:41Z",
"contentPoolId": "en",
"moduleType": "TrendingTopic",
"status": 0,
"style": "GridTopicCard",
"uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
"moduleName": "Trending Topics",
"contentVariety": 0,
"customizable": False,
"moduleId": "3c4ea74e-b500-4c72-821f-0677a5078bde",
"extensions": None,
"userRemovable": False,
"isVirtual": False,
"contentObjectType": 128,
"dataUrl": "/topic/0/feed/topic?moduleId=3c4ea74e-b500-4c72-821f-0677a5078bde",
"displayName": "Trending",
"topicLocked": False,
"visibility": 1,
},
"""


# TODO
@configurations.put("/g/s/home/discover/content-modules")
async def edit_discover_modules(request: Request):
    return Base.Answer()


@configurations.get("/g/s/home/discover/content-modules")
async def discover_modules(request: Request):
    return Base.Answer(
        {
            "contentModuleList": [
                {
                    "createdTime": "2022-06-07T18:45:41Z",
                    "contentPoolId": "en",
                    "moduleType": "CustomizedBannerAds",
                    "status": 0,
                    "style": "BannerSizeTop",
                    "uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
                    "moduleName": "Top Banner",
                    "contentVariety": 0,
                    "customizable": True,
                    "ext": {"adUnitId": "703920"},
                    "moduleId": "1c4ea74e-b500-4c72-821f-0677a5078bdc",
                    "extensions": None,
                    "userRemovable": False,
                    "isVirtual": False,
                    "contentObjectType": 151,
                    "dataUrl": "/topic/0/feed/banner-ads?moduleId=1c4ea74e-b500-4c72-821f-0677a5078bdc",
                    "displayName": "Banners",
                    "topicLocked": False,
                    "visibility": 1,
                },
                {
                    "createdTime": "2022-06-07T18:45:41Z",
                    "contentPoolId": "en",
                    "moduleType": "RecommendedCommunities",
                    "status": 0,
                    "style": "GeneralCommunityCard",
                    "uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
                    "moduleName": "Team's Picks",
                    "contentVariety": 0,
                    "customizable": False,
                    "moduleId": "5c4ea74e-b500-4c72-821f-0677a5078be0",
                    "extensions": None,
                    "userRemovable": False,
                    "isVirtual": False,
                    "contentObjectType": 16,
                    "dataUrl": "/topic/0/feed/topic?moduleId=5c4ea74e-b500-4c72-821f-0677a5078be0",
                    "displayName": "Team's Picks",
                    "topicLocked": False,
                    "visibility": 1,
                },
                {
                    "createdTime": "2022-06-07T18:45:41Z",
                    "contentPoolId": "en",
                    "moduleType": "RecommendedCommunities",
                    "status": 0,
                    "style": "GeneralCommunityCard",
                    "uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
                    "moduleName": "Recommended Communities",
                    "contentVariety": 0,
                    "customizable": False,
                    "moduleId": "2c4ea74e-b500-4c72-821f-0677a5078bdd",
                    "extensions": None,
                    "userRemovable": False,
                    "isVirtual": False,
                    "contentObjectType": 16,
                    "dataUrl": "/topic/0/feed/community?moduleId=2c4ea74e-b500-4c72-821f-0677a5078bdd",
                    "displayName": "Recommended Communities",
                    "topicLocked": False,
                    "visibility": 1,
                },
                {
                    "createdTime": "2022-06-07T18:45:41Z",
                    "contentPoolId": "en",
                    "moduleType": "PopularStories",
                    "status": 0,
                    "style": "GeneralStoryCard",
                    "uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
                    "moduleName": "Popular Stories",
                    "contentVariety": 0,
                    "customizable": False,
                    "moduleId": "4c4ea74e-b500-4c72-821f-0677a5078bdf",
                    "extensions": None,
                    "userRemovable": False,
                    "isVirtual": False,
                    "contentObjectType": 1,
                    "contentObjectSubtype": 9,
                    "dataUrl": "/topic/0/feed/story?moduleId=4c4ea74e-b500-4c72-821f-0677a5078bdf",
                    "displayName": "Popular Stories",
                    "topicLocked": False,
                    "visibility": 1,
                },
            ],
            "showStoreBadge": False,
        }
    )


@configurations.get("/g/s/topic/0/feed/community")
async def feed_community(
    request: Request,
    moduleId: Union[str, None] = None,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    if moduleId is None:
        return Errors.InvalidRequest()

    t1 = timestamp()
    if pageToken:
        start = parse_page_token(pageToken, start)

    uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        table = db.get(table="Communities")
        query = {"hidden": {"$ne": True}, "aminoId": {"$nin": ["g"]}}

        total_count = await table.count_documents(query)

        pipeline = [
            {"$match": query},
            {"$sample": {"size": size}},
        ]
        items = [item async for item in table.aggregate(pipeline)]
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


# temp
@configurations.get("/g/s/topic/0/feed/topic")
async def feed_topic(
    request: Request,
    moduleId: Union[str, None] = None,
    start: int = 0,
    size: int = 15,
    pageToken: str | None = None,
):
    if moduleId is None:
        return Errors.InvalidRequest()

    t1 = timestamp()
    if pageToken:
        start = parse_page_token(pageToken, start)

    uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        table = db.get(table="Communities")
        query = {"isSelected": True, "hidden": {"$ne": True}}

        total_count = await table.count_documents(query)
        items = [
            item
            async for item in table.find(query)
            .sort([("pickOrder", 1), ("id", 1)])
            .skip(start)
            .limit(size)
        ]
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


@configurations.get("/g/s/topic/0/feed/story")
async def feed_story(
    request: Request,
    moduleId: Union[str, None] = None,
    start: int = 0,
    size: int = 15,
):
    if moduleId is None:
        return Errors.InvalidRequest()

    t1 = timestamp()
    return Base.Answer(
        {
            "paging": {},
            "itemList": [],
            "allItemCount": 0,
        },
        spent_time=timestamp() - t1,
    )


_BANNER_MODULE_ID = "1c4ea74e-b500-4c72-821f-0677a5078bdc"
_DEFAULT_BANNERS = [
    (
        "https://media.altamino.top/always-static/welcome.jpg",
        "",
        "https://t.me/altamino",
    ),
    (
        "https://media.altamino.top/always-static/warning.jpg",
        "",
        "https://github.com/altamino",
    ),
]


def _banner_item(
    position: int, image_url: str, landing_url: str, deep_link: str = "ndc://e"
) -> dict:
    n = position + 1
    return {
        "objectId": str(n),
        "imageUrl": image_url,
        "adCampaignId": n,
        "deepLink": deep_link,
        "strategyInfo": dumps(
            {
                "scenarioType": "banner-703920",
                "objectId": "804584",
                "imageUrl": image_url,
                "landingUrl": landing_url,
                "reqId": str(uuid4()),
                "adUnitId": 703920,
                "uiPos": n,
                "objectType": "ad_campaign",
            }
        ),
        "objectType": 153,
    }


@configurations.get("/g/s/topic/0/feed/banner-ads")
async def banner(
    request: Request, moduleId: Union[str, None] = None, adUnitId: int = 703920
):
    if moduleId is None:
        return Errors.InvalidRequest()
    if moduleId != _BANNER_MODULE_ID:
        return Errors.DataNotExist()

    try:
        lang = str(request.state.lang or "en")
    except Exception:
        lang = "en"
    lang = lang.strip()
    langs = list({lang, lang.lower(), lang.lower().replace("_", "-").split("-")[0]})

    pairs = _DEFAULT_BANNERS
    db = await Database().init()
    try:
        table = db.get(table="DiscoverBanners")
        if await table.count_documents({}) > 0:
            flt = {
                "enabled": {"$ne": False},
                "$or": [
                    {"segment": {"$in": ["all", *langs]}},
                    {"segment": {"$exists": False}},
                ],
            }
            rows = [b async for b in table.find(flt).sort("order", 1)]
            pairs2 = [
                (
                    b.get("imageUrl", ""),
                    b.get("landingUrl", ""),
                    b.get("deepLink") or "ndc://e",
                )
                for b in rows
            ]
            if pairs2:
                pairs = pairs2
    finally:
        db.close()

    items = [
        _banner_item(i, img, link, deepLink)
        for i, (img, link, deepLink) in enumerate(pairs)
    ]
    return Base.Answer({"paging": {}, "itemList": items, "allItemCount": len(items)})
