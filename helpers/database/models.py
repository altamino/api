from marshmallow.fields import (
    UUID,
    Integer,
    String,
    Email,
    Dict,
    List,
    Bool,
    Float,
    Raw,
)
from marshmallow import Schema
from datetime import datetime, UTC
from json import loads
from uuid import uuid4
from time import time

from helpers import uuid_to_long

def tmstmpe1():
    return int(time())


def tmstmpe1000():
    return int(time() * 1000)


def dttmn():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ModelFabric:
    @staticmethod
    def Construct(schema, **kwargs):
        initedSchema = schema()
        loadedSchema = initedSchema.load(kwargs)
        return loads(initedSchema.dumps(loadedSchema))


class MH_Item(Schema):
    id = Integer(load_default=lambda: uuid_to_long(str(uuid4())))
    operation = Integer(required=True)
    additionalValue = Integer(required=False)
    reason = String(load_default="")
    badgeColor = String(load_default="default")
    modLevel = Integer(required=True)
    objectId = String(required=True)
    objectType = Integer(required=True)
    authorId = UUID(required=True, metadata={"as_string": True})
    timeout = Integer(load_default=None)
    createdTime = String(load_default=dttmn)


class Global:
    class Users(Schema):
        id = UUID(load_default=lambda: str(uuid4()), metadata={"as_string": True})
        role = Integer(load_default=0)
        aminoId = String(required=True)
        facebookId = String(load_default=None)
        twitterId = String(load_default=None)
        appleId = String(load_default=None)
        googleId = String(load_default=None)
        nickname = String(required=True)
        email = Email(required=True)
        passwordHash = String(required=True)
        verificationStatus = Integer(load_default=1)
        icon = String(load_default=None)
        purchasedItems = Dict(load_default={})
        communityList = List(Integer(), load_default=[])
        extensions = Dict(load_default={}, allow_none=True)
        status = Integer(load_default=0)
        coins = Float(load_default=0.00)
        lastDailyClaimDate = String(load_default=None)
        isPaidSubscriber = Bool(load_default=False)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)

    class Frames(Schema):
        frameId = UUID(load_default=lambda: str(uuid4()), metadata={"as_string": True})
        frameType = Integer(dump_default=0, required=True)
        icon = String(required=True)
        status = Integer(dump_default=0, required=True)
        resourceUrl = String(required=True)
        name = String(required=True)

    class Bubbles(Schema):
        bubbleId = UUID(load_default=lambda: str(uuid4()), metadata={"as_string": True})
        bubbleType = Integer(dump_default=0, required=True)
        icon = String(required=True)
        status = Integer(dump_default=0, required=True)
        resourceUrl = String(required=True)
        name = String(required=True)

    class VerificationCodes(Schema):
        uniqueCode = String(required=True)
        deviceId = String(required=True)
        email = String(required=True)
        captchaAnswer = String(required=True)
        timestamp = Integer(load_default=tmstmpe1)
        codeVerified = Bool(load_default=False)

    class Links(Schema):
        code = String(required=True)
        targetCode = Integer(required=True)
        objectId = UUID(required=True, metadata={"as_string": True})
        objectType = Integer(required=True)
        ndcId = Integer(load_default=0)

    class Communities(Schema):
        id = Integer(required=True)
        name = String(required=True)
        aminoId = String(required=True)
        description = String(load_default=None)
        agent = UUID(required=True, metadata={"as_string": True})
        tags = List(String(), load_default=[])
        heat = Float(load_default=0.00)
        slogan = String(load_default=None)
        rules = String(load_default=None)
        icon = String(required=True)
        theme = String(required=True)
        status = Integer(required=True)
        extensions = Dict(load_default={}, allow_none=True)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)

    # pls god pls
    # db.Devices.createIndex({ uid: 1 })
    # db.Devices.createIndex({ deviceToken: 1 }, { unique: true })
    class Devices(Schema):
        deviceToken = String(required=True)
        deviceTokenType = Integer(load_default=1)  # 1 - android (fcm)
        uid = UUID(load_default=None, allow_none=True, metadata={"as_string": True})
        deviceId = String(load_default=None, allow_none=True)
        locale = String(load_default=None, allow_none=True)
        systemPushEnabled = Bool(load_default=True)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)


