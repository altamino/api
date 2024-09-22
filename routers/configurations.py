from fastapi import APIRouter, Request
from time import time as timestamp
from typing import Union
from uuid import uuid4

# import sys
# sys.path.append('../')
from objects import *
from helpers.routers.cachable import CachableRoute

configurations = APIRouter()
configurations.route_class = CachableRoute


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
                            "screeningRoomEnabled": True,
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
    return Base.Answer({"contentLanguageSettings": {"language": "en"}})


@configurations.get("/g/s/eventlog/profile")
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
    return Base.Answer({"supportedLanguages": ["en"]})


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
                        "https://media.altamino.top/xszXOWaCFjKjTR1UyUuxOdEk9YjCbSQhfJ6BIYfPvjBxHNNJceuiCX5Ht7gjBHM7.jpg",
                        None,
                    ]
                ],
                "primaryColor": "#430e36",
            }
        }
    )


@configurations.get("/g/s/reminder/check")
async def reminder_configs(request: Request):
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    return Base.Answer(
        {
            "reminderCheckResult": {
                "noticesCount": 0,
                "noticesCount2": 0,
                "notificationsCount": 0,
            },
            "treatedNdcIds": [],
            "reminderCheckResultInCommunities": {},
        }
    )


@configurations.get("/g/s/reminder/full-check")
async def full_reminder_configs(request: Request):
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    return Base.Answer({"reminderFullCheckResult": {"hasReminder": False}})


@configurations.get("/g/s/auth/config-v2")
async def some_auth_config(request: Request):
    return Base.Answer({"mobileSignUpProviderList": [8]})


@configurations.post("/g/s/client-config")
async def client_configs(request: Request):
    # t1 = timestamp()
    # data = await request.json()

    return Base.Answer(
        {"clientConfig": {}},
        # spent_time=timestamp()-t1
    )


@configurations.get("/g/s/account/affiliations")
async def affiliations_config(request: Request):
    return Base.Answer({"affiliations": [0]})


@configurations.get("/g/s/auid")
async def auid_check(deviceId: str, request: Request):
    uid = request.state.session.get("uid", str(uuid4()))

    return Base.Answer({"auid": uid})


# BANNER


@configurations.get("/g/s/home/discover/content-modules")
async def modules(request: Request):
    return Base.Answer(
        {
            "contentModuleList": [
                {
                    "createdTime": "2022-06-07T18:45:41Z",
                    "contentPoolId": "en",
                    "moduleType": "CustomizedBannerAdsTop",
                    "status": 0,
                    "style": "BannerSizeTop",
                    "uid": "08c1cd67-b007-48b1-b5c4-bf4ace1f0db1",
                    "moduleName": "Top Banner EN",
                    "contentVariety": 0,
                    "customizable": True,
                    "ext": {"adUnitId": "703920"},
                    "moduleId": "1c4ea74e-b500-4c72-821f-0677a5078bdc",
                    "extensions": None,
                    "userRemovable": False,
                    "isVirtual": False,
                    "contentObjectType": 151,
                    "dataUrl": "/topic/0/feed/banner-ads?moduleId=1c4ea74e-b500-4c72-821f-0677a5078bdc&adUnitId=703920",
                    "displayName": "Banners",
                    "topicLocked": False,
                    "visibility": 1,
                }
            ],
            "showStoreBadge": True,
        }
    )


@configurations.get("/g/s/topic/0/feed/banner-ads")
async def banner(
    request: Request, moduleId: Union[str, None] = None, adUnitId: int = 703920
):
    if moduleId == None:
        return Errors.InvalidRequest()

    return Base.Answer(
        {
            "paging": {},
            "itemList": [
                {
                    "objectId": "2",
                    "imageUrl": "https://media.altamino.top/always-static/welcome.jpg",
                    "adCampaignId": 2,
                    "deepLink": "ndc://community/0",
                    "strategyInfo": '{"scenarioType": "banner-703920", "objectId": "804584", "imageUrl": "https://media.altamino.top/always-static/welcome.jpg", "landingUrl": "ndc://community/0", "reqId": "852e7230-6135-4cd2-89ea-e860417f6c48", "adUnitId": 703920, "uiPos": 3, "objectType": "ad_campaign"}',
                    "objectType": 153,
                },
                {
                    "objectId": "1",
                    "imageUrl": "https://media.altamino.top/always-static/warning.jpg",
                    "adCampaignId": 1,
                    "deepLink": "ndc://membership",
                    "strategyInfo": '{"scenarioType": "banner-703920", "objectId": "804584", "imageUrl": "https://media.altamino.top/always-static/warning.jpg", "landingUrl": "ndc://membership", "reqId": "f41f605a-4d81-4361-b571-19443ce136bf", "adUnitId": 703920, "uiPos": 2, "objectType": "ad_campaign"}',
                    "objectType": 153,
                },
            ],
            "allItemCount": 1,
        }
    )
