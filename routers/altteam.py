from asyncio import to_thread as asyncio_thread
import aiohttp
from helpers.aquarium import Blake
from helpers.config import Config
from helpers.database.mongo import Database
from helpers.processors.email import EmailProcessor


from time import time as timestamp
import hashlib
import io
import re
import json
import zipfile
from fastapi import APIRouter, Request
from helpers.config import Config
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors
from objects.types import UserRole, UserStatus
from objects.types.store import StoreItemType

from string import ascii_letters, digits
import secrets

from helpers.database.redis import get as get_redis
from helpers.database.models import Global, ModelFabric
from helpers.generator import Generator
from objects import Links

import uuid
from datetime import UTC, datetime
from objects.types.store import DiscountStatus, RestrictType
from helpers.processors.session import SessionProcessor


def _iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


altteam = APIRouter()
altteam.route_class = CachableRoute


@altteam.get("/g/s/altteam/version")
async def get_altteam_version(request: Request):
    t1 = timestamp()
    latest_version = "1.2.0"
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


async def _connected_uids() -> list[str]:
    r = get_redis()
    now = timestamp()
    await r.zremrangebyscore("ws:connected", "-inf", now)
    members = await r.zrangebyscore("ws:connected", now, "+inf")
    uids = set()
    for m in members:
        if isinstance(m, bytes):
            m = m.decode()
        uids.add(m.rpartition(":")[0])
    return sorted(uids)


@altteam.get("/g/s/altteam/online")
async def admin_online_users(request: Request, start: int = 0, size: int = 25):
    t1 = timestamp()
    uids = await _connected_uids()
    total = len(uids)
    page = uids[start : start + size]
    trigger_uid = request.state.session.get("uid")

    db = await Database().init()
    sensitive_table = db.get(table="Users")
    user = await sensitive_table.find_one({"id": trigger_uid})
    if not user or not UserRole.is_global_staff(user.get("role", 0)):
        db.close()
        return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
    try:
        g_table = db.get(table="Users")
        profile_table = db.get("x0", "Users")

        global_rows = {r["id"]: r async for r in g_table.find({"id": {"$in": page}})}
        profile_rows = {
            r["id"]: r async for r in profile_table.find({"id": {"$in": page}})
        }
    finally:
        db.close()

    users = []
    for uid in page:
        g = global_rows.get(uid, {})
        p = profile_rows.get(uid, {})
        users.append(
            {
                "uid": uid,
                "nickname": p.get("nickname") or g.get("nickname"),
                "icon": p.get("icon") or g.get("icon"),
                "aminoId": g.get("aminoId") or p.get("aminoId"),
                "role": g.get("role", 0),
                "status": g.get("status", 0),
            }
        )

    return Base.Answer(
        {"usersCount": total, "userList": users}, spent_time=timestamp() - t1
    )


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
            ndcId = item["id"]
            ndc_users_table = db.get(f"x{ndcId}", "Users")
            ndc_profile = await ndc_users_table.find_one({"id": userId})

            link = await links_table.find_one(
                {"objectId": userId, "objectType": 0, "ndcId": int(ndcId)}
            )

            if link is None and ndc_profile:
                link = ModelFabric.Construct(
                    Global.Links,
                    code=Generator.RealString(8),
                    targetCode=1,
                    objectId=userId,
                    objectType=0,
                    ndcId=int(ndcId),
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
    try:
        objId = int(objId)
    except ValueError:
        pass
    result = await table.update_one(
        {"id": objId},
        {"$set": {"status": 9 if action == "disable" else 0}},
    )
    if result.matched_count == 0:
        db.close()
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
    if t == "user" and action == "disable":
        await SessionProcessor.EndAllByUser(objId)
    db.close()
    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )


# discover (TODO)

DISCOVER_BANNERS = "DiscoverBanners"


async def _is_staff(request: Request, db) -> bool:
    uid = request.state.session.get("uid")
    user = await db.get(table="Users").find_one({"id": uid})
    return bool(user and UserRole.is_global_staff(user.get("role", 0)))


def _banner_out(b: dict) -> dict:
    return {
        "id": b["id"],
        "imageUrl": b.get("imageUrl", ""),
        "landingUrl": b.get("landingUrl", ""),
        "deepLink": b.get("deepLink", ""),
        "segment": b.get("segment", "all"),
        "enabled": b.get("enabled", True),
        "order": b.get("order", 0),
    }


def _community_out(c: dict) -> dict:
    return {
        "ndcId": c.get("id"),
        "name": c.get("name"),
        "aminoId": c.get("aminoId"),
        "icon": c.get("icon"),
        "isSelected": bool(c.get("isSelected", False)),
    }


