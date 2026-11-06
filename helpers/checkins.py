import base64
from datetime import datetime, timedelta, timezone as _tz
from fastapi import Request

from helpers.database.redis import get as get_redis


CHECKIN_COIN_REWARDS = [1.0, 2.0, 3.0, 10.0]
CHECKIN_COIN_WEIGHTS = [0.50, 0.30, 0.15, 0.05]

LOTTERY_REWARDS = [2.0, 5.0, 10.0]
LOTTERY_WEIGHTS = [0.40, 0.30, 0.20]

REP_CAP = 20
SECONDS_PER_DAY = 86400

REPAIR_COIN_COST = 30
REPAIR_WINDOW_SIZE = 7
REPAIR_METHOD_COIN = 1
REPAIR_METHOD_AMINOPLUS = 2


def local_date(tz_minutes: int) -> datetime:
    dt = datetime.now(_tz.utc) + timedelta(minutes=tz_minutes)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def date_str(dt) -> str:
    return dt.strftime("%Y-%m-%d")


def iso_to_unix(s) -> int:
    if not s:
        return 0
    if isinstance(s, (int, float)):
        return int(s)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return int(dt.timestamp())


async def get_tz(request: Request) -> int:
    tz = request.query_params.get("timezone")
    if tz is not None:
        try:
            return int(tz)
        except ValueError:
            return 0
    try:
        body = await request.json()
        return int(body.get("timezone", 0))
    except Exception:
        return 0


def _joined_date(row: dict):
    u = iso_to_unix(row.get("createdTime"))
    return datetime.fromtimestamp(u, _tz.utc).date() if u else None


def compute_streak(history: dict, today: datetime) -> int:
    streak = 0
    cur = today
    while history.get(date_str(cur)):
        streak += 1
        cur -= timedelta(days=1)
    return streak


def compute_broken_streaks(history: dict, row: dict, today: datetime) -> int:

    joined = _joined_date(row)
    if joined is None or not history:
        return 0
    broke = 0
    cur = today - timedelta(days=1)
    while cur.date() >= joined:
        if not history.get(date_str(cur)):
            broke += 1
        cur -= timedelta(days=1)
    return broke


def has_check_in_today(history: dict, today: datetime) -> bool:
    return bool(history.get(date_str(today)))


def earned_rep(streak: int) -> int:
    return min(1 + streak, REP_CAP)


def build_history_b64(history, start_dt, stop_dt) -> str:
    num_days = (stop_dt.date() - start_dt.date()).days + 1
    if num_days <= 0:
        return ""
    byte_arr = bytearray((num_days + 7) // 8)
    for i in range(num_days):
        day = date_str(start_dt + timedelta(days=i))
        hit = history.get(day) if isinstance(history, dict) else (day in history)
        if hit:
            byte_arr[i // 8] |= 1 << (7 - (i % 8))
    return base64.b64encode(bytes(byte_arr)).decode()


def build_checkin_history_obj(row: dict, tz: int, window_days: int = 30) -> dict:
    today = local_date(tz)
    start_dt = today - timedelta(days=window_days)
    history = row.get("checkInHistory", {}) or {}

    return {
        "joinedTime": iso_to_unix(row.get("createdTime")),
        "startTime": int(start_dt.timestamp()),
        "stopTime": int(today.timestamp()),
        "consecutiveCheckInDays": compute_streak(history, today),
        "hasCheckInToday": has_check_in_today(history, today),
        "hasAnyCheckIn": bool(history),
        "history": build_history_b64(history, start_dt, today),
        "streakRepairCoinCost": REPAIR_COIN_COST,
        "streakRepairWindowSize": REPAIR_WINDOW_SIZE,
    }


async def settle_user_active_coins(db, uid: str) -> float:
    redis = get_redis()
    today = datetime.now(_tz.utc).strftime("%Y-%m-%d")

    keys = await redis.keys(f"user:{uid}:active_sec:*")
    total = 0.0

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        date_part = key_str.split(":")[-1]
        if date_part == today:
            continue
        seconds_val = await redis.get(key)
        if seconds_val:
            try:
                total += round((float(seconds_val) / 3600.0) * 4.0, 2)
            except (ValueError, TypeError):
                pass
        await redis.delete(key)

    if total > 0:
        total = round(total, 2)
        await db.get(table="Users").update_one({"id": uid}, {"$inc": {"coins": total}})
        from helpers import coin_ledger

        await coin_ledger.record(db, uid, total, "active_time_reward")
    return total


def build_reminder_history(row: dict, today: datetime, days: int = 7) -> dict:
    history = row.get("checkInHistory", {}) or {}
    start = today - timedelta(days=days - 1)

    return {
        "joinedTime": iso_to_unix(row.get("createdTime")),
        "startTime": int(start.timestamp()),
        "stopTime": int(today.timestamp()),
        "consecutiveCheckInDays": compute_streak(history, today),
        "hasCheckInToday": has_check_in_today(history, today),
        "hasAnyCheckIn": bool(history),
        "history": build_history_b64(history, start, today),
        "streakRepairCoinCost": REPAIR_COIN_COST,
        "streakRepairWindowSize": REPAIR_WINDOW_SIZE,
    }


def build_reminder_result(row: dict | None, today: datetime) -> dict:
    row = row or {}
    history = row.get("checkInHistory", {}) or {}
    return {
        "hasCheckInToday": has_check_in_today(history, today),
        "consecutiveCheckInDays": compute_streak(history, today),
        "checkInHistory": build_reminder_history(row, today),
        "notificationsCount": 0,
        "noticesCount": 0,
        "noticesCount2": 0,
        "unreadChatThreadsCount": 0,
    }
