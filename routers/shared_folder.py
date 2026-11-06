"""Shared folder: photos, albums, likes and comments (com.narvii.sharedfolder, APK 3.4).

x{ndc}/SharedFiles, SharedFolders, SharedFileComments. Media must be app-hosted
(MediaList.Item rejects external links). Upload/album rights follow the community's
sharedFolder module (enabled flag; privilege 3 = staff only, otherwise members).
"""

from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request
from pymongo import ASCENDING, DESCENDING

from helpers.routers.cachable import CachableRoute
from helpers.community_access import (
    is_member,
    module_config,
    now_iso,
    page,
    paging,
    profile,
    staff_level,
)
from helpers.database.mongo import Database
from helpers.decorators.turtlelimit import TurtleTime, turtlelimiter
from helpers.decorators.validauth import validauth_required
from objects import Base, Errors, MediaList

shared_folder = APIRouter()
shared_folder.route_class = CachableRoute
LIKE = 4


def _file_json(row: dict, author, viewer) -> dict:
    votes = row.get("votes") or []
    return {
        "fileId": row["fileId"],
        "title": row.get("title", ""),
        "fileType": 0,
        "media": row.get("media"),
        "extensions": row.get("extensions") or {},
        "author": author,
        "commentsCount": row.get("commentsCount", 0),
        "votesCount": len(votes),
        "votedValue": LIKE if viewer and viewer in votes else 0,
        "createdTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime") or row.get("createdTime"),
        "status": row.get("status", 0),
    }


async def _files_json(db, ndcId, rows, viewer):
    return [
        _file_json(r, await profile(db, ndcId, r.get("authorId"), viewer), viewer)
        for r in rows
    ]


async def _folder_json(db, ndcId, row: dict, viewer) -> dict:
    ids = row.get("fileIds") or []
    covers = [
        f["media"]
        async for f in db.get(f"x{ndcId}", "SharedFiles").find(
            {"fileId": {"$in": ids[:4]}, "status": 0}, {"media": 1}
        )
    ]
    live = (
        await db.get(f"x{ndcId}", "SharedFiles").count_documents(
            {"fileId": {"$in": ids}, "status": 0}
        )
        if ids
        else 0
    )
    return {
        "folderId": row["folderId"],
        "title": row.get("title", ""),
        "description": row.get("description", ""),
        "folderType": row.get("folderType", 1),
        "author": await profile(db, ndcId, row.get("authorId"), viewer),
        "filesCount": live,
        "votesCount": 0,
        "coverMediaList": covers,
        "createdTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime") or row.get("createdTime"),
        "status": row.get("status", 0),
    }


async def _may(db, ndcId: int, uid: str, action: str) -> bool:
    """action: uploadPrivilege | albumManagePrivilege."""
    if not await is_member(db, ndcId, uid):
        return False
    if await staff_level(db, ndcId, uid):
        return True
    community = await db.get(table="Communities").find_one(
        {"id": ndcId}, {"configuration": 1}
    )
    conf = module_config(community, "sharedFolder")
    if conf.get("enabled") is False:
        return False
    rule = conf.get(action, 2)
    rule_type = rule.get("type", 1) if isinstance(rule, dict) else rule
    return rule_type != 3


async def _owner_or_staff(db, ndcId, uid, author_uid) -> bool:
    return uid == author_uid or bool(await staff_level(db, ndcId, uid))


