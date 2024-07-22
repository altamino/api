from datetime import datetime, UTC
from orjson import dumps

class WSObjects:
    def HttpError(ws_message: str, ws_statuscode: int) -> bytes:
        return dumps({
            # ws info
            "ws:statuscode": ws_statuscode,
            "ws:message": ws_message,

            # api info
            "api:statuscode": 104,
            "api:duration": "0.001s",
            "api:message": "Invalid request. Check all data that you sended or try again later.",
            "api:timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        })
    
    def WSError(
            exception_code: int, exception_message: str,
            ws_req_id: str | int | None = 0, ndcId: int | None = 0
        ) -> dict:
        ws_req_id = ws_req_id or 0
        ndcId = ndcId or 0
        return {
            "t": 113,
            "o": {
                "id": ws_req_id,
                "ndcId": ndcId,
                "exception": {
                    "id": ws_req_id,
                    "code": exception_code,
                    "message": exception_message
                }
            }
        }

        {"t":113,"o":{"id":"123","ndcId":0,"exception":{"id":"123","code":2,"message":"Bad Request Format"}}}
        return {"t":113,"o":{"ndcId":0,"exception":{"code":2,"message":"Bad Request Format"}}}
    
    def Pong(ws_req_id: str) -> dict:
        return {
            "t": 117,
            "o": {
                "id": ws_req_id,
                "threadChannelUserInfoList": []
            }
        }