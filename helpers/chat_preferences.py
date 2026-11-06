"""Per-reader pins and scoped recent-chat resolution using existing Mongo data."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID


def parse_thread_ids(q):
    parts = (q or "").split(",")
    if len(parts) > 100:
        raise ValueError("Too many thread IDs")
    ids = []
    for part in parts:
        if not part.strip():
            continue
        value = str(UUID(part.strip()))
        if value not in ids:
            ids.append(value)
    return ids


async def accessible_scopes(db, uid, ndc_id, all_scopes=True):
    if ndc_id or not all_scopes:
        candidates = [ndc_id]
    else:
        user = (
            await db.get(table="Users").find_one({"id": uid}, {"communityList": 1})
            or {}
        )
        candidates = [0] + list(
            dict.fromkeys(
                int(i)
                for i in user.get("communityList", [])
                if str(i).isdigit() and int(i) > 0
            )
        )
    gate = asyncio.Semaphore(8)

    async def allowed(ndc):
        async with gate:
            member = await db.get(f"x{ndc}", "Users").find_one(
                {"id": uid}, {"status": 1}
            )
            return ndc if member and member.get("status", 0) == 0 else None

    return [
        i
        for i in await asyncio.gather(*(allowed(i) for i in candidates))
        if i is not None
    ]


async def pin_ids(db, uid, ndc_id):
    return {
        r["threadId"]
        async for r in db.get(table="ChatPreferences").find(
            {"uid": uid, "ndcId": ndc_id, "isPinned": True}, {"threadId": 1}
        )
    }


async def is_pinned(db, uid, ndc_id, thread_id):
    return bool(
        await db.get(table="ChatPreferences").find_one(
            {"_id": f"{uid}:{ndc_id}:{thread_id}", "isPinned": True}, {"_id": 1}
        )
    )


async def set_pin(db, uid, ndc_id, thread_id, pinned):
    member = await db.get(f"x{ndc_id}", "Users").find_one({"id": uid}, {"status": 1})
    if not member or member.get("status", 0) != 0:
        return False
    chat = await db.get(f"x{ndc_id}", "Chats").find_one(
        {"id": thread_id, "$or": [{"memberList": uid}, {"invitedList": uid}]}, {"id": 1}
    )
    if not chat:
        return False
    await db.get(table="ChatPreferences").update_one(
        {"_id": f"{uid}:{ndc_id}:{thread_id}"},
        {
            "$set": {
                "uid": uid,
                "ndcId": ndc_id,
                "threadId": thread_id,
                "isPinned": pinned,
                "updatedAt": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    return True


def activity_ms(row):
    value = row.get("lastMessageTimestamp", row.get("timestamp", 0))
    if isinstance(value, datetime):
        return int(
            value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp() * 1000
        )
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


async def recent_rows(
    db, uid, ndc_id, ids=None, size=25, start=0, stop_ms=None, *, all_scopes=True
):
    scopes = await accessible_scopes(db, uid, ndc_id, all_scopes=all_scopes)
    gate = asyncio.Semaphore(8)

    async def fetch(ndc):
        async with gate:
            query = {"$or": [{"memberList": uid}, {"invitedList": uid}]}
            if ids is not None:
                query["id"] = {"$in": ids}
            if stop_ms is not None:
                query["lastMessageTimestamp"] = {"$lt": stop_ms}
            pins = await pin_ids(db, uid, ndc)
            # Fetch all pins separately so a quiet pinned room survives pagination.
            rows = [
                r
                async for r in db.get(f"x{ndc}", "Chats")
                .find(query)
                .sort([("lastMessageTimestamp", -1), ("id", 1)])
                .limit(start + size)
            ]
            if pins:
                pinned_query = dict(
                    query,
                    id={"$in": list(pins & set(ids) if ids is not None else pins)},
                )
                rows += [r async for r in db.get(f"x{ndc}", "Chats").find(pinned_query)]
            unique = {r["id"]: (ndc, r, r["id"] in pins) for r in rows}
            return list(unique.values())

    rows = [
        row
        for group in await asyncio.gather(*(fetch(i) for i in scopes))
        for row in group
    ]
    if ids is not None:
        order = {id_: i for i, id_ in enumerate(ids)}
        rows.sort(key=lambda r: (order[r[1]["id"]], r[0]))
    else:
        rows.sort(key=lambda r: (not r[2], -activity_ms(r[1]), r[0], r[1]["id"]))
    return rows[start : start + size]
