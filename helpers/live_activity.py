"""REST companion for the additional native WS activity categories."""

import json
from helpers.database.redis import get as get_redis

TOPICS = {
    "users-playing-quizzes": "Playing",
    "users-polling-polls": "Polling",
    "users-commenting-blogs": "Commenting",
    "users-voting-blogs": "Voting",
}


async def activity_users(ndc, topic):
    name = topic.rsplit(":", 1)[-1]
    if name not in TOPICS:
        return None
    result = set()
    redis = get_redis()
    async for key in redis.scan_iter(match=f"x{ndc}:activity:*", count=100):
        raw = await redis.get(key)
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if (
            entry.get("visible")
            and TOPICS[name] in entry.get("actions", [])
            and isinstance(entry.get("uid"), str)
        ):
            result.add(entry["uid"])
    return sorted(result)
