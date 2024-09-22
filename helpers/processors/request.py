from objects.errors import Errors
from .device import DeviceProcessor
from .session import SessionProcessor
from .signature import SignatureProcessor
from .useragent import UserAgentProcessor

from math import ceil
from time import time
from orjson import loads
from fastapi import Request
from typing import Union, Optional
from fastapi.responses import ORJSONResponse

class RequestProcessor:
    """
    Processor that validates request in middleware.
    Looks like it have 4 subprocessors. Or we can it call cores? :D

    Made for shorten the code in middleware.
    """

    @staticmethod
    def __is_timestamp_valid(timestamp: int | str):
        '''
            True if timestamp is good, False if bad
        '''
        if isinstance(timestamp, str):
            if timestamp.isdigit(): timestamp = int(timestamp)
            else: return False
        return ceil(time()) - ceil(timestamp/1000) <= 5

    @staticmethod
    async def Validate(request: Request) -> Union[bool, Optional[ORJSONResponse]]:
        """
        pass da request and it will check all possible things here

        if request is good, first element of list (bool) will be true
        else second element will contain an error that you can just send to user

        the design is very human
        """

        headers = request.headers
        data = await request.body() or bytes()
        user_agent = headers.get("user-agent", "INVALID")

        if (
            user_agent == "INVALID"
        ) or (
            not UserAgentProcessor.Validate(user_agent)
        ):
            return [False, Errors.UnsupportedClient()]
        
        """
        [TODO]: making cool too many requests
        Blocking IPs as Amino does is stupid. So I have two ideas:
        1. We can block an account or IP if it makes too many
        requests. No blocking IP just because "it's probably a
        server". The more requests, the more time in block. Also
        I'm saying account without jokes. We can totally block
        account from doing any requests for a period of time. 
        2. We can just start resetting the connection between
        account or IP and servers if account or IP makes too many
        requests. And the more requests, the more often connection
        reset will appear and the more time it will happen.
        I think it will cause damage to scripts because of dumb
        coders or because of time they need to wait. 
        """

        # TODO:
        # deprecate "service.aminoapps.com" and "service.narvii.com"
        # since its useless
        if headers.get("Host") not in ["service.narvii.com", "service.aminoapps.com", "service.altamino.top"]:
            return [False, Errors.SUS()]
        
        if not DeviceProcessor.Validate(headers.get("NDCDEVICEID", "")):
            return [False, Errors.UnsupportedClient()]
        
        possible_session = await SessionProcessor.Get(headers.get("NDCAUTH"))
        if possible_session:
            auid = headers.get("AUID")
            if not auid or auid != possible_session['uid']:
                return [False, Errors.InvalidSession()]
            
            # TODO: maybe its insecure, we need to check it
            request.state.session = {"validsession": True} | possible_session
        else:
            request.state.session = {"validsession": False}
        
        # non-get request checks
        if request.method in ['POST', 'DELETE']:
            if headers.get("Content-Type") not in [
                "image/jpg", "image/jpeg", "image/png", "image/webp", "image/gif",
                'application/x-www-form-urlencoded', 'application/octet-stream',
                'application/json', 'application/json; charset=utf-8'
            ]:
                return [False, Errors.InvalidRequest()]
            
            content_length = headers.get("Content-Length", "0")
            if not content_length.isdigit():
                return [False, Errors.InvalidRequest()]
            else:
                content_length = int(content_length)
            # check if content_length is valid

            # since urlencoded is a little bit buggy (and required only when requests are empty as octets)
            if headers['Content-Type'] == 'application/x-www-form-urlencoded':
                if len(data) > 2 or content_length > 2:
                    return [False, Errors.InvalidRequest()]
            elif "media/upload" not in request.url.path:
                if not SignatureProcessor.Validate(headers.get("NDC-MSG-SIG", ""), data):
                    return [False, Errors.InvalidRequest()]
            

            if data and "media/upload" not in request.scope['path']:
                try:
                    json = loads(data)
                
                    if not RequestProcessor.__is_timestamp_valid(json.get("timestamp", 0)):
                        return [False, Errors.ExpiredRequest()]
                except:
                    return [False, Errors.InvalidRequest()]
                
        return [True, None]
                
            

