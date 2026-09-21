from hashlib import sha256
from typing import Union
from datetime import datetime, timedelta, timezone

from helpers.database.mongo import Database
from helpers.checkins import date_str

from .medialist import MediaList
from .user import User
from .types.users import UserRole

"""
this is top tier bullshit
"""


RANKING_TABLE = [
    {"id": "1", "level": 1, "reputation": 0, "title": "Level 1"},
    {"id": "2", "level": 2, "reputation": 5, "title": "Level 2"},
    {"id": "3", "level": 3, "reputation": 10, "title": "Level 3"},
    {"id": "4", "level": 4, "reputation": 25, "title": "Level 4"},
    {"id": "5", "level": 5, "reputation": 50, "title": "Level 5"},
    {"id": "6", "level": 6, "reputation": 100, "title": "Level 6"},
    {"id": "7", "level": 7, "reputation": 200, "title": "Level 7"},
    {"id": "8", "level": 8, "reputation": 500, "title": "Level 8"},
    {"id": "9", "level": 9, "reputation": 1000, "title": "Level 9"},
    {"id": "10", "level": 10, "reputation": 2000, "title": "Level 10"},
    {"id": "11", "level": 11, "reputation": 3000, "title": "Level 11"},
    {"id": "12", "level": 12, "reputation": 5000, "title": "Level 12"},
    {"id": "13", "level": 13, "reputation": 7000, "title": "Level 13"},
    {"id": "14", "level": 14, "reputation": 10000, "title": "Level 14"},
    {"id": "15", "level": 15, "reputation": 20000, "title": "Level 15"},
    {"id": "16", "level": 16, "reputation": 40000, "title": "Level 16"},
    {"id": "17", "level": 17, "reputation": 60000, "title": "Level 17"},
    {"id": "18", "level": 18, "reputation": 100000, "title": "Level 18"},
    {"id": "19", "level": 19, "reputation": 250000, "title": "Level 19"},
    {"id": "20", "level": 20, "reputation": 500000, "title": "Level 20"},
]


MODULE_DEFAULTS = {
    "post": True,
    "chat": True,
    "ranking": True,
    "leaderboard": True,
    "featured": True,
    "catalog": True,
    "sharedFolder": False,
    "influencer": False,
    "topicCategories": False,
    "externalContent": False,
}


def _mod_enabled(mods: dict, name: str) -> bool:
    m = mods.get(name)
    if isinstance(m, dict):
        return bool(m.get("enabled", MODULE_DEFAULTS.get(name, True)))
    if isinstance(m, bool):
        return m
    return MODULE_DEFAULTS.get(name, True)


_DEFAULT_PAGES = [
    (
        {
            "url": "ndc://leaderboards",
            "alias": None,
            "id": "leaderboards-default",
            "parentId": None,
            "originalTitle": None,
        },
        "ranking",
    ),
    (
        {
            "url": "ndc://featured",
            "alias": None,
            "id": "featured-default",
            "parentId": None,
            "originalTitle": None,
        },
        "featured",
    ),
    (
        {
            "url": "ndc://my-chats",
            "alias": None,
            "id": "chat-default",
            "parentId": None,
            "originalTitle": None,
        },
        "chat",
    ),
    (
        {
            "url": "ndc://public-chats",
            "alias": None,
            "id": "chat-public-chats",
            "parentId": None,
            "originalTitle": None,
        },
        "chat",
    ),
    (
        {
            "url": "ndc://latest-posts",
            "alias": None,
            "id": "post-latest-feed",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://following-feed",
            "alias": None,
            "id": "post-following-feed",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://image-posts",
            "alias": None,
            "id": "post-image-posts",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://blogs",
            "alias": None,
            "id": "post-blogs",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://questions",
            "alias": None,
            "id": "post-questions",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://polls",
            "alias": None,
            "id": "post-polls",
            "parentId": None,
            "originalTitle": None,
        },
        "post",
    ),
    (
        {
            "url": "ndc://catalog",
            "alias": None,
            "id": "catalog-default",
            "parentId": None,
            "originalTitle": None,
        },
        "catalog",
    ),
    (
        {
            "url": "ndc://shared-folder",
            "alias": None,
            "id": "shared-folder",
            "parentId": None,
            "originalTitle": None,
        },
        "sharedFolder",
    ),
    (
        {
            "url": "ndc://blog-categories",
            "alias": None,
            "id": "topic-categories-default",
            "parentId": None,
            "originalTitle": None,
        },
        "topicCategories",
    ),
    (
        {
            "url": "ndc://guidelines",
            "alias": None,
            "id": "guidelines",
            "parentId": None,
            "originalTitle": None,
        },
        None,
    ),
]


