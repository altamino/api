# from re import findall
from re import findall
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from orjson import dumps, loads

from helpers.functions import get_hashed_ip, make_hash
from helpers.processors.cache import CacheProcessor
from helpers.processors.request import RequestProcessor
from objects.errors import Errors


class CachableRoute(APIRoute):
    main_headers = {
        "content-type": "application/json; charset=utf-8",
        "server": "AltAmino Open Server",
    }

    async def make_key_for_cache(self, request: Request) -> str:
        """
        Hey, we really need to think how to properly cache
        requests. Some values are dynamic.
        """
        body = await request.body() or b""
        if body:
            return make_hash(
                request.scope["method"],
                request.scope["raw_path"],
                str(request.headers),
                body,
            )
        else:
            return make_hash(
                request.scope["method"],
                request.scope["raw_path"],
                request.scope["query_string"],
                str(request.headers),
            )

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            if "verification-code" in request.scope["path"]:
                return await original_route_handler(request)

            # if ip blocked
            hashed_ip = get_hashed_ip(request)
            ip_info = await CacheProcessor.Get(hashed_ip, "ip:")
            if ip_info:
                await CacheProcessor.Make(hashed_ip, 5, "ip:", 300)
                return Errors.IpFrozen()

            # Stateful private streams must authenticate and read current storage.
            path = request.scope["path"]
            live = any(
                part in path
                for part in ("/chat/", "/notification", "/notice", "/reminder")
            )
            if (
                live
                or request.headers.get("NDCAUTH")
                or request.method not in ("GET", "HEAD")
            ):
                valid, error = await RequestProcessor.Validate(request)
                if not valid:
                    return error
                response = await original_route_handler(request)
                response.headers.update(self.main_headers)
                response.headers["cache-control"] = "no-store"
                return response

            # if request cached
            key = await self.make_key_for_cache(request)
            result = await CacheProcessor.Get(key, "creq:")
            if result:
                result = loads(result)

                return JSONResponse(
                    loads(result["response"]),
                    result["status_code"],
                    self.main_headers,
                    result["media_type"],
                )

            # validating request
            valid, error = await RequestProcessor.Validate(request)
            if not valid:
                return error

            # processing request and caching
            response = await original_route_handler(request)
            response.headers.update(self.main_headers)

            await CacheProcessor.Make(
                key,
                dumps(
                    {
                        "response": response.body.decode(),
                        "status_code": response.status_code,
                        "media_type": response.media_type,
                    }
                ),
                "creq:",
                (
                    2
                    if findall(r"(chat|thread)", request.scope["raw_path"].decode())
                    else 60
                ),
            )

            return response

        return custom_route_handler
