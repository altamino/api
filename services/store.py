from datetime import UTC, datetime, timedelta

from helpers.database.mongo import Database
from helpers.store import (
    build_avatar_frame_response,
    build_avatar_frame_icon,
    build_preview_item,
    build_chat_bubble_object,
    get_ownership_map,
    apply_ownership,
    mark_activated,
    _iso,
    TYPE_TO_GROUP,
)
from objects.types.store import RestrictType, StoreItemType, PurchaseError


class PurchaseResult:
    __slots__ = ("store_item", "error_code", "error_message")

    def __init__(self, store_item=None, error_code=None, error_message=None):
        self.store_item = store_item
        self.error_code = error_code
        self.error_message = error_message

    @property
    def ok(self) -> bool:
        return self.error_code is None


def _meta(group_id: str) -> dict | None:
    return StoreItemType.SECTION_META.get(group_id)


def _id_field(object_type: int) -> str | None:
    return StoreItemType.TYPE_INFO.get(object_type, (None, None))[1]


def _catalog_query(group_id: str) -> dict:
    if group_id != "sticker":
        return {}
    # Native types: 1 = normal store pack, 2 = personal, 3 = user/community-created.
    return {
        "collectionType": 1,
        "status": 0,
        "ndcId": {"$in": [0, None]},
        "isShared": {"$ne": True},
        "collectionId": {"$nin": ["mood"], "$not": {"$regex": "^personal-"}},
    }


