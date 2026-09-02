from asyncio import to_thread as asyncio_thread
import aiohttp
from helpers.aquarium import Blake
from helpers.config import Config
from helpers.database.mongo import Database
from helpers.processors.email import EmailProcessor


from time import time as timestamp
import hashlib
import io
import json
import zipfile
from fastapi import APIRouter, Request

from helpers.routers.cachable import CachableRoute
from objects import Base, Errors
from objects.types import UserRole, UserStatus
from objects.types.store import StoreItemType

from string import ascii_letters, digits
import secrets


from helpers.database.models import Global, ModelFabric
from helpers.generator import Generator
from objects import Links

import uuid
from datetime import UTC, datetime
from objects.types.store import DiscountStatus, RestrictType


def _iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


altteam = APIRouter()
altteam.route_class = CachableRoute


@altteam.get("/g/s/altteam/version")
async def get_altteam_version(request: Request):
    t1 = timestamp()
    latest_version = "1.0.4"
    current_version = request.query_params.get("version")
    altTeamPage = "https://altamino.top/altapp"
    return Base.Answer(
        {
            "currentVersion": current_version,
            "latestVersion": latest_version,
            "downloadPage": altTeamPage,
        },
        spent_time=timestamp() - t1,
    )


@altteam.get("/g/s/altteam")
async def get_altamino_team(request: Request):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")
        local_table = db.get(database="x0", table="Users")

        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        global_cursor = sensitive_table.find(
            {"role": {"$in": UserRole.GODS}},
            {
                "_id": 0,
                "id": 1,
                "role": 1,
                "tagList": 1,
                "aminoId": 1,
                "telegramId": 1,
                "isTeamMember": 1,
                "isVerified": 1,
            },
        )
        global_members = await global_cursor.to_list(length=None)
        if not global_members:
            return Base.Answer(spent_time=timestamp() - t1, userProfileList=[])

        global_ids = [m["id"] for m in global_members]

        local_cursor = local_table.find(
            {"id": {"$in": global_ids}},
            {
                "_id": 0,
                "id": 1,
                "nickname": 1,
                "icon": 1,
                "reputation": 1,
                "createdTime": 1,
                "modifiedTime": 1,
                "extensions": 1,
            },
        )
        local_profiles = await local_cursor.to_list(length=None)
        local_by_uid = {p["id"]: p for p in local_profiles}
        team_list = []
        for g in global_members:
            profile = local_by_uid.get(g["id"])
            if not profile:
                continue

            merged = dict(profile)
            merged["uid"] = g["id"]
            merged["role"] = g.get("role", 0)
            merged["extensions"]["tagList"] = g.get("tagList", [])
            merged["aminoId"] = g.get("aminoId")
            merged["telegramId"] = g.get("telegramId")
            merged["extensions"]["isMemberOfTeamAmino"] = g.get("isTeamMember", False)
            merged["isNicknameVerified"] = bool(g.get("isVerified", False))
            team_list.append(merged)
        return Base.Answer({"userProfileList": team_list}, spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.get("/g/s/altteam/{userId}")
async def get_altamino_team_member(request: Request, userId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")
        local_table = db.get(database="x0", table="Users")

        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        global_member = await sensitive_table.find_one(
            {"id": userId, "role": {"$in": UserRole.GODS}},
            {
                "_id": 0,
                "id": 1,
                "role": 1,
                "tagList": 1,
                "aminoId": 1,
                "telegramId": 1,
                "isTeamMember": 1,
                "isVerified": 1,
            },
        )
        if not global_member:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        local_profile = await local_table.find_one(
            {"id": userId},
            {
                "_id": 0,
                "id": 1,
                "nickname": 1,
                "icon": 1,
                "reputation": 1,
                "createdTime": 1,
                "modifiedTime": 1,
                "extensions": 1,
            },
        )
        if not local_profile:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        merged = dict(local_profile)
        merged["uid"] = global_member["id"]
        merged["role"] = global_member.get("role", 0)
        merged["extensions"]["tagList"] = global_member.get("tagList", [])
        merged["aminoId"] = global_member.get("aminoId")
        merged["telegramId"] = global_member.get("telegramId")
        merged["extensions"]["isMemberOfTeamAmino"] = global_member.get(
            "isTeamMember", False
        )
        merged["isNicknameVerified"] = bool(global_member.get("isVerified", False))

        return Base.Answer({"userProfile": merged}, spent_time=timestamp() - t1)
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    finally:
        db.close()


@altteam.post("/g/s/altteam/telegram/link")
async def link_telegram(request: Request, body: dict):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    telegram_id = body.get("telegramId")
    amino_id = body.get("aminoId")

    if not trigger_uid or telegram_id is None:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if not isinstance(telegram_id, int):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")

        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or user.get("role", 0) != UserRole.System:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        target_query = {"aminoId": amino_id} if amino_id else {"id": trigger_uid}

        await sensitive_table.update_one(
            target_query, {"$set": {"telegramId": telegram_id}}
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/telegram/unlink")
async def unlink_telegram(request: Request, body: dict = None):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")

    body = body or {}
    amino_id = body.get("aminoId")

    if not trigger_uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")

        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or user.get("role", 0) != UserRole.System:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        target_query = {"aminoId": amino_id} if amino_id else {"id": trigger_uid}

        await sensitive_table.update_one(target_query, {"$unset": {"telegramId": ""}})
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/{userId}/edit")
async def edit_altteam_member(request: Request, userId: str, body: dict):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")

    if not trigger_uid:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")

        trigger_user = await sensitive_table.find_one({"id": trigger_uid})
        if not trigger_user or trigger_user.get("role", 0) != UserRole.AltAminoStaff:
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        target_user = await sensitive_table.find_one({"id": userId})
        if not target_user:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        update_fields = {}

        new_role = body.get("role")
        is_verified = body.get("isVerified")
        new_tags = body.get("tagList")
        altteam_status = body.get("isMemberOfTeamAmino")

        if new_role is not None:
            if (
                target_user.get("role", 0) == UserRole.AltAminoStaff
                or userId == trigger_uid
            ):
                return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
            if not UserRole.is_valid_role(new_role):
                return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

            update_fields["role"] = new_role

        if new_tags is not None:
            if isinstance(new_tags, list):
                update_fields["tagList"] = new_tags

        if altteam_status is not None:
            update_fields["isTeamMember"] = altteam_status

        if is_verified is not None:
            update_fields["isVerified"] = is_verified

        if update_fields:
            await sensitive_table.update_one({"id": userId}, {"$set": update_fields})

        return Base.Answer(spent_time=timestamp() - t1)
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    finally:
        db.close()


@altteam.post("/g/s/altteam/reset-password")
async def support_reset_password(request: Request, ndcId: int = 0):
    t1 = timestamp()
    if not Config.ENABLE_EMAIL:
        return Errors.PathUnderMaintenance(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    sensitive_table = db.get(table="Users")
    user = await sensitive_table.find_one({"id": trigger_uid})
    if not user or not UserRole.is_global_staff(user.get("role", 0)):
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    try:
        secret = "".join(secrets.choice(ascii_letters + digits) for _ in range(12))
        data = await request.json()
        updateSecret = Blake(
            data=f"0 {secret}",
            key=Config.PASSWORD_SALT,
            digest_size=64,
        ).hash
        email = data["email"]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if not await EmailProcessor.Validate(email):
        return Errors.InvalidEmail(timestamp() - t1, lang=request.state.lang)
    table = db.get(table="Users")
    await table.update_one({"email": email}, {"$set": {"passwordHash": updateSecret}})
    db.close()

    html = """<h3>Your AltAmino password has been reset by support.</h3><p>Your new password is:</p><h2>{{ PASSWORD }}</h2><p>Please log in using this password and change it as soon as possible in your account settings.</p><p>If you did not request this, please contact us immediately.</p><br><p>Thanks,<br>Team AltAmino</p>"""
    text = "Your AltAmino password has been reset by support. Your new temporary password is: {{ PASSWORD }}. Please log in and change it as soon as possible in your account settings. If you did not request this, please contact us immediately."

    html = html.replace("{{ PASSWORD }}", secret)
    text = text.replace("{{ PASSWORD }}", secret)
    subject = "Your AltAmino password has been reset"

    try:
        await asyncio_thread(
            EmailProcessor.SendEmail,
            receiver=email,
            subject=subject,
            html=html,
            text=text,
        )
    except Exception as e:
        print(e)
        return Errors.MailError(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )


@altteam.post("/g/s/altteam/user-profile/{userId}/status")
async def set_user_status(request: Request, userId: str):
    t1 = timestamp()
    if not Config.ENABLE_EMAIL:
        return Errors.PathUnderMaintenance(timestamp() - t1, lang=request.state.lang)
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    sensitive_table = db.get(table="Users")
    user = await sensitive_table.find_one({"id": trigger_uid})
    if not user or not UserRole.is_global_staff(user.get("role", 0)):
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    try:
        data = await request.json()
        status = data.get("status", 0)
        if not UserStatus.is_valid_status(status):
            raise Exception
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    table = db.get(table="Users")
    await table.update_one({"id": userId}, {"$set": {"status": status}})
    db.close()

    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )


@altteam.get("/g/s/altteam/user-profile/{userId}/communities")
async def get_user_communities(request: Request, userId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        sensitive_table = db.get(table="Users")
        user = await sensitive_table.find_one({"id": trigger_uid})
        if not user or not UserRole.is_global_staff(user.get("role", 0)):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        target = await sensitive_table.find_one(
            {"id": userId}, {"communityList": 1, "nickname": 1, "icon": 1}
        )
        if not target:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)

        community_ids = target.get("communityList", [])

        communities_table = db.get(table="Communities")
        links_table = db.get(table="Links")
        result = []

        async for item in communities_table.find({"id": {"$in": community_ids}}):
            ndc_id = item["id"]
            ndc_users_table = db.get(f"x{ndc_id}", "Users")
            ndc_profile = await ndc_users_table.find_one({"id": userId})

            link = await links_table.find_one(
                {"objectId": userId, "objectType": 0, "ndcId": int(ndc_id)}
            )

            if link is None and ndc_profile:
                link = ModelFabric.Construct(
                    Global.Links,
                    code=Generator.RealString(8),
                    targetCode=1,
                    objectId=userId,
                    objectType=0,
                    ndcId=int(ndc_id),
                )
                await links_table.insert_one(link)

            if link:
                link_data = Links.User(link)
            else:
                link_data = None

            result.append(
                {
                    "ndcId": item.get("id"),
                    "endpoint": item.get("aminoId"),
                    "name": item.get("name"),
                    "icon": item.get("icon"),
                    "userProfile": {
                        "nickname": ndc_profile.get("nickname")
                        if ndc_profile
                        else target.get("nickname"),
                        "icon": ndc_profile.get("icon")
                        if ndc_profile
                        else target.get("icon"),
                        "role": ndc_profile.get("role", 0) if ndc_profile else 0,
                        "linkData": link_data,
                    },
                }
            )

        return Base.Answer(
            {
                "communityList": result,
                "communityCount": len(result),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


async def _fetch_resource_config(resource_url: str) -> tuple[str, dict] | None:
    """
    Скачивает zip по resourceUrl, считает md5 всего архива и читает config.json из корня.
    Возвращает (md5_hex, config_dict) либо None, если скачать/распарсить не удалось.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(resource_url) as resp:
                if resp.status != 200:
                    return None
                raw = await resp.read()
    except Exception as e:
        print(e)
        return None

    md5_hex = hashlib.md5(raw).hexdigest()

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with zf.open("config.json") as f:
                config = json.loads(f.read().decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        print("zip/json error")
        return None

    if not isinstance(config, dict):
        return None
    return md5_hex, config


async def _require_global_staff(db, trigger_uid: str) -> bool:
    user = await db.get(table="Users").find_one({"id": trigger_uid})
    return bool(user and UserRole.is_global_staff(user.get("role", 0)))


async def _purge_ownership(db, object_type: int, object_id: str, worn_field: str):
    await db.get(table="UserStoreItems").delete_many(
        {"objectType": object_type, "objectId": object_id}
    )
    await db.get(table="Users").update_many(
        {worn_field: object_id}, {"$set": {worn_field: None}}
    )


#  Avatar Frames


@altteam.post("/g/s/altteam/altstore/avatar-frame")
async def create_frame(request: Request):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        try:
            data = await request.json()
            resource_url = data["resourceUrl"]
        except Exception:
            print("data error")
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        fetched = await _fetch_resource_config(resource_url)
        if fetched is None:
            print("fetched none")
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        md5_hex, config = fetched

        frame_id = str(uuid.uuid4())
        doc = {
            "frameId": frame_id,
            "name": config.get("name"),
            "version": config.get("version"),
            "resourceUrl": resource_url,
            "md5": md5_hex,
            "icon": data.get("icon"),
            "frameType": data.get("frameType", 1),
            "description": data.get("description", ""),
            "price": data.get("price", 0),
            "restrictType": data.get("restrictType")
            or (RestrictType.COIN if data.get("price", 0) else RestrictType.FREE),
            "discountStatus": data.get("discountStatus", DiscountStatus.OFF),
            "discountValue": data.get("discountValue", 0),
            "availableDuration": data.get("availableDuration", 0),
            "status": 0,
            "uid": trigger_uid,
            "createdTime": _iso(),
            "modifiedTime": _iso(),
            "extensions": {},
            "availableNdcIds": data.get("availableNdcIds", []),
        }

        if not doc["name"]:
            print("no name")
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        frames = db.get(table="AvatarFrames")
        await frames.insert_one(doc)
        doc.pop("_id", None)

        return Base.Answer(
            {"frameId": frame_id, "avatarFrame": doc}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@altteam.post("/g/s/altteam/altstore/avatar-frame/{frameId}/edit")
async def edit_frame(request: Request, frameId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        try:
            data = await request.json()
        except Exception:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        allowed = {
            "resourceUrl",
            "icon",
            "frameType",
            "description",
            "price",
            "restrictType",
            "discountStatus",
            "discountValue",
            "availableDuration",
            "md5",
            "status",
        }
        changes = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not changes:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        changes["modifiedTime"] = _iso()

        frames = db.get(table="AvatarFrames")
        result = await frames.update_one({"frameId": frameId}, {"$set": changes})
        if result.matched_count == 0:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/altstore/avatar-frame/{frameId}/delete")
async def delete_frame(request: Request, frameId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        frames = db.get(table="AvatarFrames")
        result = await frames.delete_one({"frameId": frameId})
        if result.deleted_count == 0:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        # снести владение и снять у всех, кто носит
        await _purge_ownership(db, StoreItemType.AvatarFrame, frameId, "frameId")

        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.get("/g/s/altteam/altstore/avatar-frame")
async def list_frames(request: Request):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        frames = db.get(table="AvatarFrames")
        docs = await frames.find({}, {"_id": 0}).to_list(length=None)

        return Base.Answer({"avatarFrameList": docs}, spent_time=timestamp() - t1)
    finally:
        db.close()


#  Chat Bubbles


@altteam.post("/g/s/altteam/altstore/chat-bubble")
async def create_bubble(request: Request):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        try:
            data = await request.json()
            resource_url = data["resourceUrl"]
        except Exception:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        fetched = await _fetch_resource_config(resource_url)
        if fetched is None:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        md5_hex, config = fetched

        bubble_id = str(uuid.uuid4())
        doc = {
            "bubbleId": bubble_id,
            "name": config.get("name"),
            "version": config.get("version"),
            "bubbleType": config.get("bubbleType"),
            "templateId": config.get("templateId"),
            "coverImage": config.get("coverImage"),
            "config": config,
            "resourceUrl": resource_url,
            "md5": md5_hex,
            "backgroundImage": data.get("backgroundImage"),
            "bannerImage": data.get("bannerImage"),
            "price": data.get("price", 0),
            "restrictType": data.get("restrictType")
            or (RestrictType.COIN if data.get("price", 0) else RestrictType.FREE),
            "discountStatus": data.get("discountStatus", DiscountStatus.OFF),
            "discountValue": data.get("discountValue", 0),
            "availableDuration": data.get("availableDuration", 0),
            "status": 0,
            "deletable": True,
            "uid": trigger_uid,
            "createdTime": _iso(),
            "modifiedTime": _iso(),
            "extensions": {},
            "availableNdcIds": data.get("availableNdcIds", []),
        }

        if not doc["name"]:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        bubbles = db.get(table="ChatBubbles")
        await bubbles.insert_one(doc)
        doc.pop("_id", None)

        return Base.Answer(
            {"bubbleId": bubble_id, "chatBubble": doc}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@altteam.post("/g/s/altteam/altstore/chat-bubble/{bubbleId}/edit")
async def edit_bubble(request: Request, bubbleId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        try:
            data = await request.json()
        except Exception:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        allowed = {
            "name",
            "resourceUrl",
            "coverImage",
            "backgroundImage",
            "bannerImage",
            "bubbleType",
            "config",
            "templateId",
            "price",
            "restrictType",
            "discountStatus",
            "discountValue",
            "availableDuration",
            "md5",
            "version",
            "status",
            "deletable",
        }
        changes = {k: v for k, v in data.items() if k in allowed and v is not None}
        if not changes:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
        changes["modifiedTime"] = _iso()

        bubbles = db.get(table="ChatBubbles")
        result = await bubbles.update_one({"bubbleId": bubbleId}, {"$set": changes})
        if result.matched_count == 0:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/altstore/chat-bubble/{bubbleId}/delete")
async def delete_bubble(request: Request, bubbleId: str):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        bubbles = db.get(table="ChatBubbles")
        result = await bubbles.delete_one({"bubbleId": bubbleId})
        if result.deleted_count == 0:
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

        # снести владение и снять у всех, кто носит
        await _purge_ownership(db, StoreItemType.ChatBubble, bubbleId, "bubbleId")

        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.get("/g/s/altteam/altstore/chat-bubble")
async def list_bubbles(request: Request):
    t1 = timestamp()
    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    try:
        if not await _require_global_staff(db, trigger_uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

        bubbles = db.get(table="ChatBubbles")
        docs = await bubbles.find({}, {"_id": 0}).to_list(length=None)

        return Base.Answer({"chatBubbleList": docs}, spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/mod/{t}/{action}/{objId}")
async def disable_toggle(request: Request, t: str, action: str, objId: str):
    t1 = timestamp()

    _t = {"user": "Users", "community": "Communities"}
    print(f"t: {t}, action: {action}, objId: {objId}")

    if t not in _t or action not in ("disable", "enable"):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    trigger_uid = request.state.session.get("uid")
    db = await Database().init()
    sensitive_table = db.get(table="Users")
    user = await sensitive_table.find_one({"id": trigger_uid})
    if not user or not UserRole.is_global_staff(user.get("role", 0)):
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)

    table = db.get(table=_t[t])
    result = await table.update_one(
        {"id": objId},
        {"$set": {"status": 9 if action == "disable" else 0}},
    )
    if result.matched_count == 0:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
    db.close()
    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )
