"""Native Notice contract. Storage remains unchanged; never fabricate an actor."""

from datetime import datetime, timezone


def native_time(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value / 1000, timezone.utc)
        elif isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            return None
        return (
            value.replace(tzinfo=value.tzinfo or timezone.utc)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    except (ValueError, OverflowError, OSError):
        return None


def notification_dto(doc, ndc_id, operator):
    if operator:
        operator = dict(operator)
        for field in ("createdTime", "modifiedTime"):
            operator[field] = native_time(operator.get(field))
    keys = (
        "type",
        "parentType",
        "parentId",
        "parentText",
        "parentSubtype",
        "objectId",
        "objectType",
        "objectSubtype",
        "objectText",
        "contextText",
        "contextValue",
        "contextNdcId",
    )
    result = {key: doc.get(key) for key in keys}
    # NoticeListFragment uses contextNdcId for profile navigation. A missing
    # value becomes zero in Java and incorrectly opens the global profile.
    result["contextNdcId"] = (
        ndc_id
        if ndc_id or doc.get("type") in (1, 2)
        else (doc.get("contextNdcId") or 0)
    )
    if operator:
        operator["ndcId"] = ndc_id
        operator["isGlobal"] = ndc_id == 0
    result.update(
        notificationId=doc.get("id"),
        ndcId=ndc_id,
        createdTime=native_time(doc.get("createdTime")),
        operator=operator,
        author=operator,
    )
    return result
