from time import time as timestamp

from fastapi import APIRouter, Request

from helpers.routers.cachable import CachableRoute
from objects import Base, Errors

mock = APIRouter()
mock.route_class = CachableRoute


@mock.get("/g/s/persona/profile/basic")
async def personabasic_mock(request: Request):
    if not request.state.session["validsession"]:
        return Errors.InvalidSession()

    return Base.Answer(
        {
            "basicProfile": {
                "auid": request.state.session["uid"],
                "age": 20,
                "gender": 1,
                "country_code": "NL",
                "dateOfBirth": 731589,
            }
        }
    )


@mock.get("/g/s/coupon/new-user-coupon")
async def newusercoupon_mock(request: Request):
    return Base.Answer({"couponMappingList": []})


@mock.get("/g/s/account/{userId}/mission-set")
async def mission_set_mock(request: Request):
    return Base.Answer(
        {
            "missionSet": {
                "reviewUs": {"completedTime": "2023-09-11T12:37:12Z"},
                "checkInTwoWeeks": {"completedTime": "2023-09-11T12:36:39Z"},
                "invitedOneFriend": {"completedTime": "2023-09-11T12:36:39Z"},
                "followInstagram": {"completedTime": "2023-09-11T12:36:39Z"},
                "downloadAminoMaster": {"completedTime": "2023-09-11T12:36:39Z"},
            }
        }
    )


@mock.get("/g/s/user-profile/{userId}/compose-eligible-check")
async def compose_eligible_check_mock(
    request: Request, objectType: str | None = None, objectSubtype: str | None = None
):
    t1 = timestamp()

    if not isinstance(objectType, str) and not isinstance(objectSubtype, str):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    oT_allowed = ["chat-thread"]
    osT_allowed = ["public"]
    if objectType not in oT_allowed or objectSubtype not in osT_allowed:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    return Base.Answer(spent_time=timestamp() - t1)
