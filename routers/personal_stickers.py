"""Amino+ personal stickers (the star tab of StickerPickerTabFragment; port of Kioraa sticker-state).

Every Amino+ member gets one personal collection (collectionType 2, id "personal-{uid}") in
StickerCollections, owned and activated through UserStoreItems like any other pack. The picker
draws a tab with the collection's smallIcon, so the star is served here as an image. Stickers
are added with POST /sticker/save-as (a sticker seen in chat or an image uploaded to the
AltAmino media host) and removed with .../stickers/batch-delete. Leaving Amino+ hides the tab
(deactivated); nothing is deleted.
"""

import base64
from datetime import UTC, datetime
from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request, Response

from helpers.config import Config
from helpers.database.mongo import Database
from helpers.decorators.validauth import validauth_required
from helpers.functions import is_app_link
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors
from objects.types.store import StoreItemType

personal_stickers = APIRouter()
personal_stickers.route_class = CachableRoute
sticker_assets = APIRouter()  # plain route: image loaders send no app headers

STAR_PATH = "/static/v1/sticker-star.png"
MAX_STICKERS = 100
NAMES = {"pt": "Minhas figurinhas", "es": "Mis stickers", "en": "My Stickers"}
_STAR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAJAAAACQCAYAAADnRuK4AAAGBUlEQVR4nO2d4ZWbOhCFKYEStoQtwSVsCS5hS3AH24Fdgktw"
    "CS7BJVBC3nnnQEIcBBJIc+9I98f3M8mHuUEMM4juer12QuwFLiB8AxcQvoELCN/ABYRv4ALCN3AB4Ru4gPANXED4Bi4gfAMX"
    "EL6BCwjfwAXI+RxBe9ACFyDnNoL2oAUuQEx/vV5/jfQEPpTABYi5zAJ0IfChBC5AzGsWoBeBDyVwAVLOs/BMnAm86IALkPJY"
    "CNCDwIsOuAAhnwvhmVBJ/wZcgJDbSoBU0r8BFyDj/3J9WAnQoJL+b+ACZHyvhGfim8CTBrgAGa+IAKmknwEXIOIrIjwTXwS+"
    "FMAFiFgq3UOopB+BC5DwkRCeiQ8CbzhwARJ+dgToh8AbDlyAgK3SXSW9ArTKUt8rlub7Y3ABAmJKd5X0CtAipwPhmTgRHIcC"
    "BOKeIUB3guNQgADsKd1V0itAv9lTuqukV4B+s6d0Xyvp0cejABlypHRXSa8AXZ8FAvQkOC4FyIAcpXuI5kp6uACAtZHVozQ3"
    "8goXMCZn6R6iqZIeLmDMxSBATb3FChcw5kjfK5am+mNwAUNKlO4hminp4QKGpIysHqWZkVe4gBFrb5uWoom3WOECRpQs3UM0"
    "UdLDBQzoAeGZqH7kFS5ggEXpHqL6kh4uYIBF6R6i+pIeLlCYlLdNS1H1W6xwgYKcjEv3EI+am6xwgQQ+xxNxGnfIuIzcx5PE"
    "EJaUUD1G9+k4vmfH5+YRAPIf/5j9YOdAIHJODXplCATuPPv9YA3cnH9ZHwjEbfYDIG9oW+E1+71vgcBle7yw5w+dZ4IlJvuE"
    "Lc/Z+Uzu4e290ni63xBxPPZcmY5cvhDtAVGG3W2Xo2tgzJ6CgptDez7muJGynLMReTk8t5QjQN343EIltx+GXM+acgVoCpGq"
    "Mn6eOR9U5gxQN97FK0S8PHOPmOQO0BQiVWh83ErMJ5UI0ETO3S/EMYrtHlIyQJ0qNAqKviFSOkDdOA+jCs2ewWIWySJAncp8"
    "SHhMRkKsAtSpQjMje6XFEqBOjdji7GqIegrQhMr8/EDeQ0MFqFMjNiuwj+AhA9SNJaZurvczoDdyQAeoU4V2KDzw4Xt0eOYh"
    "UoUWT9aGaA0B6lTmJ4WH5p17uMACqtDC0O34ARcIoEbsv1B+TgEusIIasX+g3TIPLrDBqfEKbWB/rx4uEEGrZT5FmV5DgLoG"
    "KzSqSquGAE0hyvGFQXbuXsLjLUATNZf5dGV6jQGquTqjrbZqCpCuQETABXZQ8x5D7jblhAskYvG5JjSuPhcFF0iEYdfV0rja"
    "1RUukEgLPTLKnlctAWrhYaKrj/fCBRJBn1wr0L9zlQEq+bVlNqgbqF4DhPxoijVuPtICF0igpRcS3XzxEC6QAPqkWoP+vasK"
    "EOKTlWjoZ4E8BajFt1hhb5vWGKAW5oDeuRP87tUEqOYGaggXjVW4QAQtNFBD0DdW4QIR1DxAtgX9gBlcIIKaB8i2oB8wgwtE"
    "gGygvsD3X/SNVbjABj3w5F3Gf7+/Ytso1G9owAU2QAyQPQI3rx+gdgr1gBlcYAPL//mvyJP1ZbysUTdW4QIbWP2PvyQuFZbL"
    "GnVjFS6wgcXJOfKsxWpZQ58HlwEqOUCWe3PK0puF0g6YwQVWKLVE/BSqbPqCQ/+090FwgRVyN1AfRiMSnwWWNdrGKlxghVxL"
    "Amov5ZzL2kBwPlwFKNcAWanlKpacyxrlgBlcIMDRBqrVchVLjmWNsrEKFwiwt4EK3/p/gyPLGmVjFS4QYM+TXvRyFcveZY1y"
    "wAwusEDqABnNtv+J7Pm8A92AGVxggdgG6uBl8HyD74Rlja6xChdYIObyXuQb6ED6yPs+up074AILrF3Wn8yP9TNwijh+tCN9"
    "gGpermJZW9bQbn8BF3hjqYFa23IVS2hZo7oCwwXeuDS0XMXyvqxRNVbhAm88GlyuYpmWNaoBM7jAG662+QfQs3Xm4QLCN3AB"
    "4Ru4gPANXED4Bi4gfAMXEL6BCwjfwAWEb+ACwjdwAeEbuIDwDVxA+AYuIHwDFxC+gQsI38AFhG/gAsI3cAHhm/8AFWWuRZOT"
    "RRgAAAAASUVORK5CYII="
)


