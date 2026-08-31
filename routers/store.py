from time import time as timestamp

from fastapi import APIRouter, Request

from helpers.decorators.validauth import validauth_required
from helpers.routers.cachable import CachableRoute
from helpers.store import build_store_items_response
from objects import Base, Errors
from objects.types.store import StoreItemType
from services.store import StoreService

store = APIRouter()
store.route_class = CachableRoute


def _uid(request: Request) -> str:
    return request.state.session["uid"]


def _paging(request: Request, default_size: int = 25) -> tuple[int, int]:
    start = int(request.query_params.get("start", 0))
    size = int(request.query_params.get("size", default_size))
    return start, size


@store.get("/x{ndcId}/s/store/items")
@store.get("/g/s/store/items")
@validauth_required
async def get_store_items(request: Request, ndcId: int = 0):
    t1 = timestamp()
    group_id = request.query_params.get("sectionGroupId", "avatar-frame")
    start, size = _paging(request)

    async with await StoreService.create(_uid(request), ndcId) as svc:
        items = await svc.list_items(group_id, start, size)
        storeSection = StoreItemType.SECTION_META.get("group_id", {}).get("objectType")

    return Base.Answer(
        build_store_items_response(items, storeSection), spent_time=timestamp() - t1
    )


"""

{
  "frameId": "d7360ef5-fcb5-478d-abbe-ea321411c024",
  "applyToAll": 1,
  "timestamp": 1785092732365
}
"""


@store.post("/g/s/avatar-frame/apply")
@store.post("/x{ndcId}/s/avatar-frame/apply")
@validauth_required
async def apply_avatar_frame(request: Request, ndcId: int = 0):
    t1 = timestamp()
    try:
        data = await request.json()
        frame_id = data.get("frameId")
        apply_to_all = int(data.get("applyToAll", 0)) == 1
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    # [note] in case of default frame w/ None id

    async with await StoreService.create(_uid(request), ndcId) as svc:
        ok = await svc.apply_avatar_frame(frame_id, apply_to_all)

    if not ok:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(spent_time=timestamp() - t1)


@store.get("/x{ndcId}/s/avatar-frame/{frameId}")
@store.get("/g/s/avatar-frame/{frameId}")
@validauth_required
async def get_avatar_frame(request: Request, frameId: str, ndcId: int = 0):
    t1 = timestamp()
    async with await StoreService.create(_uid(request), ndcId) as svc:
        payload = await svc.get_avatar_frame(frameId)

    if payload is None:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(payload, spent_time=timestamp() - t1)


@store.post("/x{ndcId}/s/store/purchase")
@store.post("/g/s/store/purchase")
@validauth_required
async def store_purchase(request: Request, ndcId: int = 0):
    t1 = timestamp()
    try:
        data = await request.json()
        object_id = data["objectId"]
        object_type = int(data["objectType"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    async with await StoreService.create(_uid(request), ndcId) as svc:
        result = await svc.purchase(object_id, object_type)

    if not result.ok:
        if result.error_code == "invalid":
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        return Errors.Custom(
            result.error_code,
            result.error_message,
            spent_time=timestamp() - t1,
            lang=request.state.lang,
        )

    return Base.Answer({"storeItem": result.store_item}, spent_time=timestamp() - t1)


@store.get("/g/s/store/sections")
@store.get("/x{ndcId}/s/store/sections")
@validauth_required
async def storesections(request: Request, ndcId: int = 0):
    t1 = timestamp()
    raw = request.query_params.get("storeSectionGroupIds", "")
    wanted = [x.strip() for x in raw.split(",") if x.strip()] or list(
        StoreItemType.SECTION_META
    )

    async with await StoreService.create(_uid(request), ndcId) as svc:
        section_list = await svc.sections(wanted)

    return Base.Answer({"storeSectionList": section_list}, spent_time=timestamp() - t1)


@store.get("/x{ndcId}/s/chat/chat-bubble/{bubbleId}")
@store.get("/g/s/chat/chat-bubble/{bubbleId}")
@validauth_required
async def get_chat_bubble(request: Request, bubbleId: str, ndcId: int = 0):
    t1 = timestamp()
    async with await StoreService.create(_uid(request), ndcId) as svc:
        payload = await svc.get_chat_bubble(bubbleId)

    if payload is None:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(payload, spent_time=timestamp() - t1)


@store.get("/x{ndcId}/s/store/recommend-items")
@store.get("/g/s/store/recommend-items")
@validauth_required
async def recommend_items(request: Request, ndcId: int = 0):
    t1 = timestamp()
    group_id = request.query_params.get("sectionGroupId", "avatar-frame")
    object_id = request.query_params.get("objectId")
    size = int(request.query_params.get("size", 25))

    async with await StoreService.create(_uid(request), ndcId) as svc:
        items = await svc.recommend_items(group_id, object_id, size)
        storeSection = StoreItemType.SECTION_META.get("group_id", {}).get("objectType")

    return Base.Answer(
        build_store_items_response(items, storeSection), spent_time=timestamp() - t1
    )


@store.get("/x{ndcId}/s/avatar-frame")
@store.get("/g/s/avatar-frame")
@validauth_required
async def list_my_avatar_frames(request: Request, ndcId: int = 0):
    t1 = timestamp()
    start, size = _paging(request, default_size=20)

    async with await StoreService.create(_uid(request), ndcId) as svc:
        result = await svc.list_my_avatar_frames(start, size)

    return Base.Answer({"avatarFrameList": result}, spent_time=timestamp() - t1)


@store.get("/x{ndcId}/s/chat/chat-bubble")
@store.get("/g/s/chat/chat-bubble")
@validauth_required
async def list_my_bubbles(request: Request, ndcId: int = 0):
    t1 = timestamp()
    start, size = _paging(request, default_size=20)
    chat_id = request.query_params.get("threadId")

    async with await StoreService.create(_uid(request), ndcId) as svc:
        payload = await svc.list_my_bubbles(chat_id, start, size)

    return Base.Answer(payload, spent_time=timestamp() - t1)


@store.get("/g/s/store/subscription")
@validauth_required
async def get_store_subscription(request: Request):
    t1 = timestamp()
    return Base.Answer({"storeSubscriptionItemList": []}, spent_time=timestamp() - t1)


@store.get("/x{ndcId}/s/store/recommend-store-by-product")
@store.get("/g/s/store/recommend-store-by-product")
@validauth_required
async def recommend_store_by_product(request: Request, ndcId: int = 0):
    t1 = timestamp()
    return Base.Answer(
        {"communityList": [], "storeItemCommunityCheckList": []},
        spent_time=timestamp() - t1,
    )


@store.get("/x{ndcId}/s/store/share-requests/pending-check")
@store.get("/g/s/store/share-requests/pending-check")
@validauth_required
async def recommend_store_by_product(request: Request, objectType: int, ndcId: int = 0):
    t1 = timestamp()
    return Base.Answer(
        spent_time=timestamp() - t1,
    )


@store.post("/x{ndcId}/s/store/share-requests")
@store.post("/g/s/store/share-requests")
@validauth_required
async def store_share_request(request: Request, ndcId: int = 0):
    t1 = timestamp()
    try:
        data = await request.json()
        object_id = data["objectId"]
        object_type = int(data["objectType"])
        _timestamp = int(data["timestamp"])
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    return Base.Answer(
        spent_time=timestamp() - t1
    )  # TODO: implement store share request
