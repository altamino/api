from functools import wraps
from time import time as timestamp

from fastapi import Request
from objects import Errors
from helpers.database.mongo import Database
from objects.types import UserRole


def not_banned(check_global: bool = True):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            t1 = timestamp()
            request: Request = kwargs["request"]
            session = request.state.session

            if not session["validsession"]:
                return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

            uid = session["uid"]
            ndcId = kwargs.get("ndcId", 0)

            db = await Database().init()
            try:
                if check_global or ndcId == 0:
                    row = await db.get(table="Users").find_one({"id": uid})
                    if row and row.get("status", 0) == 9:
                        return Errors.UserBanned(
                            timestamp() - t1, lang=request.state.lang
                        )

                if ndcId != 0:
                    row = await db.get(f"x{ndcId}", "Users").find_one({"id": uid})
                    if row and row.get("status", 0) == 9:
                        return Errors.UserBanned(
                            timestamp() - t1, lang=request.state.lang
                        )
            finally:
                db.close()

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def not_blocked(param: str = "userId"):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            t1 = timestamp()
            request: Request = kwargs["request"]
            session = request.state.session

            if not session["validsession"]:
                return Errors.InvalidSession(timestamp() - t1, lang=request.state.lang)

            target_uid = kwargs.get(param)
            uid = session["uid"]

            if target_uid and target_uid != uid:
                db = await Database().init()
                try:
                    row = await db.get(table="Users").find_one({"id": target_uid})
                    trigger_row = await db.get(table="Users").find_one({"id": uid})
                    if (
                        row
                        and uid in row.get("blockedUidList", [])
                        and not UserRole.is_global_staff(trigger_row.get("role", 0))
                    ):
                        return Errors.NotEnoughRights(
                            timestamp() - t1, lang=request.state.lang
                        )
                finally:
                    db.close()

            return await func(*args, **kwargs)

        return wrapper

    return decorator
