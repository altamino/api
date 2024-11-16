from helpers.database.redis import get
from typing import Optional


class CacheProcessor:
    """
    Processor for making and getting caches.
    """

    @staticmethod
    async def Make(
        key: str, value: str | bytes, prefix: str = "", expiring_after: int = None
    ) -> None:
        """
        Making cache of data by prefix+key.

        Prefix is empty by default and you can not provide it.
        """
        redis = get()
        await redis.set(prefix + key, value, expiring_after)

    @staticmethod
    async def Get(key: str, prefix: str = "") -> Optional[dict]:
        """
        None if there is no cache by provided key and prefix,
        "any" type when there is something.
        """
        redis = get()
        return await redis.get(prefix + key)