@altteam.get("/g/s/altteam/discover/banners")
async def discover_banners_list(request: Request):
    t1 = timestamp()
    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table=DISCOVER_BANNERS)
        items = [b async for b in table.find({}).sort("order", 1)]
        return Base.Answer(
            {"bannerList": [_banner_out(b) for b in items]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/banners/create")
async def discover_banner_create(request: Request):
    t1 = timestamp()
    body = await request.json()
    image_url = str(body.get("imageUrl", "")).strip()
    landing_url = str(body.get("landingUrl", "")).strip()
    deep_link = str(body.get("deepLink", "")).strip()
    segment = str(body.get("segment", "all")).strip()
    segment = segment if segment in Config.LANG_SEGMENTS else "all"
    if not image_url.startswith("http"):
        return Errors.InvalidRequest()

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table=DISCOVER_BANNERS)
        last = await table.find_one({}, sort=[("order", -1)])
        doc = {
            "id": str(uuid.uuid4()),
            "imageUrl": image_url,
            "landingUrl": landing_url,
            "segment": segment,
            "deepLink": deep_link,
            "enabled": True,
            "order": (last.get("order", 0) + 1) if last else 0,
        }
        await table.insert_one(doc)
        return Base.Answer({"banner": _banner_out(doc)}, spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/banners/reorder")
async def discover_banners_reorder(request: Request):
    t1 = timestamp()
    body = await request.json()
    ids = body.get("ids")
    if not isinstance(ids, list):
        return Errors.InvalidRequest()

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table=DISCOVER_BANNERS)
        for i, banner_id in enumerate(ids):
            await table.update_one({"id": str(banner_id)}, {"$set": {"order": i}})
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/banners/{banner_id}/edit")
async def discover_banner_edit(request: Request, banner_id: str):
    t1 = timestamp()
    body = await request.json()
    updates = {}
    if "imageUrl" in body:
        url = str(body["imageUrl"]).strip()
        if not url.startswith("http"):
            return Errors.InvalidRequest()
        updates["imageUrl"] = url
    if "landingUrl" in body:
        updates["landingUrl"] = str(body["landingUrl"]).strip()
    if "enabled" in body:
        updates["enabled"] = bool(body["enabled"])
    if "deepLink" in body:
        updates["deepLink"] = str(body.get("deepLink", "")).strip()
    if "segment" in body:
        segment = str(body.get("segment", "all")).strip()
        updates["segment"] = segment if segment in Config.LANG_SEGMENTS else "all"
    if not updates:
        return Errors.InvalidRequest()

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table=DISCOVER_BANNERS)
        res = await table.update_one({"id": banner_id}, {"$set": updates})
        if res.matched_count == 0:
            return Errors.DataNotExist()
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/banners/{banner_id}/delete")
async def discover_banner_delete(request: Request, banner_id: str):
    t1 = timestamp()
    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        await db.get(table=DISCOVER_BANNERS).delete_one({"id": banner_id})
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.get("/g/s/altteam/discover/picks")
async def discover_picks(request: Request):
    t1 = timestamp()
    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        items = [c async for c in table.find({"isSelected": True})]
        return Base.Answer(
            {"communityList": [_community_out(c) for c in items]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@altteam.get("/g/s/altteam/discover/communities/search")
async def discover_communities_search(
    request: Request, query: str = "", start: int = 0, size: int = 20
):
    t1 = timestamp()
    query = query.strip()
    if not query:
        return Base.Answer({"communityList": []}, spent_time=timestamp() - t1)

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        flt = {
            "hidden": {"$ne": True},
            "name": {"$regex": re.escape(query), "$options": "i"},
        }
        items = [c async for c in table.find(flt).skip(start).limit(min(size, 50))]
        return Base.Answer(
            {"communityList": [_community_out(c) for c in items]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@altteam.get("/g/s/altteam/discover/picks")
async def discover_picks_list(request: Request):
    t1 = timestamp()
    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        items = [
            c
            async for c in table.find({"isSelected": True}).sort(
                [("pickOrder", 1), ("id", 1)]
            )
        ]
        return Base.Answer(
            {"communityList": [_community_out(c) for c in items]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@altteam.get("/g/s/altteam/discover/communities/search")
async def discover_communities_search(
    request: Request, query: str = "", start: int = 0, size: int = 20
):
    t1 = timestamp()
    q = query.strip()
    if not q:
        return Errors.InvalidRequest()
    size = max(1, min(size, 50))
    rx = {"$regex": re.escape(q), "$options": "i"}

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        flt = {"$or": [{"name": rx}, {"aminoId": rx}]}
        if q.isdigit():
            flt["$or"].append({"id": int(q)})
        items = [c async for c in table.find(flt).skip(start).limit(size)]
        return Base.Answer(
            {"communityList": [_community_out(c) for c in items]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/picks/reorder")
async def discover_picks_reorder(request: Request):
    t1 = timestamp()
    body = await request.json()
    picks = body.get("picks")
    if not isinstance(picks, list):
        return Errors.InvalidRequest()
    try:
        ids = [int(x) for x in picks]
    except (TypeError, ValueError):
        return Errors.InvalidRequest()

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        for i, ndc_id in enumerate(ids):
            await table.update_one(
                {"id": ndc_id, "isSelected": True}, {"$set": {"pickOrder": i}}
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@altteam.post("/g/s/altteam/discover/picks/{ndc_id}/set")
async def discover_pick_set(request: Request, ndc_id: int):
    t1 = timestamp()
    body = await request.json()
    selected = bool(body.get("selected", True))

    db = await Database().init()
    try:
        if not await _is_staff(request, db):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(table="Communities")
        if not await table.find_one({"id": ndc_id}):
            return Errors.DataNotExist()

        if selected:
            last = await table.find_one(
                {"isSelected": True, "pickOrder": {"$exists": True}},
                sort=[("pickOrder", -1)],
            )
            order = (last.get("pickOrder", 0) + 1) if last else 0
            await table.update_one(
                {"id": ndc_id}, {"$set": {"isSelected": True, "pickOrder": order}}
            )
        else:
            await table.update_one(
                {"id": ndc_id},
                {"$set": {"isSelected": False}, "$unset": {"pickOrder": ""}},
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()
