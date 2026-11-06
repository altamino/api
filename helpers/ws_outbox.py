"""Bounded Mongo outbox; Redis is a wake-up signal, never the durable store.

Delivery is at least once at the socket-write boundary (native client has no ACK).
Messages/notifications remain the authoritative, unbounded REST history.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from bson import BSON

MAX_EVENTS = 128
RETENTION = timedelta(days=3)


def is_durable(message, kind):
    if not isinstance(message, dict) or len(BSON.encode({"message": message})) > 65536:
        return False
    if kind in (101, 120, 125):
        return True
    chat = (
        message.get("o", {}).get("chatMessage", {}) if isinstance(message, dict) else {}
    )
    return kind == 0 and message.get("t") == 1000 and chat.get("type") in (0, 2, 3, 100)


async def enqueue(database, message, targets, kind=0):
    now = datetime.now(timezone.utc)
    seq = {"$add": [{"$ifNull": ["$sequence", 0]}, 1]}
    event = {
        "seq": seq,
        "command": {"$literal": {"message": message, "type": kind}},
        "createdAt": {"$literal": now},
    }
    for uid in dict.fromkeys(targets):
        if not isinstance(uid, str) or not uid:
            continue
        await database["WsOutbox"].update_one(
            {"_id": uid},
            [
                {
                    "$set": {
                        "epoch": {"$ifNull": ["$epoch", {"$literal": str(uuid4())}]},
                        "sequence": seq,
                        "events": {
                            "$slice": [
                                {
                                    "$concatArrays": [
                                        {"$ifNull": ["$events", []]},
                                        [event],
                                    ]
                                },
                                -MAX_EVENTS,
                            ]
                        },
                        "expiresAt": {"$literal": now + RETENTION},
                    }
                }
            ],
            upsert=True,
        )


async def load_after(database, uid, cursor, epoch=None):
    cutoff = datetime.now(timezone.utc) - RETENTION
    after = (
        cursor
        if epoch is None
        else {"$cond": [{"$eq": ["$epoch", {"$literal": epoch}]}, cursor, 0]}
    )
    row = await database["WsOutbox"].find_one(
        {"_id": uid},
        {
            "sequence": 1,
            "epoch": 1,
            "events": {
                "$filter": {
                    "input": "$events",
                    "as": "e",
                    "cond": {
                        "$and": [
                            {"$gt": ["$$e.seq", after]},
                            {"$gte": ["$$e.createdAt", cutoff]},
                        ]
                    },
                }
            },
        },
    )
    return row or {}


async def acknowledge(database, key, sequence, epoch):
    await database["WsDeliveryCursors"].update_one(
        {"_id": key},
        [
            {
                "$set": {
                    "sequence": {
                        "$cond": [
                            {"$eq": ["$epoch", {"$literal": epoch}]},
                            {"$max": [{"$ifNull": ["$sequence", 0]}, sequence]},
                            sequence,
                        ]
                    },
                    "epoch": {"$literal": epoch},
                    "expiresAt": {"$literal": datetime.now(timezone.utc) + RETENTION},
                }
            }
        ],
        upsert=True,
    )