def _build_pages(mods: dict, conf: dict) -> dict:
    default_list = [
        page
        for page, gate in _DEFAULT_PAGES
        if gate is None or _mod_enabled(mods, gate)
    ]
    return {
        "defaultList": conf.get("pageDefaultList", default_list),
        "customList": conf.get("pageCustomList", []),
    }


def _build_appearance(conf: dict) -> dict:
    return {
        "leftSidePanel": {
            "style": {
                "iconColor": conf.get("sidepanelIconColor"),
            },
            "navigation": {
                "level1": conf.get(
                    "sidepanelTopNav",
                    [
                        {"id": "guidelines"},
                        {"id": "chat-default"},
                        {"id": "chat-public-chats"},
                        {"id": "catalog-default"},
                    ],
                ),
                "level2": conf.get("sidepanelBottomNav", []),
            },
        },
        "homePage": {
            "navigation": conf.get(
                "homepageNav",
                [
                    {"id": "guidelines"},
                    {"id": "featured-default", "isStartPage": True},
                    {"id": "post-latest-feed"},
                    {"id": "chat-public-chats"},
                ],
            ),
        },
    }


def _mod_field(mods: dict, name: str, field: str, default):
    m = mods.get(name)
    if isinstance(m, dict):
        return m.get(field, default)
    return default


async def _get_community_head_list(table, ndcId: int, agent_id: str) -> list:
    cursor = table.find({"role": {"$in": [UserRole.Agent, UserRole.Leader]}})
    heads = []
    async for u in cursor:
        heads.append(User.OwnNonSensetiveProfile(u, ndcId))
    return heads


VALID_STATUSES_EXCLUDE = [9, 11]
ACTIVITY_WINDOW_DAYS = 7
ACTIVE_TIME_THRESHOLD_SECONDS = 300


EXPECTED_BASE = 0.92 
EXPECTED_DECAY = 0.265 
EXPECTED_MIN = 0.05 
EXPECTED_MAX = 0.60 

def _expected_active_ratio(total: int) -> float:
    raw = EXPECTED_BASE * (total ** -EXPECTED_DECAY)
    return max(EXPECTED_MIN, min(EXPECTED_MAX, raw))


HEAT_AT_EXPECTED = 0.70
OVERPERFORM_CAP = 2.5
MIN_MEMBERS_FULL_TRUST = 8

def _ratio_to_heat(ratio: float, expected: float) -> float:
    r = ratio / expected
    if r <= 1.0:
        return HEAT_AT_EXPECTED * r
    over = (r - 1.0) / (OVERPERFORM_CAP - 1.0)
    return HEAT_AT_EXPECTED + (1.0 - HEAT_AT_EXPECTED) * min(over, 1.0)


async def _compute_community_heat(table, tz_offset_days: int = 0) -> float:
    now_local = datetime.now(timezone.utc) + timedelta(days=tz_offset_days)
    recent_days = [
        date_str(now_local - timedelta(days=i)) for i in range(ACTIVITY_WINDOW_DAYS)
    ]

    total_valid = await table.count_documents(
        {"status": {"$nin": VALID_STATUSES_EXCLUDE}}
    )
    if total_valid == 0:
        return 0.0

    pipeline = [
        {
            "$match": {
                "status": {"$nin": VALID_STATUSES_EXCLUDE},
                "activeTime": {"$exists": True, "$ne": {}},
            }
        },
        {"$addFields": {"_activeTimeArr": {"$objectToArray": "$activeTime"}}},
        {
            "$addFields": {
                "_recentActiveSeconds": {
                    "$sum": {
                        "$map": {
                            "input": {
                                "$filter": {
                                    "input": "$_activeTimeArr",
                                    "as": "entry",
                                    "cond": {"$in": ["$$entry.k", recent_days]},
                                }
                            },
                            "as": "entry",
                            "in": "$$entry.v",
                        }
                    }
                }
            }
        },
        {"$match": {"_recentActiveSeconds": {"$gte": ACTIVE_TIME_THRESHOLD_SECONDS}}},
        {"$count": "activeCount"},
    ]

    result = await table.aggregate(pipeline).to_list(length=1)
    active_count = result[0]["activeCount"] if result else 0
    if active_count == 0:
        return 0.0

    ratio = active_count / total_valid
    expected = _expected_active_ratio(total_valid)
    heat = _ratio_to_heat(ratio, expected)

    # мелкие соо: 2 из 3 не должны давать максимум — нет статистики
    if total_valid < MIN_MEMBERS_FULL_TRUST:
        heat *= total_valid / MIN_MEMBERS_FULL_TRUST

    return round(max(0.0, min(heat, 1.0)), 2)