@shared_folder.get("/x{ndcId}/s/shared-folder/stats")
async def stats(request: Request, ndcId: int):
    t1 = timestamp()
    db = await Database().init()
    try:
        files = await db.get(f"x{ndcId}", "SharedFiles").count_documents({"status": 0})
        folders = await db.get(f"x{ndcId}", "SharedFolders").count_documents(
            {"status": 0}
        )
        return Base.Answer(
            {
                "stats": {
                    "filesCount": files,
                    "foldersCount": folders,
                    "fileCount": files,
                    "folderCount": folders,
                }
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/files")
async def list_files(
    request: Request,
    ndcId: int,
    type: str = "latest",
    uid: str | None = None,
    q: str | None = None,
    refId: str | None = None,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    query: dict = {"status": 0}
    db = await Database().init()
    try:
        if type == "disabled":
            if not await staff_level(db, ndcId, viewer):
                return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
            query["status"] = 9
        elif type == "my-uploads":
            if not viewer:
                return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)
            query["authorId"] = viewer
        elif type == "reference" and refId:
            query["referObjectId"] = refId
        elif uid or q:
            query["authorId"] = uid or q
        table = db.get(f"x{ndcId}", "SharedFiles")
        total = await table.count_documents(query)
        rows = [
            r
            async for r in table.find(query)
            .sort([("createdTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = await _files_json(db, ndcId, rows, viewer)
        return Base.Answer(
            {
                "fileList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/upload")
@shared_folder.post("/x{ndcId}/s/shared-folder/files")
@turtlelimiter(limit=10, period=TurtleTime.minute, tag="shared-folder-upload")
@validauth_required
async def upload_files(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        raw = data.get("mediaList") or ([data["media"]] if data.get("media") else [])
        media = [MediaList.Item(m) for m in raw]
    except Exception:
        return Errors.InvalidMediaContent(timestamp() - t1, lang=request.state.lang)
    if not media or len(media) > 50:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    title = str(data.get("title") or "")[:200]
    folder_id = data.get("folderId")
    db = await Database().init()
    try:
        if not await _may(db, ndcId, uid, "uploadPrivilege"):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        folders = db.get(f"x{ndcId}", "SharedFolders")
        if folder_id and not await folders.find_one(
            {"folderId": folder_id, "status": 0}, {"_id": 1}
        ):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        rows = []
        for m in media:
            row = {
                "fileId": str(uuid4()),
                "authorId": uid,
                "title": title,
                "media": m,
                "extensions": {},
                "votes": [],
                "commentsCount": 0,
                "status": 0,
                "referObjectId": data.get("referObjectId"),
                "referObjectType": data.get("referObjectType"),
                "createdTime": now_iso(),
                "modifiedTime": now_iso(),
            }
            await db.get(f"x{ndcId}", "SharedFiles").insert_one(dict(row))
            rows.append(row)
        if folder_id:
            await folders.update_one(
                {"folderId": folder_id},
                {"$push": {"fileIds": {"$each": [r["fileId"] for r in rows]}}},
            )
        return Base.Answer(
            {
                "fileIdList": [r["fileId"] for r in rows],
                "fileList": await _files_json(db, ndcId, rows, uid),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/files/batch-delete")
@validauth_required
async def delete_files(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = [str(i) for i in (await request.json()).get("fileIdList", [])][:100]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        staff = await staff_level(db, ndcId, uid)
        query = (
            {"fileId": {"$in": ids}}
            if staff
            else {"fileId": {"$in": ids}, "authorId": uid}
        )
        result = await db.get(f"x{ndcId}", "SharedFiles").update_many(
            query, {"$set": {"status": 9, "modifiedTime": now_iso()}}
        )
        return Base.Answer(
            {"deletedCount": result.modified_count}, spent_time=timestamp() - t1
        )
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/files/{fileId}")
async def get_file(request: Request, ndcId: int, fileId: str):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    db = await Database().init()
    try:
        row = await db.get(f"x{ndcId}", "SharedFiles").find_one({"fileId": fileId})
        if not row or (
            row.get("status") == 9
            and not await _owner_or_staff(db, ndcId, viewer, row.get("authorId"))
        ):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            {"file": (await _files_json(db, ndcId, [row], viewer))[0]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/files/{fileId}/title")
@validauth_required
async def rename_file(request: Request, ndcId: int, fileId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        title = str((await request.json()).get("title") or "")[:200]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFiles")
        row = await table.find_one({"fileId": fileId, "status": 0})
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if not await _owner_or_staff(db, ndcId, uid, row.get("authorId")):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        await table.update_one(
            {"fileId": fileId}, {"$set": {"title": title, "modifiedTime": now_iso()}}
        )
        row["title"] = title
        return Base.Answer(
            {"file": (await _files_json(db, ndcId, [row], uid))[0]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/folders")
async def list_folders(
    request: Request,
    ndcId: int,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFolders")
        total = await table.count_documents({"status": 0})
        rows = [
            r
            async for r in table.find({"status": 0})
            .sort([("position", ASCENDING), ("createdTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = [await _folder_json(db, ndcId, r, viewer) for r in rows]
        return Base.Answer(
            {
                "folderList": items,
                "allItemCount": total,
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/folders")
@validauth_required
async def create_folder(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        title = str(data.get("title") or "").strip()[:100]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if not title:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await _may(db, ndcId, uid, "albumManagePrivilege"):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "SharedFolders")
        last = await table.find_one({"status": 0}, sort=[("position", DESCENDING)])
        row = {
            "folderId": str(uuid4()),
            "authorId": uid,
            "title": title,
            "description": str(data.get("description") or "")[:2000],
            "folderType": 1,
            "fileIds": [],
            "position": (last or {}).get("position", -1) + 1,
            "status": 0,
            "createdTime": now_iso(),
            "modifiedTime": now_iso(),
        }
        await table.insert_one(dict(row))
        return Base.Answer(
            {"folder": await _folder_json(db, ndcId, row, uid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/folders/reorder")
@validauth_required
async def reorder_folders(request: Request, ndcId: int):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        ids = [str(i) for i in (await request.json()).get("folderIdList", [])][:200]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await staff_level(db, ndcId, uid):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "SharedFolders")
        for position, folder_id in enumerate(ids):
            await table.update_one(
                {"folderId": folder_id}, {"$set": {"position": position}}
            )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/folders/{folderId}")
async def get_folder(request: Request, ndcId: int, folderId: str):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    db = await Database().init()
    try:
        row = await db.get(f"x{ndcId}", "SharedFolders").find_one(
            {"folderId": folderId, "status": 0}
        )
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            {"folder": await _folder_json(db, ndcId, row, viewer)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/folders/{folderId}")
@validauth_required
async def edit_folder(request: Request, ndcId: int, folderId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    fields = {}
    if isinstance(data.get("title"), str) and data["title"].strip():
        fields["title"] = data["title"].strip()[:100]
    if isinstance(data.get("description"), str):
        fields["description"] = data["description"][:2000]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFolders")
        row = await table.find_one({"folderId": folderId, "status": 0})
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if not await _owner_or_staff(db, ndcId, uid, row.get("authorId")):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        if fields:
            await table.update_one(
                {"folderId": folderId}, {"$set": {**fields, "modifiedTime": now_iso()}}
            )
            row.update(fields)
        return Base.Answer(
            {"folder": await _folder_json(db, ndcId, row, uid)},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/folders/{folderId}/delete")
@shared_folder.delete("/x{ndcId}/s/shared-folder/folders/{folderId}")
@validauth_required
async def delete_folder(request: Request, ndcId: int, folderId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFolders")
        row = await table.find_one({"folderId": folderId, "status": 0})
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if not await _owner_or_staff(db, ndcId, uid, row.get("authorId")):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        # The album goes away; its photos stay in the shared folder.
        await table.update_one(
            {"folderId": folderId}, {"$set": {"status": 9, "modifiedTime": now_iso()}}
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/folders/{folderId}/files")
async def folder_files(
    request: Request,
    ndcId: int,
    folderId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        row = await db.get(f"x{ndcId}", "SharedFolders").find_one(
            {"folderId": folderId, "status": 0}
        )
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        ids = row.get("fileIds") or []
        by_id = {
            f["fileId"]: f
            async for f in db.get(f"x{ndcId}", "SharedFiles").find(
                {"fileId": {"$in": ids}, "status": 0}
            )
        }
        ordered = [by_id[i] for i in ids if i in by_id]
        chunk = ordered[start : start + size]
        items = await _files_json(db, ndcId, chunk, viewer)
        return Base.Answer(
            {
                "fileList": items,
                "allItemCount": len(ordered),
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/folders/{folderId}/files")
@validauth_required
async def change_folder_files(request: Request, ndcId: int, folderId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        action = str(data.get("action") or "add").lower()
        ids = [str(i) for i in data.get("fileIdList", [])][:200]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await _may(db, ndcId, uid, "albumManagePrivilege"):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        table = db.get(f"x{ndcId}", "SharedFolders")
        if not await table.find_one({"folderId": folderId, "status": 0}, {"_id": 1}):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if action == "remove":
            await table.update_one(
                {"folderId": folderId}, {"$pull": {"fileIds": {"$in": ids}}}
            )
        else:
            live = [
                f["fileId"]
                async for f in db.get(f"x{ndcId}", "SharedFiles").find(
                    {"fileId": {"$in": ids}, "status": 0}, {"fileId": 1}
                )
            ]
            await table.update_one(
                {"folderId": folderId}, {"$addToSet": {"fileIds": {"$each": live}}}
            )
        return Base.Answer({"success": True}, spent_time=timestamp() - t1)
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/files/{fileId}/joined-folders")
async def joined_folders(request: Request, ndcId: int, fileId: str):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    db = await Database().init()
    try:
        rows = [
            r
            async for r in db.get(f"x{ndcId}", "SharedFolders").find(
                {"fileIds": fileId, "status": 0}
            )
        ]
        return Base.Answer(
            {"folderList": [await _folder_json(db, ndcId, r, viewer) for r in rows]},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/files/{fileId}/vote")
@shared_folder.delete("/x{ndcId}/s/shared-folder/files/{fileId}/vote")
@validauth_required
async def vote_file(request: Request, ndcId: int, fileId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        op = "$pull" if request.method == "DELETE" else "$addToSet"
        result = await db.get(f"x{ndcId}", "SharedFiles").update_one(
            {"fileId": fileId, "status": 0}, {op: {"votes": uid}}
        )
        if result.matched_count == 0:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer({"success": True}, spent_time=timestamp() - t1)
    finally:
        db.close()


@shared_folder.get("/x{ndcId}/s/shared-folder/files/{fileId}/voters")
async def file_voters(
    request: Request, ndcId: int, fileId: str, start: int = 0, size: int = 25
):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    start, size = page(start, size)
    db = await Database().init()
    try:
        row = await db.get(f"x{ndcId}", "SharedFiles").find_one(
            {"fileId": fileId, "status": 0}, {"votes": 1}
        )
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        votes = (row.get("votes") or [])[start : start + size]
        users = [p for p in [await profile(db, ndcId, v, viewer) for v in votes] if p]
        return Base.Answer(
            {"userProfileList": users, "allItemCount": len(row.get("votes") or [])},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


def _comment_json(row: dict, author) -> dict:
    return {
        "commentId": row["commentId"],
        "content": row.get("content", ""),
        "createdTime": row.get("createdTime"),
        "createTime": row.get("createdTime"),
        "modifiedTime": row.get("modifiedTime") or row.get("createdTime"),
        "type": 0,
        "ndcId": row.get("ndcId"),
        "parentNdcId": row.get("ndcId"),
        "parentType": 109,
        "parentId": row.get("fileId"),
        "replyToCommentId": row.get("respondTo"),
        "mediaList": row.get("mediaList") or [],
        "stickerId": None,
        "extensions": {},
        "votesSum": 0,
        "votedValue": 0,
        "subcommentsCount": 0,
        "status": row.get("status", 0),
        "author": author,
    }


@shared_folder.get("/x{ndcId}/s/shared-folder/files/{fileId}/comment")
async def list_comments(
    request: Request,
    ndcId: int,
    fileId: str,
    start: int = 0,
    size: int = 25,
    pageToken: str | None = None,
):
    t1 = timestamp()
    viewer = request.state.session.get("uid")
    start, size = page(start, size, pageToken)
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFileComments")
        query = {"fileId": fileId, "status": 0}
        rows = [
            r
            async for r in table.find(query)
            .sort([("createdTime", DESCENDING)])
            .skip(start)
            .limit(size)
        ]
        items = [
            _comment_json(r, await profile(db, ndcId, r.get("authorId"), viewer))
            for r in rows
        ]
        return Base.Answer(
            {
                "commentList": items,
                "allItemCount": await table.count_documents(query),
                "paging": paging(start, size, items),
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.post("/x{ndcId}/s/shared-folder/files/{fileId}/comment")
@turtlelimiter(limit=5, period=TurtleTime.minute, tag="shared-folder-comment")
@validauth_required
async def add_comment(request: Request, ndcId: int, fileId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    try:
        data = await request.json()
        content = str(data.get("content") or "").strip()[:2000]
        media = [MediaList.Item(m) for m in (data.get("mediaList") or [])[:5]]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    if not content:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    db = await Database().init()
    try:
        if not await is_member(db, ndcId, uid):
            return Errors.UserNotJoined(timestamp() - t1, lang=request.state.lang)
        files = db.get(f"x{ndcId}", "SharedFiles")
        if not await files.find_one({"fileId": fileId, "status": 0}, {"_id": 1}):
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        row = {
            "commentId": str(uuid4()),
            "ndcId": ndcId,
            "fileId": fileId,
            "authorId": uid,
            "content": content,
            "mediaList": media,
            "respondTo": data.get("respondTo"),
            "status": 0,
            "createdTime": now_iso(),
            "modifiedTime": now_iso(),
        }
        await db.get(f"x{ndcId}", "SharedFileComments").insert_one(dict(row))
        await files.update_one({"fileId": fileId}, {"$inc": {"commentsCount": 1}})
        return Base.Answer(
            {"comment": _comment_json(row, await profile(db, ndcId, uid, uid))},
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()


@shared_folder.delete("/x{ndcId}/s/shared-folder/files/{fileId}/comment/{commentId}")
@validauth_required
async def delete_comment(request: Request, ndcId: int, fileId: str, commentId: str):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        table = db.get(f"x{ndcId}", "SharedFileComments")
        row = await table.find_one(
            {"commentId": commentId, "fileId": fileId, "status": 0}
        )
        if not row:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        if not await _owner_or_staff(db, ndcId, uid, row.get("authorId")):
            return Errors.NotEnoughRights(timestamp() - t1, lang=request.state.lang)
        await table.update_one({"commentId": commentId}, {"$set": {"status": 9}})
        await db.get(f"x{ndcId}", "SharedFiles").update_one(
            {"fileId": fileId}, {"$inc": {"commentsCount": -1}}
        )
        return Base.Answer(spent_time=timestamp() - t1)
    finally:
        db.close()
