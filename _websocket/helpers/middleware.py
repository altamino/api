from typing import Union, Optional
from fastapi import WebSocket

import sys
sys.path.append('../')
from helpers.config import Config
from helpers.wsobjs import WSObjects
from helpers.processors.device import DeviceProcessor
from helpers.processors.session import SessionProcessor
from helpers.processors.signature import SignatureProcessor

async def CheckRequest(websocket: WebSocket) -> Union[Optional[bool], Optional[str], Optional[dict]]:
    admin = True
    uid = None

    admkey = websocket.headers.get("WS-ADMIN-KEY")
    admverify = websocket.headers.get("WS-ADMIN-VERIFY")
    if admkey and admverify:
        if admkey != Config.WS_ADMIN_KEY or admverify != Config.WS_ADMIN_VERIFY:
            return WSObjects.HttpError(1008, "Invalid (verify or usual) keys."), 400
        admin = True

    try:
        auid = websocket.headers['AUID']
        auth = websocket.headers['NDCAUTH']
        device = websocket.headers['NDCDEVICEID']
        signature = websocket.headers['NDC-MSG-SIG']
        body = websocket.query_params["signbody"].split("|")

        if len(body) != 2 or body[0] != device:
            raise Exception()
        
        data_time = body[1]
    except:
        return [
            None, None,
            WSObjects.HttpError(1003, "Unsupported or invalid data.")
        ]
    
    sid = await SessionProcessor.Get(auth)
    if not sid or sid['uid'] != auid:
        return [
            None, None,
            WSObjects.HttpError(1003, "Unsupported or invalid session.")
        ]
    
    did_valid = DeviceProcessor.Validate(device)
    sig_valid = SignatureProcessor.Validate(signature, f"{device}|{data_time}")
    if not did_valid or not sig_valid:
        return [
            None, None,
            WSObjects.HttpError(1003, "Unsupported or invalid device.")
        ]
    
    return [admin, uid, None]