def star_url() -> str:
    return Config.API_BASE_URL.rstrip("/") + STAR_PATH


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@sticker_assets.get(STAR_PATH)
async def personal_star():
    return Response(
        _STAR_PNG,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


async def sync_personal(db, uid: str | None, lang: str = "en") -> None:
    """Amino+ members: personal collection exists and is active. Others: tab hidden."""
    if not uid:
        return
    user = await db.get(table="Users").find_one({"id": uid}, {"isPaidSubscriber": 1})
    owned = db.get(table="UserStoreItems")
    collection_id = f"personal-{uid}"
    if not (user or {}).get("isPaidSubscriber"):
        await owned.update_one(
            {"uid": uid, "objectId": collection_id}, {"$set": {"isActivated": False}}
        )
        return
    collections = db.get(table="StickerCollections")
    if not await collections.find_one({"collectionId": collection_id}, {"_id": 1}):
        language = (lang or "en")[:2]
        await collections.update_one(
            {"collectionId": collection_id},
            {
                "$setOnInsert": {
                    "collectionId": collection_id,
                    "ndcId": 0,
                    "creatorId": uid,
                    "name": NAMES.get(language, NAMES["en"]),
                    "description": "",
                    "collectionType": 2,
                    "icon": star_url(),
                    "smallIcon": star_url(),
                    "bannerUrl": None,
                    "stickersCount": 0,
                    "usedCount": 0,
                    "status": 0,
                    "isShared": False,
                    "availableNdcIds": [],
                    "extensions": {},
                    "discountStatus": 0,
                    "discountValue": 0,
                    "ownerType": 0,
                    "restrictType": 2,
                    "price": 0,
                    "restrictValue": None,
                    "availableDuration": 0,
                    "stickerList": [],
                    "createdTime": _now(),
                    "modifiedTime": _now(),
                }
            },
            upsert=True,
        )
    await owned.update_one(
        {
            "uid": uid,
            "objectType": StoreItemType.StickerCollection,
            "objectId": collection_id,
        },
        {
            "$set": {"isActivated": True},
            "$setOnInsert": {
                "ownershipInfo": {
                    "createdTime": _now(),
                    "expiredTime": None,
                    "isAutoRenew": False,
                    "ownershipStatus": 1,
                },
                "createdTime": _now(),
            },
        },
        upsert=True,
    )


@personal_stickers.post("/g/s/sticker/save-as")
@personal_stickers.post("/x{ndcId}/s/sticker/save-as")
@validauth_required
async def save_as(request: Request, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        icon = data["icon"]
        name = data.get("name") or "Sticker"
        if (
            not isinstance(icon, str)
            or len(icon) > 1000
            or not is_app_link(icon)
            or not isinstance(name, str)
        ):
            raise ValueError("icon")
        name = name.strip()[:80] or "Sticker"
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        user = await db.get(table="Users").find_one(
            {"id": uid}, {"isPaidSubscriber": 1}
        )
        if not (user or {}).get("isPaidSubscriber"):
            return Errors.NotEnoughRights(
                timestamp() - t1, lang=request.state.lang
            )  # Amino+ only
        await sync_personal(db, uid, request.state.lang)
        collection_id = f"personal-{uid}"
        sticker = {
            "stickerId": str(uuid4()),
            "stickerCollectionId": collection_id,
            "name": name,
            "icon": icon,
            "iconV2": icon,
            "smallIcon": icon,
            "smallIconV2": icon,
            "mediumIcon": icon,
            "mediumIconV2": icon,
            "usedCount": 0,
            "status": 0,
            "extensions": {},
            "createdTime": _now(),
        }
        added = await db.get(table="StickerCollections").update_one(
            {
                "collectionId": collection_id,
                f"stickerList.{MAX_STICKERS - 1}": {"$exists": False},
            },
            {
                "$push": {"stickerList": sticker},
                "$inc": {"stickersCount": 1},
                "$set": {"modifiedTime": _now()},
            },
        )
        if not added.modified_count:
            return Errors.InvalidRequest(
                timestamp() - t1, lang=request.state.lang
            )  # pack is full
        return Base.Answer(
            {"sticker": sticker, "isNewSticker": True}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@personal_stickers.post("/g/s/sticker-collection/{collectionId}/stickers")
@personal_stickers.post("/x{ndcId}/s/sticker-collection/{collectionId}/stickers")
@validauth_required
async def add_sticker(request: Request, collectionId: str, ndcId: int = 0):
    """StickerHelper.createSticker: an uploaded image added to one of the reader's own packs."""
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        icon = data["icon"]
        name = data.get("name") or "Sticker"
        if (
            not isinstance(icon, str)
            or len(icon) > 1000
            or not is_app_link(icon)
            or not isinstance(name, str)
        ):
            raise ValueError("icon")
        name = name.strip()[:80] or "Sticker"
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if collectionId == f"personal-{uid}":
            user = await db.get(table="Users").find_one(
                {"id": uid}, {"isPaidSubscriber": 1}
            )
            if not (user or {}).get("isPaidSubscriber"):
                return Errors.NotEnoughRights(
                    timestamp() - t1, lang=request.state.lang
                )  # Amino+ only
            await sync_personal(db, uid, request.state.lang)
        table = db.get(table="StickerCollections")
        collection = await table.find_one(
            {"collectionId": collectionId, "status": 0}, {"creatorId": 1}
        )
        if not collection:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if collection.get("creatorId") != uid:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        sticker = {
            "stickerId": str(uuid4()),
            "stickerCollectionId": collectionId,
            "name": name,
            "icon": icon,
            "iconV2": icon,
            "smallIcon": icon,
            "smallIconV2": icon,
            "mediumIcon": icon,
            "mediumIconV2": icon,
            "usedCount": 0,
            "status": 0,
            "extensions": {},
            "createdTime": _now(),
        }
        added = await table.update_one(
            {
                "collectionId": collectionId,
                f"stickerList.{MAX_STICKERS - 1}": {"$exists": False},
            },
            {
                "$push": {"stickerList": sticker},
                "$inc": {"stickersCount": 1},
                "$set": {"modifiedTime": _now()},
            },
        )
        if not added.modified_count:
            return Errors.InvalidRequest(
                timestamp() - t1, lang=request.state.lang
            )  # pack is full
        return Base.Answer(
            {"sticker": sticker, "isNewSticker": True}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@personal_stickers.post("/g/s/sticker-collection/{collectionId}/stickers/batch-delete")
@personal_stickers.post(
    "/x{ndcId}/s/sticker-collection/{collectionId}/stickers/batch-delete"
)
@validauth_required
async def delete_stickers(request: Request, collectionId: str, ndcId: int = 0):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = (await request.json())["stickerIdList"]
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > MAX_STICKERS
            or not all(isinstance(i, str) for i in ids)
        ):
            raise ValueError("stickerIdList")
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        table = db.get(table="StickerCollections")
        collection = await table.find_one({"collectionId": collectionId, "status": 0})
        if not collection:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if collection.get("creatorId") != uid:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        remaining = [
            s
            for s in collection.get("stickerList") or []
            if s.get("stickerId") not in ids
        ]
        update = {
            "stickerList": remaining,
            "stickersCount": len(remaining),
            "modifiedTime": _now(),
        }
        if collection.get("collectionType") != 2 and remaining:
            update.update(
                {"icon": remaining[0]["icon"], "smallIcon": remaining[0]["icon"]}
            )
        await table.update_one({"collectionId": collectionId}, {"$set": update})
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


async def resolve_chat_sticker(
    db, ndcId: int, uid: str, sticker_id: str
) -> dict | None:
    """A custom sticker the sender may use: own pack, an owned pack, or this community's shared pack."""
    collection = await db.get(table="StickerCollections").find_one(
        {"stickerList.stickerId": sticker_id, "status": 0}
    )
    if not collection:
        return None
    sticker = next(
        (
            s
            for s in collection.get("stickerList") or []
            if s.get("stickerId") == sticker_id and s.get("status", 0) == 0
        ),
        None,
    )
    if not sticker:
        return None
    allowed = collection.get("creatorId") == uid or (
        collection.get("isShared") and collection.get("ndcId") == ndcId
    )
    if not allowed:
        allowed = (
            await db.get(table="UserStoreItems").find_one(
                {
                    "uid": uid,
                    "objectType": StoreItemType.StickerCollection,
                    "objectId": collection["collectionId"],
                },
                {"_id": 1},
            )
            is not None
        )
    if not allowed:
        return None
    if collection.get("collectionType") == 2:
        owner = await db.get(table="Users").find_one(
            {"id": uid}, {"isPaidSubscriber": 1}
        )
        if not (owner or {}).get("isPaidSubscriber"):
            return None  # personal stickers are an Amino+ perk
    snapshot = {k: v for k, v in sticker.items() if k != "_id"}
    snapshot["stickerCollectionSummary"] = {
        "collectionId": collection["collectionId"],
        "collectionType": collection.get("collectionType"),
        "name": collection.get("name"),
        "uid": collection.get("creatorId"),
        "icon": collection.get("icon"),
        "smallIcon": collection.get("smallIcon"),
        "status": 0,
    }
    return snapshot
