from typing import Optional, Union, Any

from helpers.database.redis import get


class CacheProcessor:
    @staticmethod
    def _redis_key(key: str, prefix: str = "") -> str:
        key = CacheProcessor._norm(key)
        prefix = CacheProcessor._norm(prefix)
        if prefix != "" and key.startswith(prefix):
            return key
        return prefix + key

    @staticmethod
    def _norm(x: Union[str, bytes, None]) -> str:
        if x is None:
            return ""
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="ignore")
        return str(x)

    @staticmethod
    async def Make(
        key: str,
        value: str | bytes | int,
        prefix: str = "",
        expiring_after: Optional[int] = None,
    ) -> None:
        if value is None:
            return

        redis = get()
        final_key = CacheProcessor._redis_key(key, prefix)

        await redis.set(final_key, value, expiring_after)

    @staticmethod
    async def Update(
        key: str,
        value: str | bytes | int | None = None,
        prefix: str = "",
        expiring_after: Optional[int] = None,
        keep_ttl: bool = False,
        increment: bool = False,
    ) -> None:

        redis = get()
        full_key = CacheProcessor._redis_key(key, prefix)

        if increment:
            await redis.incr(full_key)
            return

        if value is None and expiring_after is not None:
            await redis.expire(full_key, expiring_after)
            return
        if value is None:
            return  # idk

        await redis.set(full_key, value, expiring_after, keepttl=keep_ttl)

    @staticmethod
    async def Get(
        key: str | bytes,
        prefix: str = "",
    ) -> Optional[Any]:

        redis = get()

        full_key = CacheProcessor._redis_key(key, prefix)

        return await redis.get(full_key)

    @staticmethod
    async def Delete(
        key: str,
        prefix: str = "",
    ) -> Optional[int]:

        redis = get()

        full_key = CacheProcessor._redis_key(key, prefix)

        return await redis.unlink(full_key)

    @staticmethod
    async def SetAdd(
        key: str,
        member: str,
        prefix: str = "",
        expiring_after: Optional[int] = None,
    ) -> None:
        """Add member to a redis set; refresh the set TTL if given."""
        redis = get()
        full_key = CacheProcessor._redis_key(key, prefix)

        await redis.sadd(full_key, member)
        if expiring_after is not None:
            await redis.expire(full_key, expiring_after)

    @staticmethod
    async def SetRemove(
        key: str,
        member: str,
        prefix: str = "",
    ) -> None:
        redis = get()
        full_key = CacheProcessor._redis_key(key, prefix)

        await redis.srem(full_key, member)

    @staticmethod
    async def SetMembers(
        key: str,
        prefix: str = "",
    ) -> list[str]:
        redis = get()
        full_key = CacheProcessor._redis_key(key, prefix)

        members = await redis.smembers(full_key)
        return [CacheProcessor._norm(m) for m in members]
