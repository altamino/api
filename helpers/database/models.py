from marshmallow.fields import UUID, Integer, String, Email, Dict, List, Bool, Float, Raw
from marshmallow import Schema
from datetime import datetime
from json import loads
from uuid import uuid4
from time import time

def tmstmpe1(): return int(time())
def tmstmpe1000(): return int(time()*1000)
def dttmn(): return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

class ModelFabric:
    @staticmethod
    def Construct(schema, **kwargs):
        initedSchema = schema()
        loadedSchema = initedSchema.load(dict(**kwargs))
        return loads(initedSchema.dumps(loadedSchema))

class Global:
    class Users(Schema): 
        id = UUID(default=str(uuid4()), metadata={"as_string": True})
        role = Integer(default=0)
        aminoId = String(required=True)
        facebookId = String(default=None)
        twitterId = String(default=None)
        appleId = String(default=None)
        googleId = String(default=None)
        nickname = String(required=True)
        email = Email(required=True)
        passwordHash = String(required=True)
        verificationStatus = Integer(default=1)
        icon = String(default=None)
        purchasedItems = Dict(default={})
        communityList = List(Integer(), default=[])
        extensions = Dict(default={}, allow_none=True)
        status = Integer(default=0)
        coins = Float(default=0.00)
        isPaidSubscriber = Bool(default=False)
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)

    class Frames(Schema):
        frameId = UUID(default=str(uuid4()), metadata={"as_string": True})
        frameType = Integer(dump_default=0, required=True)
        icon = String(required=True)
        status = Integer(dump_default=0, required=True)
        resourceUrl = String(required=True)
        name = String(required=True)

    class Bubbles(Schema):
        bubbleId = UUID(default=str(uuid4()), metadata={"as_string": True})
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
        timestamp = Integer(default=tmstmpe1)
        codeVerified = Bool(default=False)

    class Links(Schema):
        code = String(required=True)
        targetCode = Integer(required=True)
        objectId = UUID(required=True, metadata={"as_string": True})
        objectType = Integer(required=True)
        ndcId = Integer(default=0)

    class Communities(Schema):
        id = Integer(required=True)
        name = String(required=True)
        aminoId = String(required=True)
        description = String(default=None)
        agent = UUID(required=True, metadata={"as_string": True})
        staff = List(UUID(metadata={"as_string": True}), default=[])
        tags = List(String(), default=[])
        heat = Float(default=0.00)
        slogan = String(default=None)
        rules = String(default=None)
        icon = String(required=True)
        theme = String(required=True)
        status = Integer(required=True)
        extensions = Dict(default={}, allow_none=True)
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)

class Community:
    class Chats(Schema):
        id = UUID(required=True, metadata={"as_string": True})
        chatType = Integer(default=2) # 2 - public chat, 0 - private
        title = String(allow_none=True)
        description = String(default=None, allow_none=True)
        hostId = UUID(required=True)
        cohostsIds = List(UUID(metadata={"as_string": True}), default=[])
        bannedUids = List(UUID(metadata={"as_string": True}), default=[])
        memberList = List(UUID(metadata={"as_string": True}), required=True)
        invitedList = List(UUID(metadata={"as_string": True}), default=[])
        lastReadedList = Dict(default={})
        lastMessageId = String(default=None)
        icon = String(allow_none=True)
        background = String(default="https://media.altamino.top/default-chat-room-background/10_00.png")
        announcement = String(default=None)
        pinAnnouncement = Bool(default=False)
        status = Integer(default=0)
        extensions = Dict(default={}, allow_none=True)
        tags = List(String(), default=[])
        canMembersInvite = Bool(default=True)
        isViewMode = Bool(default=False)
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)

    class Message(Schema):
        messageId = UUID(default=str(uuid4()), metadata={"as_string": True})
        authorId = UUID(required=True, metadata={"as_string": True})
        messageType = Integer(default=0)
        clientRefId = Integer(default=0)
        content = String(default=None, allow_none=True)
        mediaType = Integer(default=0) # 0 if nothing, 100 if image
        mediaValue = String(default=None, allow_none=True)
        timestamp = Integer(default=tmstmpe1000)
        extensions = Dict(default={}, allow_none=True)
        createdTime = String(default=dttmn)

    class Users(Schema): 
        id = UUID(required=True, metadata={"as_string": True})
        nickname = String(required=True)
        description = String(default=None)
        mediaList = List(Raw, default=[], allow_none=True)
        backgroundColor = String(default=None)
        backgroundMediaList = String(default=None)
        status = Integer(default=0)
        wall = Dict(default={})
        whoFollows = List(UUID(metadata={"as_string": True}), default=[])
        following = List(UUID(metadata={"as_string": True}), default=[])
        icon = String(default=None)
        savedBlogs = List(UUID(metadata={"as_string": True}), default=[])
        consecutiveDaysOfCheckIns = Integer(default=0)
        reputation = Integer(default=0)
        minutesPerDay = Integer(default=0)
        minutesPerWeek = Integer(default=0)
        role = Integer(default=0)
        titles = List(String(), default=[])
        extensions = Dict(default={}, allow_none=True)
        bubbleId = UUID(default=None, metadata={"as_string": True})
        frameId = UUID(default=None, metadata={"as_string": True})
        allowanceWriteToPM = Bool(default=True)
        allowanceWriteToWall = Bool(default=True)
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)

    class Blogs(Schema):
        id = UUID(required=True, metadata={"as_string": True})
        authorId = UUID(required=True, metadata={"as_string": True})
        title = String(required=True)
        tags = List(String(), default=[])
        mediaList = List(Raw, default=[], allow_none=True)
        status = Integer(default=0)
        content = String(required=True)
        liked = List(UUID(metadata={"as_string": True}), default=[])
        wall = Dict(default={})
        background = String(default=None)
        blogType = Integer(required=True)
        extensions = Dict(default={}, allow_none=True)
        informationTable = Dict(default={})
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)

    class WallMessage(Schema):
        authorId = UUID(required=True, metadata={"as_string": True})
        content = String(required=True)
        wmType = Integer(default=0)
        likes = List(UUID(metadata={"as_string": True}), default=[])
        mediaList = List(Raw, default=[], allow_none=True)
        subWMs = List(UUID(metadata={"as_string": True}), default=[])
        extensions = Dict(default={}, allow_none=True)
        createdTime = String(default=dttmn)
        modifiedTime = String(default=dttmn)
        isSubWM = Bool(default=False)