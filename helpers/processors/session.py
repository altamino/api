from orjson import dumps, loads
from .cache import CacheProcessor
from secrets import token_urlsafe

class SessionProcessor:
    """
    Processor for making and getting sessions.
    """

    @staticmethod
    async def Make(user_id: str, ip: str, client_type: int = 100) -> str:
        """
        Returning string key for headers.

        **It's NOT decodable.**
        Key is random string from bunch of symbols
        to prevent session generation.
        """
        prefix = "sid="
        timeout = 86400                 # its a day :з
        
        key = token_urlsafe(1663)
        data = dumps({
            "uid": user_id,
            "ip": ip,                   # one session one ip? maybe someday...~
            "client_type": client_type
        })
        
        await CacheProcessor.Make(key, data, prefix, 86400)

        return key
    
    @staticmethod
    async def Get(session: str | bytes) -> dict | None:
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
        if not session: return None
        if isinstance(session, bytes): session = session.decode()
        info = await CacheProcessor.Get(session)

        return loads(info) if info else None
        
