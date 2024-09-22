from typing import Union
from ..config import Config

from .models import *
import motor.motor_asyncio


class Database:
    async def init(self) -> motor.motor_asyncio.AsyncIOMotorClient:
        self.__connection = motor.motor_asyncio.AsyncIOMotorClient(
            Config.MONGODB_CONNECTION_STRING, uuidRepresentation="pythonLegacy"
        )
        return self

    async def get(
        self, database: str = Config.MONGODB_MAIN_DB, table: Union[None, str] = None
    ):
        return (
            self.__connection[database]
            if table == None
            else self.__connection[database][table]
        )

    async def close(self):
        return self.__connection.close()

    async def get_connection(self):
        return self.__connection
