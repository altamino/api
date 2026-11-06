"""Shared checks for the community feature routers (catalog, shared folder, flags, fan clubs...)."""

from datetime import UTC, datetime

from helpers.functions import calculate_page_tokens, parse_page_token

LEFT_OR_BANNED = (5, 9, 10)


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def page(start: int, size: int, pageToken: str | None = None, max_size: int = 100):
    size = size if 0 < size <= max_size else 25
    return max(0, parse_page_token(pageToken, start)), size


def paging(start: int, size: int, items: list) -> dict:
    return calculate_page_tokens(start, size, items)


async def is_member(db, ndcId: int, uid: str | None) -> bool:
    """Active member of the community (or its agent); global scope only needs an account."""
    if not uid:
        return False
    if ndcId == 0:
        return True
    row = await db.get(f"x{ndcId}", "Users").find_one({"id": uid}, {"status": 1})
    if row is None or row.get("status", 0) in LEFT_OR_BANNED:
        return False
    community = await db.get(table="Communities").find_one(
        {"id": ndcId, "$or": [{"memberList": uid}, {"agent": uid}]}, {"_id": 1}
    )
    return community is not None


async def staff_level(db, ndcId: int, uid: str | None) -> int:
    """0 = no staff rights; 1 curator; 2 leader/agent; 3 global staff (same scale as moderation)."""
    if not uid:
        return 0
    from routers.moderation_tools import check_rights

    allowed, level = await check_rights(db, uid, ndcId, only_gods=(ndcId == 0))
    return level if allowed else 0


async def profile(db, ndcId: int, uid: str | None, viewer: str | None = None):
    if not uid:
        return None
    table = db.get(f"x{ndcId}", "Users") if ndcId else db.get(table="Users")
    row = await table.find_one({"id": uid})
    if not row:
        return None
    from objects import User

    return User.GetUserInfo(row, ndcId=ndcId, triggerUserId=viewer)


def module_config(community: dict | None, name: str) -> dict:
    conf = (community or {}).get("configuration") or {}
    mods = conf.get("modules") or {}
    value = mods.get(name)
    if isinstance(value, bool):  # older communities store the switch alone
        return {"enabled": value}
    return value if isinstance(value, dict) else {}


async def pending_staff_counts(db, ndcId: int, uid: str | None) -> dict:
    """communityGeneralCheckResult: red dots of the side menu (Flag Center, wiki submissions).
    Only staff get numbers; everybody else sees zeros."""
    # pendingShareRequestCountMapping must stay null: the 3.4 client unboxes map.get(114) whenever
    # the map exists, and an empty map crashes it on entering the community.
    result = {
        "pendingFlagCount": 0,
        "pendingKnowledgeBaseRequestCount": 0,
        "pendingShareRequestCountMapping": None,
    }
    if not await staff_level(db, ndcId, uid):
        return result
    result["pendingFlagCount"] = len(
        await db.get(f"x{ndcId}", "Flags").distinct("objectId", {"status": "pending"})
    )
    result["pendingKnowledgeBaseRequestCount"] = await db.get(
        f"x{ndcId}", "KnowledgeBaseRequests"
    ).count_documents({"status": 1})
    return result