class Communities:
    @staticmethod
    def ModuleInfo(module_data: dict):
        return {
            "enabled": module_data.get("enabled", True),
            "privilege": {
                "type": module_data.get("accessType", 1),
                "minLevel": module_data.get("minLevel", 3),
            },
        }

    @staticmethod
    async def Info(
        ndcId: int | dict,
        connection=None,
        trigger_uid: Union[str, None] = None,
    ):
        if not connection:
            connection = await Database().init()
        if isinstance(ndcId, int) or isinstance(ndcId, str):
            comms = connection.get(table="Communities")
            data = await comms.find_one({"id": ndcId})
        else:
            data = ndcId
            ndcId = data["id"]

        table = connection.get(f"x{ndcId}", "Users")
        host_xndcId = await table.find_one({"id": data["agent"]})
        agent = User.OwnNonSensetiveProfile(host_xndcId, ndcId) if host_xndcId else None
        community_head_list =  await _get_community_head_list(table, ndcId, data["agent"]) #it's work, but idk why app need it, so i will not add it for now
        community_heat = await _compute_community_heat(table)

        membershipStatus = 0
        if trigger_uid and (
            trigger_uid == data.get("agent")
            or trigger_uid in data.get("memberList", [])
        ):
            membershipStatus = 1

        conf = data.get("configuration", {})
        mods = conf.get("modules", {})
        adv = conf.get("advancedSettings", {})

        chat_mod = mods.get("chat", {})
        blog_mod = mods.get("blog", {})
        poll_mod = mods.get("poll", {})
        image_mod = mods.get("image", {})
        question_mod = mods.get("question", {})
        catalog_mod = mods.get("catalog", {})
        quiz_mod = mods.get("quiz", {})

        av = chat_mod.get("avChat", {}) if isinstance(chat_mod, dict) else {}

        return {
            "agent": agent,
            "ndcId": ndcId,
            "name": data["name"],
            "link": "http://altamino.top/c/" + data["aminoId"],
            "endpoint": data["aminoId"],
            "membershipStatus": membershipStatus,
            "icon": data["icon"],
            "status": data["status"],
            "membersCount": data.get("membersCount", 0),
            "joinType": data.get("joinType", 0),
            "content": data.get("description", ""),
            "tagline": data.get("tagline", ""),
            "templateId": data.get("templateId", 9),
            "communityHeat": community_heat,  # data.get("heat", 0.00),
            "extensions": {},
            "createdTime": data.get("createdTime", "2023-01-01T12:00:00Z"),
            "modifiedTime": data.get("modifiedTime", "2023-01-01T12:00:00Z"),
            "userAddedTopicList": data.get("userAddedTopicList", []),
            "searchable": data.get("searchable", True),
            "influencerList": data.get("influencerList", []),
            "primaryLanguage": data.get("lang", "en"),
            "isStandaloneAppDeprecated": False,
            "listedStatus": data.get("listedStatus", 2),
            "probationStatus": data.get("probationStatus", 0),
            "hidden": data.get("hidden", False),
            "themePack": {
                "themeColor": data.get("themeColor", "#1B1C43"),
                "themePackUrl": data.get("themeUrl"),
                "themePackHash": data.get(
                    "themeHash",
                    sha256(
                        data.get("themeUrl", "https://trolo.lol/example").encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                ),
                "themePackRevision": data.get("themeRevision"),
            },
            "mediaList": data.get("mediaList", []),
            "isStandaloneAppMonetizationEnabled": False,
            "communityHeadList": community_head_list,
            "activeInfo": {},
            "configuration": {
                "page": _build_pages(mods, conf),
                "module": {
                    "post": {
                        "enabled": _mod_enabled(mods, "post"),
                        "postType": {
                            "publicChatRooms": Communities.ModuleInfo(chat_mod),
                            "blog": Communities.ModuleInfo(blog_mod),
                            "poll": Communities.ModuleInfo(poll_mod),
                            "image": Communities.ModuleInfo(image_mod),
                            "question": Communities.ModuleInfo(question_mod),
                            "catalogEntry": Communities.ModuleInfo(catalog_mod),
                            "quiz": Communities.ModuleInfo(quiz_mod),
                        },
                    },
                    "chat": {
                        "enabled": _mod_enabled(mods, "chat"),
                        "spamProtectionEnabled": _mod_field(
                            mods, "chat", "spamProtectionEnabled", True
                        ),
                        "avChat": {
                            "screeningRoomEnabled": av.get(
                                "screeningRoomEnabled", False
                            ),
                            "audioEnabled": av.get("audioEnabled", True),
                            "videoEnabled": av.get("videoEnabled", False),
                            "audio2Enabled": av.get("audio2Enabled", True),
                        },
                        "publicChat": Communities.ModuleInfo(chat_mod),
                    },
                    "ranking": {
                        "enabled": _mod_enabled(mods, "ranking"),
                        "leaderboardEnabled": _mod_enabled(mods, "leaderboard"),
                        "rankingTable": conf.get("rankingTable", RANKING_TABLE),
                        "leaderboardList": conf.get("leaderboardList", []),
                    },
                    "featured": {
                        "enabled": _mod_enabled(mods, "featured"),
                        "postEnabled": _mod_field(
                            mods,
                            "featured",
                            "postEnabled",
                            _mod_enabled(mods, "featured"),
                        ),
                        "memberEnabled": _mod_field(
                            mods,
                            "featured",
                            "memberEnabled",
                            _mod_enabled(mods, "featured"),
                        ),
                        "publicChatRoomEnabled": _mod_field(
                            mods,
                            "featured",
                            "publicChatRoomEnabled",
                            _mod_enabled(mods, "chat"),
                        ),
                        "layout": _mod_field(mods, "featured", "layout", 1),
                    },
                    "catalog": {
                        "enabled": _mod_enabled(mods, "catalog"),
                        "curationEnabled": _mod_field(
                            mods,
                            "catalog",
                            "curationEnabled",
                            _mod_enabled(mods, "catalog"),
                        ),
                    },
                    "sharedFolder": {
                        "enabled": _mod_enabled(mods, "sharedFolder"),
                        "uploadPrivilege": _mod_field(
                            mods, "sharedFolder", "uploadPrivilege", 2
                        ),
                        "albumManagePrivilege": _mod_field(
                            mods, "sharedFolder", "albumManagePrivilege", 2
                        ),
                    },
                    "influencer": {
                        "enabled": _mod_enabled(mods, "influencer"),
                        "maxVipNumbers": _mod_field(
                            mods, "influencer", "maxVipNumbers", 12
                        ),
                        "maxVipMonthlyFee": _mod_field(
                            mods, "influencer", "maxVipMonthlyFee", 500
                        ),
                        "lock": _mod_field(mods, "influencer", "lock", False),
                    },
                    "topicCategories": {
                        "enabled": _mod_enabled(mods, "topicCategories"),
                    },
                    "externalContent": {
                        "enabled": _mod_enabled(mods, "externalContent"),
                    },
                },
                "appearance": _build_appearance(conf),
            },
            "advancedSettings": {
                "pollMinFullBarVoteCount": adv.get("pollMinFullBarVoteCount", 10),
                "welcomeMessageEnabled": conf.get("welcomeMessageEnabled", False),
                "welcomeMessageText": conf.get("welcomeMessage", ""),
                "catalogEnabled": _mod_enabled(mods, "catalog"),
                "defaultRankingTypeInLeaderboard": adv.get(
                    "defaultRankingTypeInLeaderboard", 1
                ),
                "frontPageLayout": conf.get("frontPageLayout", 1),
            },
            "promotionalMediaList": [MediaList.Item(data["coverUrl"])]
            if "coverUrl" in data
            else None,
        }

    """
    [TODO]
    configuration!
    """

    """
    [NOTE]
    This is what we need to implement later.
    Here are real examples what server sends.

    userAddedTopicList:
    {
      "topicId": 17328,
      "style": {
        "backgroundColor": "#ECCA41"
      },
      "name": "Аниме"
    }

    influencerList:
    basically, user with influencerInfo obj:
    {
      "pinned": false,
      "createdTime": "2024-05-01T21:53:14Z",
      "fansCount": 179,
      "monthlyFee": 20
    }

    themePack:
    wtf is hash and how it calculated
    {
        "themeColor": "#34754e",
        "themePackHash": "ea6f312f63cb8fedbe2145f7967d39cb", # ???
        "themePackRevision": 130,
        "themePackUrl": "http://theme.aminoapps.com/x156542274-rev130.ndthemepack"
    }

    communityHeadList:
    basically list with all admins there
    idk really why they need to do it, will not
    add it for now

    extensions:
    also idk why we need it for now
    {
        "communityNameAliases": "Anime,Аниме",
        "iTagIdList": [
            100006
        ]
    }
    """