class StoreService:
    def __init__(self, db: Database, uid: str, ndcId: int = 0):
        self.db = db
        self.uid = uid
        self.ndcId = ndcId
        self._worn: dict | None = None

    @classmethod
    async def create(cls, uid: str, ndcId: int = 0) -> "StoreService":
        db = await Database().init()
        return cls(db, uid, ndcId)

    def close(self):
        self.db.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.close()

    def _collection(self, name: str):
        return self.db.get(table=name)

    def _users_table(self):
        return (
            self.db.get(f"x{self.ndcId}", "Users")
            if self.ndcId
            else self._collection("Users")
        )

    async def _worn_ids(self) -> dict:
        if self._worn is None:
            user = (
                await self._users_table().find_one(
                    {"id": self.uid},
                    {"bubbleId": 1, "frameId": 1},
                )
                or {}
            )
            self._worn = {
                "bubbleId": user.get("bubbleId"),
                "frameId": user.get("frameId"),
            }
        return self._worn

    async def _active_id_for(self, id_field: str | None) -> str | None:
        if id_field not in ("bubbleId", "frameId"):
            return None
        return (await self._worn_ids()).get(id_field)

    async def _owned_map_by_object(self, object_type: int, ids: list[str]) -> dict:
        return await get_ownership_map(self.db, self.uid, object_type, ids)

    def _decorate(
        self,
        docs: list[dict],
        id_field: str | None,
        own_map: dict,
        active_id: str | None = None,
    ) -> list[dict]:
        out = []
        for d in docs:
            if id_field:
                d = apply_ownership(d, id_field, own_map)
                d = mark_activated(d, id_field, active_id)
            out.append(d)
        return out

    async def _fetch_with_ownership(
        self, group_id: str, query: dict, skip: int = 0, limit: int | None = None
    ) -> list[dict]:
        meta = _meta(group_id)
        if not meta:
            return []
        col = self._collection(meta["collection"])
        catalog = _catalog_query(group_id)
        if catalog:
            query = {"$and": [catalog, query]}
        cursor = col.find(query, {"_id": 0})
        if skip:
            cursor = cursor.skip(skip)
        if limit is not None:
            cursor = cursor.limit(limit)
        docs = await cursor.to_list(length=limit)

        object_type = meta["objectType"]
        id_field = _id_field(object_type)
        own_map = {}
        active_id = None
        if id_field:
            ids = [d.get(id_field) for d in docs if d.get(id_field)]
            own_map = await self._owned_map_by_object(object_type, ids)
            active_id = await self._active_id_for(id_field)
        return self._decorate(docs, id_field, own_map, active_id)

    def _build_items(self, group_id: str, docs: list[dict]) -> list[dict]:
        items = []
        for d in docs:
            item = build_preview_item(group_id, d, ndcId=self.ndcId)
            if item:
                items.append(item)
        return items

    async def list_items(
        self, group_id: str, start: int = 0, size: int = 25
    ) -> list[dict]:
        docs = await self._fetch_with_ownership(group_id, {}, skip=start, limit=size)
        return self._build_items(group_id, docs)

    async def recommend_items(
        self, group_id: str, object_id: str | None, size: int = 25
    ) -> list[dict]:
        meta = _meta(group_id)
        if not meta:
            return []
        id_field = _id_field(meta["objectType"])
        query = {id_field: {"$ne": object_id}} if (id_field and object_id) else {}
        docs = await self._fetch_with_ownership(group_id, query, limit=size)
        return self._build_items(group_id, docs)

    async def sections(self, group_ids: list[str]) -> list[dict]:
        section_list = []
        for group_id in group_ids:
            meta = _meta(group_id)
            if not meta:
                continue
            docs = await self._fetch_with_ownership(group_id, {}, limit=6)
            total = await self._collection(meta["collection"]).count_documents(
                _catalog_query(group_id)
            )
            if group_id == "sticker" and total == 0:
                continue  # APK inserts a local emoji card into any returned sticker section.
            section_list.append(
                {
                    "name": meta["name"],
                    "sectionGroupId": group_id,
                    "storeSectionId": group_id,
                    "allItemsCount": total,
                    "previewStoreItemList": self._build_items(group_id, docs),
                }
            )
        return section_list

    async def get_avatar_frame(self, frame_id: str) -> dict | None:
        frame = await self._collection("AvatarFrames").find_one(
            {"frameId": frame_id}, {"_id": 0}
        )
        if frame is None:
            return None
        own_map = await self._owned_map_by_object(StoreItemType.AvatarFrame, [frame_id])
        frame = apply_ownership(frame, "frameId", own_map)
        frame = mark_activated(frame, "frameId", await self._active_id_for("frameId"))
        return build_avatar_frame_response(
            frame, price=frame.get("price", 0), ndcId=self.ndcId
        )

    async def get_chat_bubble(self, bubble_id: str) -> dict | None:
        bubble = await self._collection("ChatBubbles").find_one(
            {"bubbleId": bubble_id}, {"_id": 0}
        )
        if bubble is None:
            return None
        own_map = await self._owned_map_by_object(StoreItemType.ChatBubble, [bubble_id])
        bubble = apply_ownership(bubble, "bubbleId", own_map)

        worn_bubble = await self._active_id_for("bubbleId")
        bubble = mark_activated(bubble, "bubbleId", worn_bubble)

        return {
            "chatBubble": build_chat_bubble_object(bubble, ndcId=self.ndcId),
            "allChatsBubbleId": worn_bubble,
        }

    async def _owned_docs(self, object_type: int) -> tuple[dict, list[str]]:
        cursor = self._collection("UserStoreItems").find(
            {"uid": self.uid, "objectType": object_type},
            {"_id": 0},
        )
        own_docs = await cursor.to_list(length=None)
        own_map = {d["objectId"]: d for d in own_docs}
        return own_map, list(own_map.keys())

    async def list_my_avatar_frames(self, start: int = 0, size: int = 20) -> list[dict]:
        own_map, owned_ids = await self._owned_docs(StoreItemType.AvatarFrame)
        docs = (
            await self._collection("AvatarFrames")
            .find(
                {"frameId": {"$in": owned_ids}},
                {"_id": 0},
            )
            .skip(start)
            .limit(size)
            .to_list(length=size)
        )
        active_id = await self._active_id_for("frameId")
        result = []
        for d in docs:
            d = apply_ownership(d, "frameId", own_map)
            d = mark_activated(d, "frameId", active_id)
            result.append(
                build_avatar_frame_response(
                    d, price=d.get("price", 0), ndcId=self.ndcId
                )["avatarFrame"]
            )
        return result

    async def list_my_bubbles(
        self, chat_id: str | None = None, start: int = 0, size: int = 20
    ) -> dict:
        own_map, owned_ids = await self._owned_docs(StoreItemType.ChatBubble)
        docs = (
            await self._collection("ChatBubbles")
            .find(
                {"bubbleId": {"$in": owned_ids}},
                {"_id": 0},
            )
            .skip(start)
            .limit(size)
            .to_list(length=size)
        )

        user_table = (
            self.db.get(f"x{self.ndcId}", "Users")
            if self.ndcId
            else self._collection("Users")
        )
        user = await user_table.find_one({"id": self.uid}) or {}
        default_bubble_id = user.get("bubbleId")
        per_chat = (user.get("chatBubbles") or {}).get(chat_id) if chat_id else None
        current_selected = per_chat or default_bubble_id

        chat_bubble_list = []
        for d in docs:
            d = apply_ownership(d, "bubbleId", own_map)
            d = mark_activated(d, "bubbleId", current_selected)
            chat_bubble_list.append(build_chat_bubble_object(d, ndcId=self.ndcId))

        return {
            "chatBubbleList": chat_bubble_list,
            "allChatsBubbleId": default_bubble_id,
            "currentSelectedBubbleId": current_selected,
        }

    async def _user_ndc_ids(self) -> list[int]:
        """ndcId всех сообществ, где состоит юзер."""
        cursor = self._collection("CommunityMembers").find(
            {"uid": self.uid},
            {"_id": 0, "ndcId": 1},
        )
        docs = await cursor.to_list(length=None)
        return [d["ndcId"] for d in docs if d.get("ndcId")]

    async def apply_avatar_frame(self, frame_id: str, apply_to_all: bool) -> bool:
        if frame_id:
            owned = await self._collection("UserStoreItems").find_one(
                {
                    "uid": self.uid,
                    "objectType": StoreItemType.AvatarFrame,
                    "objectId": frame_id,
                }
            )
            if owned is None:
                return False

        value = frame_id or None
        if not apply_to_all:
            target = (
                self.db.get(f"x{self.ndcId}", "Users")
                if self.ndcId
                else self._collection("Users")
            )
            await target.update_one({"id": self.uid}, {"$set": {"frameId": value}})
            return True

        for ndc in await self._user_ndc_ids():
            await self.db.get(f"x{ndc}", "Users").update_one(
                {"id": self.uid},
                {"$set": {"frameId": value}},
            )
        await self._collection("Users").update_one(
            {"id": self.uid},
            {"$set": {"frameId": value}},
        )
        return True

    async def frame_icon(self, frame_id: str | None) -> dict | None:

        if not frame_id:
            return None
        frame = await self._collection("AvatarFrames").find_one(
            {"frameId": frame_id}, {"_id": 0}
        )
        if frame is None:
            return None
        own_map = await self._owned_map_by_object(StoreItemType.AvatarFrame, [frame_id])
        frame = apply_ownership(frame, "frameId", own_map)
        return build_avatar_frame_icon(frame)

    async def attach_frame_icon(self, row: dict) -> dict:
        row["iconFrame"] = await self.frame_icon(row.get("frameId"))
        return row

    async def attach_frame_icons(self, rows: list[dict]) -> list[dict]:
        frame_ids = [fid for r in rows if (fid := r.get("frameId"))]
        if not frame_ids:
            for r in rows:
                r["iconFrame"] = None
            return rows

        cursor = self._collection("AvatarFrames").find(
            {"frameId": {"$in": list(set(frame_ids))}},
            {"_id": 0},
        )
        frames = {f["frameId"]: f for f in await cursor.to_list(length=None)}

        own_map = await self._owned_map_by_object(
            StoreItemType.AvatarFrame, list(frames)
        )

        for r in rows:
            fid = r.get("frameId")
            frame = frames.get(fid) if fid else None
            if frame is not None:
                frame = apply_ownership(frame, "frameId", own_map)
            r["iconFrame"] = build_avatar_frame_icon(frame) if frame else None
        return rows

    async def _owns(self, object_type: int, object_id: str) -> bool:
        doc = await self._collection("UserStoreItems").find_one(
            {"uid": self.uid, "objectType": object_type, "objectId": object_id},
            {"_id": 1},
        )
        return doc is not None

    async def apply_avatar_frame(
        self, frame_id: str | None, apply_to_all: bool
    ) -> bool:
        if frame_id is not None and not await self._owns(
            StoreItemType.AvatarFrame, frame_id
        ):
            return False

        update = {"$set": {"frameId": frame_id}}

        if not apply_to_all:
            table = (
                self.db.get(f"x{self.ndcId}", "Users")
                if isinstance(self.ndcId, int)
                else self._collection("Users")
            )
            await table.update_one({"id": self.uid}, update)
            return True

        global_users = self._collection("Users")
        profile = (
            await global_users.find_one({"id": self.uid}, {"communityList": 1}) or {}
        )
        community_ids = profile.get("communityList") or []

        await global_users.update_one({"id": self.uid}, update)

        for cid in community_ids:
            table = self.db.get(f"x{cid}", "Users")
            await table.update_one({"id": self.uid}, update)

        return True

    async def purchase(self, object_id: str, object_type: int) -> PurchaseResult:
        if object_type not in StoreItemType.TYPE_INFO:
            return PurchaseResult(error_code="invalid")

        collection, id_field = StoreItemType.TYPE_INFO[object_type]
        item = await self._collection(collection).find_one({id_field: object_id})
        if item is None:
            return PurchaseResult(error_code="invalid")

        owned = self._collection("UserStoreItems")
        existing = await owned.find_one(
            {
                "uid": self.uid,
                "objectType": object_type,
                "objectId": object_id,
            }
        )

        group_id = TYPE_TO_GROUP.get(object_type, "avatar-frame")

        if existing:
            store_item = self._finalize_item(
                item,
                group_id,
                existing.get("ownershipInfo"),
                existing.get("isActivated", False),
            )
            return PurchaseResult(store_item=store_item)

        if object_type == StoreItemType.StickerCollection:
            catalog_item = await self._collection("StickerCollections").find_one(
                {"$and": [_catalog_query("sticker"), {"collectionId": object_id}]},
                {"_id": 1},
            )
            if catalog_item is None:
                return PurchaseResult(error_code="invalid")

        restrict_type = item.get("restrictType")
        price = item.get("price", 0)
        if restrict_type is None:
            restrict_type = RestrictType.COIN if price else RestrictType.FREE
        if restrict_type == RestrictType.NONE:
            return PurchaseResult(error_code="invalid")

        if restrict_type == RestrictType.AMINO_MEMBERSHIP:
            u = await self._collection("Users").find_one(
                {"id": self.uid}, {"isPaidSubscriber": 1}
            )
            if not u or not u.get("isPaidSubscriber"):
                return PurchaseResult(
                    error_code=PurchaseError.MEMBERSHIP_NOT_SATISFIED,
                    error_message="Membership required",
                )

        if restrict_type == RestrictType.COIN and price > 0:
            result = await self._collection("Users").update_one(
                {"id": self.uid, "coins": {"$gte": price}},
                {"$inc": {"coins": -price}},
            )
            if result.modified_count == 0:
                return PurchaseResult(
                    error_code=PurchaseError.NOT_ENOUGH_COINS,
                    error_message="Not enough coins",
                )
            from helpers import coin_ledger

            await coin_ledger.record(
                self.db,
                self.uid,
                -price,
                "store_purchase",
                getattr(self, "ndcId", 0),
                objectId=object_id,
                title=item.get("name") or item.get("title"),
            )

        duration = item.get("availableDuration", 0)
        expired = None
        if duration:
            expired = (datetime.now(UTC) + timedelta(seconds=duration)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        ownership_info = {
            "createdTime": _iso(),
            "expiredTime": expired,
            "isAutoRenew": False,
            "ownershipStatus": 1,
        }
        await owned.insert_one(
            {
                "uid": self.uid,
                "objectId": object_id,
                "objectType": object_type,
                "isActivated": False,
                "ownershipInfo": ownership_info,
                "createdTime": _iso(),
            }
        )

        store_item = self._finalize_item(item, group_id, ownership_info, False)
        return PurchaseResult(store_item=store_item)

    def _finalize_item(
        self, item: dict, group_id: str, ownership_info, is_activated: bool
    ) -> dict:
        item = {**item}
        item.pop("_id", None)
        item["ownershipInfo"] = ownership_info
        item["isActivated"] = is_activated
        item["isNew"] = False
        return build_preview_item(group_id, item, ndcId=self.ndcId)
