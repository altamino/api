_connection = None

from ..config import Config
from redis import asyncio as aioredis

def get():
    global _connection
    if not _connection:
        _connection = aioredis.from_url(
            Config.REDIS_CONNECTION_STRING,
            decode_responses=True
        )
    return _connection