class Community:
    class Chats(Schema):
        id = UUID(required=True, metadata={"as_string": True})
        chatType = Integer(load_default=2)  # 2 - public chat, 0 - private
        title = String(allow_none=True)
        description = String(load_default=None, allow_none=True)
        hostId = UUID(required=True)
        cohostsIds = List(UUID(metadata={"as_string": True}), load_default=[])
        bannedUids = List(UUID(metadata={"as_string": True}), load_default=[])
        memberList = List(UUID(metadata={"as_string": True}), required=True)
        invitedList = List(UUID(metadata={"as_string": True}), load_default=[])
        lastReadedList = Dict(load_default={})
        lastMessageId = String(load_default=None)
        icon = String(allow_none=True)
        background = String(
            load_default="https://media.altamino.top/default-chat-room-background/10_00.png"
        )
        announcement = String(load_default=None)
        pinAnnouncement = Bool(load_default=False)
        status = Integer(load_default=0)
        channelType = Integer(load_default=0)  # 0=normal, 1=voice, 2=video
        extensions = Dict(load_default={}, allow_none=True)
        tags = List(String(), load_default=[])
        canMembersInvite = Bool(load_default=True)
        isViewMode = Bool(load_default=False)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)

    class Message(Schema):
        messageId = UUID(
            load_default=lambda: str(uuid4()), metadata={"as_string": True}
        )
        authorId = UUID(required=True, metadata={"as_string": True})
        messageType = Integer(load_default=0)
        clientRefId = Integer(load_default=0)
        content = String(load_default=None, allow_none=True)
        mediaType = Integer(load_default=0)  # 0 if nothing, 100 if image
        mediaValue = String(load_default=None, allow_none=True)
        timestamp = Integer(load_default=tmstmpe1000)
        extensions = Dict(load_default={}, allow_none=True)
        createdTime = String(load_default=dttmn)

    class Users(Schema):
        id = UUID(required=True, metadata={"as_string": True})
        nickname = String(required=True)
        description = String(load_default=None)
        mediaList = List(Raw, load_default=[], allow_none=True)
        backgroundColor = String(load_default=None)
        backgroundMediaList = String(load_default=None)
        status = Integer(load_default=0)
        wall = Dict(load_default={})
        whoFollows = List(UUID(metadata={"as_string": True}), load_default=[])
        following = List(UUID(metadata={"as_string": True}), load_default=[])
        icon = String(load_default=None)
        savedBlogs = List(UUID(metadata={"as_string": True}), load_default=[])
        consecutiveDaysOfCheckIns = Integer(load_default=0)
        reputation = Integer(load_default=0)
        minutesPerDay = Integer(load_default=0)
        minutesPerWeek = Integer(load_default=0)
        role = Integer(load_default=0)
        titles = List(String(), load_default=[])
        extensions = Dict(load_default={}, allow_none=True)
        bubbleId = UUID(load_default=None, metadata={"as_string": True})
        frameId = UUID(load_default=None, metadata={"as_string": True})
        allowanceWriteToPM = Bool(load_default=True)
        allowanceWriteToWall = Bool(load_default=True)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)

    class Blogs(Schema):
        id = UUID(required=True, metadata={"as_string": True})
        authorId = UUID(required=True, metadata={"as_string": True})
        title = String(required=True)
        tags = List(String(), load_default=[])
        mediaList = List(Raw, load_default=[], allow_none=True)
        status = Integer(load_default=0)
        content = String(load_default="", allow_none=True)
        liked = List(UUID(metadata={"as_string": True}), load_default=[])
        upvote = List(UUID(metadata={"as_string": True}), load_default=[])
        downvote = List(UUID(metadata={"as_string": True}), load_default=[])
        wall = Dict(load_default={})
        blogType = Integer(required=True)
        extensions = Dict(load_default={}, allow_none=True)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)

    class WallMessage(Schema):
        authorId = UUID(required=True, metadata={"as_string": True})
        content = String(required=True)
        wmType = Integer(load_default=0)
        upvotes = List(UUID(metadata={"as_string": True}), load_default=[])
        downvotes = List(UUID(metadata={"as_string": True}), load_default=[])
        mediaList = List(Raw, load_default=[], allow_none=True)
        subWMs = List(UUID(metadata={"as_string": True}), load_default=[])
        extensions = Dict(load_default={}, allow_none=True)
        createdTime = String(load_default=dttmn)
        modifiedTime = String(load_default=dttmn)
        isSubWM = Bool(load_default=False)


class CommentSchema(Schema):
    commentId = UUID(load_default=lambda: str(uuid4()), metadata={"as_string": True})
    rootId = String(required=True)  # e.g., "blog:uuid" or "profile:uuid"
    parentId = UUID(load_default=None, allow_none=True, metadata={"as_string": True})
    authorId = UUID(required=True, metadata={"as_string": True})
    content = String(required=True)
    mediaList = List(Raw, load_default=[], allow_none=True)
    upvotes = List(UUID(metadata={"as_string": True}), load_default=[])
    downvotes = List(UUID(metadata={"as_string": True}), load_default=[])
    createdTime = String(load_default=dttmn)
    modifiedTime = String(load_default=dttmn)
