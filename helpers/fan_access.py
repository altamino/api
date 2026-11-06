"""Fan club access: subscribers-only posts belong to one creator inside one community."""

from datetime import UTC, datetime


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


async def club_enabled(db, ndcId: int, creator_uid: str) -> dict | None:
    return await db.get(table="FanClubs").find_one(
        {"ndcId": ndcId, "creatorUid": creator_uid, "enabled": True}
    )


async def active_subscription(
    db, ndcId: int, creator_uid: str, fan_uid: str
) -> dict | None:
    sub = await db.get(table="FanSubscriptions").find_one(
        {"ndcId": ndcId, "creatorUid": creator_uid, "fanUid": fan_uid}
    )
    if not sub:
        return None
    if sub.get("expiresAt") and sub["expiresAt"] > utcnow():
        return sub
    from helpers.renewals import (
        renew_fan_subscription,
    )  # a due auto-renewal is charged right here

    return await renew_fan_subscription(db, sub)


async def can_read_fan_content(
    db, ndcId: int, creator_uid: str | None, viewer_uid: str | None
) -> bool:
    if not viewer_uid or not creator_uid:
        return False
    if viewer_uid == creator_uid:
        return True
    from helpers.community_access import is_member, staff_level

    if await staff_level(db, ndcId, viewer_uid):
        return True  # moderators must be able to review reported content
    if not await club_enabled(db, ndcId, creator_uid) or not await is_member(
        db, ndcId, viewer_uid
    ):
        return False
    return await active_subscription(db, ndcId, creator_uid, viewer_uid) is not None


async def can_use_fans_chat(db, ndcId: int, chat: dict | None, uid: str | None) -> bool:
    """Fans-only chats: host, co-hosts, staff and active subscribers of the host's club."""
    if not chat or not chat.get("fansOnly"):
        return True
    if uid and (uid == chat.get("hostId") or uid in (chat.get("cohostsIds") or [])):
        return True
    return await can_read_fan_content(db, ndcId, chat.get("hostId"), uid)
