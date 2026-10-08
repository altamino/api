from orjson import dumps, loads
from .cache import CacheProcessor
from secrets import token_urlsafe



class SessionProcessor:
    """
    Processor for making and getting sessions.
    """

    PREFIX = "sid="
    USER_INDEX_PREFIX = "user_sessions:"
    TIMEOUT = 86400  # its a day :з

    @staticmethod
    def _token(session: str | bytes) -> str:
        """Токен без префикса 'sid=' (для индекса по пользователю)."""
        if isinstance(session, bytes):
            session = session.decode()
        if session.startswith(SessionProcessor.PREFIX):
            session = session[len(SessionProcessor.PREFIX):]
        return session

    @staticmethod
    async def Make(user_id: str, ip: str, client_type: int = 100) -> str:
        """
        Returning string key for headers.

        **It's NOT decodable.**
        Key is random string from bunch of symbols
        to prevent session generation.
        """
        key = token_urlsafe(1663)
        data = dumps(
            {
                "uid": user_id,
                "ip": ip,  # one session one ip? maybe someday...~
                "client_type": client_type,
            }
        )

        await CacheProcessor.Make(
            key, data, SessionProcessor.PREFIX, SessionProcessor.TIMEOUT
        )
        # индекс: user_id -> токены его сессий
        await CacheProcessor.SetAdd(
            user_id, key, SessionProcessor.USER_INDEX_PREFIX, SessionProcessor.TIMEOUT
        )

        return key

    @staticmethod
    async def Get(session: str | bytes | None) -> dict | None:
        """
        dict if session is valid, None if not

        dict contains:
        - uid
        - ip
        - client_type

        no timestamp needed since session stored in redis
        and time of live of session is exactly 24 hours
        (in mr beast basement)
        """
        if not session:
            return None
        if isinstance(session, bytes):
            session = session.decode()
        info = await CacheProcessor.Get(session, SessionProcessor.PREFIX)

        return loads(info) if info else None

    @staticmethod
    async def GetByUser(user_id: str) -> list[dict]:
        """
        All active sessions of the user.

        Each dict contains: uid, ip, client_type and sid (token).
        Expired sessions are removed from the index along the way.
        """
        tokens = await CacheProcessor.SetMembers(
            user_id, SessionProcessor.USER_INDEX_PREFIX
        )

        sessions: list[dict] = []
        for token in tokens:
            info = await SessionProcessor.Get(token)
            if info is None:
                # сессия истекла, чистим индекс
                await CacheProcessor.SetRemove(
                    user_id, token, SessionProcessor.USER_INDEX_PREFIX
                )
                continue
            info["sid"] = token
            sessions.append(info)

        return sessions

    @staticmethod
    async def End(session: str | bytes | None) -> bool | None:
        """
        end the session if it exist
        """
        if not session:
            return None

        token = SessionProcessor._token(session)
        info = await SessionProcessor.Get(token)

        result = await CacheProcessor.Delete(token, SessionProcessor.PREFIX)

        if info:
            await CacheProcessor.SetRemove(
                info["uid"], token, SessionProcessor.USER_INDEX_PREFIX
            )
        return bool(result or 0)

    @staticmethod
    async def EndAllByUser(user_id: str) -> int:
        """
        end all sessions of the user (logout everywhere, ban, password change).
        Returns how many sessions were deleted.
        """
        tokens = await CacheProcessor.SetMembers(
            user_id, SessionProcessor.USER_INDEX_PREFIX
        )

        count = 0
        for token in tokens:
            result = await CacheProcessor.Delete(token, SessionProcessor.PREFIX)
            count += int(bool(result or 0))

        await CacheProcessor.Delete(user_id, SessionProcessor.USER_INDEX_PREFIX)
        return count