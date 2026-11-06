import logging
from helpers.database.mongo import Database
from helpers.ws_outbox import enqueue, is_durable
import json
from typing import List, Optional
from helpers.database.redis import get as get_redis


WS_CHANNEL_CMD = "ws:commands"


class ApiBroadcastType:
    RawSend: int = 0
    InviteChatPush: int = 101
    ChatMessagePush: int = 102

    NewFollowerPush: int = 120
    NewCommunityMemberPush: int = 125


async def send_ws_message(
    message: dict, uids: Optional[List[str]] = None, type: int | None = None
):
    """
    uids=None -> for all users
    uids=[...] -> for selected
    """
    redis = get_redis()
    payload = {
        "message": message,
        "type": type if type is not None else ApiBroadcastType.RawSend,
    }
    if uids is not None:
        payload["uids"] = uids
    durable = False
    if isinstance(uids, list) and uids and is_durable(message, payload["type"]):
        db = await Database().init()
        try:
            await enqueue(db.get(), message, uids, payload["type"])
            durable = payload["_durable"] = True
        finally:
            db.close()
    try:
        await redis.publish(WS_CHANNEL_CMD, json.dumps(payload))
    except Exception as error:
        if not durable:
            raise
        # Polling workers still deliver persisted events if Redis is unavailable.
        logging.getLogger("altamino").warning(
            "WS wake-up unavailable; event persisted (%s)", error.__class__.__name__
        )
