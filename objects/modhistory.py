from helpers.i18n import i18n
from helpers import uuid_to_long

def _get_right_op_name(data: dict, lang: str):
    op = data["operation"]
    if op == 110:
        op = int(f"{op}{data.get('objectType', 0)}{data.get('additionalValue', 0)}")

    mapmen = {
        11019: "mod.op.hide.blog.action",
        11010: "mod.op.unhide.blog.action",
        110129: "mod.op.hide.chat.action",
        110120: "mod.op.unhide.chat.action",
        11009: "mod.op.ban.action",
        11000: "mod.op.unban.action",
        18: "mod.op.hide.profile.action",
        19: "mod.op.unhide.profile.action",
        205: "mod.op.strike.action",
        267: "mod.op.warn.action",
        207: "mod.op.titles-change.action",
        102: "mod.op.msg-delete.action",
        114: "mod.op.feature.action",
        116: "mod.op.unfeature.action",
    }
    key = mapmen.get(op, f"mod.op.{op}.action")
    return i18n.get(key, lang)



class ModHistory:
    @staticmethod
    def Item(
        ndcId: int,
        data: dict,
        punisher: dict,
        punished: dict | None = None,
        lang: str = "en",
    ):
        operation_name = _get_right_op_name(data, lang)

        return {
            "logId": uuid_to_long(data["id"]),
            "operation": data["operation"],
            "operationName": operation_name,
            "operationDetail": data.get("reason"),
            "operationLevel": data.get("badgeColor"),
            "moderationLevel": data.get("modLevel", 1),
            "objectId": data["objectId"],
            "objectType": data["objectType"],
            "objectUrl": data.get("objectUrl"),
            "ndcId": ndcId,
            "author": punisher,
            "refObject": punished,
            "extData": {
                "message": data.get("reason"),
                "penaltyValue": data.get("timeout"),
            },
            "createdTime": data["createdTime"],
        }
