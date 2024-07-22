import websockets
from os import getenv
from orjson import dumps
from .config import Config

async def send_admin_ws(victims: list | str, payload: dict | str):
    if isinstance(victims, str) and victims != "ALL":
        raise Exception("Invalid victims")

    headers = {
        "WS-ADMIN-KEY": Config.WS_ADMIN_KEY,
        "WS-ADMIN-VERIFY": Config.WS_ADMIN_VERIFY
    }
    url = Config.WS_ADMIN_PROD if getenv("docker") in [1, "1"] else Config.WS_ADMIN_DEV
    async with websockets.connect(url, extra_headers=headers) as websocket:
        request = dumps({
            "ADMIN-SAYS": {
                "VICTIMS": victims,
                "WEAPON": payload
            }
        })
        await websocket.send(request.decode())
        response = await websocket.recv()
        print(response)
        return response