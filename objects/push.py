from json import dumps


class Push:
    CHAT_MESSAGE = 18

    @staticmethod
    def Payload(notifType: int, pushId: str, title: str, body: str, **fields) -> dict:
        payload = {
            "notifType": notifType,
            "id": pushId,  # pushId uses for dedup
            "aps": {
                "alert": {"title": title[:64], "body": body[:200]},
                "sound": "default",
            },
            **fields,
        }

        return {
            "data": {
                "payload": dumps(
                    {k: v for k, v in payload.items() if v is not None},
                    ensure_ascii=False,
                )
            },
            "android": {"priority": "high"},
        }

    @staticmethod
    def ChatMessage(chat: dict, message: dict, author: dict, ndcId: int = 0) -> dict:
        nickname = author.get("nickname") or ""
        content = message.get("content") or "[Attachment]"
        title = chat.get("title")

        return Push.Payload(
            Push.CHAT_MESSAGE,
            message["messageId"],
            title or nickname,
            f"{nickname}: {content}" if title else content,
            ndcId=ndcId,
            tid=chat["id"],
            ttype=chat.get("chatType", 0),
            uid=author.get("uid"),
            nickname=nickname,
            picUrl=author.get("icon"),
            picType=1,
        )
