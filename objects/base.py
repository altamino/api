from typing import Union
from datetime import datetime, UTC
from fastapi.responses import ORJSONResponse

class Base:
    @staticmethod
    def Answer(
        data: dict = {},
        spent_time: Union[int, float] = 0.001,
        api_status_code: int = 0,
        api_message = "OK",
        html_status_code: int = 200
    ):
        return ORJSONResponse(
            {
                "api:statuscode": api_status_code,
                "api:duration": f"{round(spent_time+0.001, 4)}s",
                "api:message": api_message,
                "api:timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            } | data,
            status_code=html_status_code
        )
