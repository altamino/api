

import uuid
from time import time as timestamp

from helpers.database.mongo import Database


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_ms() -> int:
    return int(timestamp() * 1000)


async def create_notification(
    db: Database,
    ndcId: int,
    uid: str | list[str],
    authorUid: str,
    type: int,
    parentType: int | None = None,
    parentId: str | None = None,
    parentText: str | None = None,
    objectId: str | None = None,
    objectType: int | None = None,
    objectSubtype: int | None = None,
    objectText: str | None = None,
    contextText: str | None = None,
    contextValue: str | None = None,
    contextNdcId: int | None = None,
):
    table = db.get(f"x{ndcId}", "Notifications")

    uids = [uid] if isinstance(uid, str) else uid
    if not uids:
        return []

    created_time = _now_ms()
    documents = []

    for target_uid in uids:
        if target_uid == authorUid:
            continue

        documents.append({
            "id": _new_id(),
            "uid": target_uid,
            "authorUid": authorUid,
            "type": type,
            "parentType": parentType,
            "parentId": parentId,
            "parentText": parentText,
            "objectId": objectId,
            "objectType": objectType,
            "objectSubtype": objectSubtype,
            "objectText": objectText,
            "contextText": contextText,
            "contextValue": contextValue,
            "contextNdcId": contextNdcId,
            "createdTime": created_time,
            "read": False,
        })

    if documents:
        await table.insert_many(documents)

    return documents


async def create_notice(
    db: Database,
    ndcId: int,
    targetUid: str | list[str],
    operatorUid: str,
    title: str,
    type: int,
    status: int = 1,
    notificationId: str | None = None,
):
    table = db.get(f"x{ndcId}", "Notices")

    target_uids = [targetUid] if isinstance(targetUid, str) else targetUid
    if not target_uids:
        return []

    created_time = _now_ms()
    documents = []

    for uid in target_uids:
        documents.append({
            "id": _new_id(),
            "notificationId": notificationId or _new_id(),
            "targetUid": uid,
            "operatorUid": operatorUid,
            "title": title,
            "type": type,
            "status": status,
            "createdTime": created_time,
        })

    if documents:
        await table.insert_many(documents)

    return documents