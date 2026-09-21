from asyncio import Semaphore, gather, to_thread
from json import load

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from httpx import AsyncClient

from helpers.config import Config
from helpers.database.models import Global, ModelFabric
from helpers.database.mongo import Database
from helpers.processors.cache import CacheProcessor


def load_service_account():
    if not Config.ENABLE_PUSH or not Config.FCM_SERVICE_ACCOUNT:
        return None

    try:
        path = Config.FCM_SERVICE_ACCOUNT.strip()
        with open(path, encoding="utf-8") as file:
            return load(file)
    except Exception as e:
        print("FCM json fail:", e)
        return None


ACCOUNT = load_service_account()
AUTH_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


class PushProcessor:
    _limit = Semaphore(16)

    TOKEN_LIFETIME = 60 * 55
    SEND_URL = "https://fcm.googleapis.com/v1/projects/{}/messages:send"

    @staticmethod
    async def Register(uid: str | None, data: dict) -> None:
        if not data.get("deviceToken"):
            return

        document = ModelFabric.Construct(
            Global.Devices,
            deviceToken=data["deviceToken"],
            deviceTokenType=data.get("deviceTokenType", 1),
            uid=uid,
            deviceId=data.get("deviceID"),
            locale=data.get("locale"),
            systemPushEnabled=data.get("systemPushEnabled", True),
        )

        db = await Database().init()
        await db.get(table="Devices").update_one(
            {"deviceToken": document["deviceToken"]},
            {
                "$set": document,
                "$setOnInsert": {"createdTime": document.pop("createdTime")},
            },
            upsert=True,
        )
        db.close()

    @staticmethod
    async def Token() -> str | None:
        cached = await CacheProcessor.Get("accessToken", prefix="fcm:")
        if cached:
            return cached

        try:
            credentials = Credentials.from_service_account_info(
                ACCOUNT, scopes=AUTH_SCOPES
            )
            await to_thread(credentials.refresh, GoogleRequest())
            token = credentials.token
        except Exception as e:
            print("FCM auth fail:", e)
            return None

        if not token:
            print("FCM empty token")
            return None

        await CacheProcessor.Make(
            "accessToken",
            token,
            prefix="fcm:",
            expiring_after=PushProcessor.TOKEN_LIFETIME,
        )

        return token

    @staticmethod
    async def Send(
        client: AsyncClient, accessToken: str, deviceToken: str, message: dict
    ) -> bool:
        try:
            async with PushProcessor._limit:
                response = await client.post(
                    PushProcessor.SEND_URL.format(ACCOUNT["project_id"]),
                    headers={"Authorization": f"Bearer {accessToken}"},
                    json={"message": {"token": deviceToken, **message}},
                )

            if response.status_code == 200:
                return True

            error = response.json().get("error", {})
        except Exception as e:
            print("FCM send fail:", e)
            return False

        if any(
            details.get("errorCode") == "UNREGISTERED"
            for details in error.get("details", [])
        ):
            db = await Database().init()
            await db.get(table="Devices").delete_one({"deviceToken": deviceToken})
            db.close()
        else:
            print("FCM reject msg:", error)

        return False

    @staticmethod
    async def SendToUsers(uids: list, message: dict) -> int:
        if ACCOUNT is None:
            return 0

        db = await Database().init()
        devices = (
            await db.get(table="Devices")
            .find({"uid": {"$in": uids}, "systemPushEnabled": True}, {"deviceToken": 1})
            .to_list(length=None)
        )
        db.close()

        accessToken = await PushProcessor.Token() if devices else None
        if accessToken is None:
            return 0

        async with AsyncClient(timeout=10) as client:
            results = await gather(
                *[
                    PushProcessor.Send(
                        client, accessToken, device["deviceToken"], message
                    )
                    for device in devices
                ],
                return_exceptions=True,
            )

        return sum(result is True for result in results)
