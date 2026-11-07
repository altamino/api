import re
from asyncio import to_thread as asyncio_thread
from base64 import b64decode, b64encode
from json import dumps
from math import ceil
from time import time as timestamp
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from helpers.aquarium import Aether, Blake, Ferret
from helpers.config import Config
from helpers.database.models import Community, Global, ModelFabric
from helpers.database.mongo import Database
from helpers.functions import get_ip
from helpers.generator import Generator
from helpers.imageTools import ImageTools
from helpers.processors.cache import CacheProcessor
from helpers.processors.device import DeviceProcessor
from helpers.processors.email import EmailProcessor
from helpers.processors.push import PushProcessor
from helpers.processors.session import SessionProcessor
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors, User
from pyotp import TOTP

logregin = APIRouter()
logregin.route_class = CachableRoute


@logregin.get("/verification-code/{code}")
async def seeVerificationCode(code):
    db = await Database().init()
    table = db.get(table="VerificationCodes")
    row = await table.find_one({"uniqueCode": code})
    db.close()
    if row is None:
        return Errors.InvalidVerificationCode()
    img, _, __ = ImageTools.generate_captcha(row["captchaAnswer"])
    return StreamingResponse(img)


@logregin.post("/g/s/auth/verify-password")
async def verifyPassword(request: Request):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    try:
        data = await request.json()
        secret = Blake(
            data=data["secret"],
            key=Config.PASSWORD_SALT,
            digest_size=64,
        ).hash
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()

    table = db.get(table="Users")
    row = await table.find_one({"id": uid, "passwordHash": secret})
    if row is None:
        return Errors.InvalidLogin(timestamp() - t1, lang=request.state.lang)

    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )


@logregin.post("/g/s/auth/change-password")
async def changePassword(request: Request):
    t1 = timestamp()
    uid = request.state.session.get("uid")
    try:
        data = await request.json()
        oldSecret = Blake(
            data=data["secret"],
            key=Config.PASSWORD_SALT,
            digest_size=64,
        ).hash
        validationContext = data["validationContext"]
        updateSecret = Blake(
            data=data["updateSecret"],
            key=Config.PASSWORD_SALT,
            digest_size=64,
        ).hash
        code = validationContext["data"]["code"]
        email = validationContext["identity"]
        deviceId = data["deviceID"]
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    
    db = await Database().init()
    codes = db.get(table="VerificationCodes")
    codes_row = await codes.find_one_and_update(
        {"deviceId": deviceId, "email": email, "used": {"$ne": True}},
        {"$set": {"used": True}}
    )
    if codes_row is None:
        db.close()
        return Errors.UnverifiedEmail(timestamp() - t1, lang=request.state.lang)

    if str(code) != str(codes_row["captchaAnswer"]) and not codes_row.get("codeVerified"):
        db.close()
        return Errors.InvalidVerificationCode(
            timestamp() - t1, lang=request.state.lang
        )
    await codes.delete_one({"deviceId": deviceId, "email": email})

    table = db.get(table="Users")
    row = await table.find_one({"email": email, "passwordHash": oldSecret})
    if row is None:
        db.close()
        return Errors.UserUnavailable(timestamp() - t1, lang=request.state.lang)
    
    if row.get("id") != uid:
        db.close()
        return Errors.SUS(timestamp() - t1, lang=request.state.lang)

    table.update_one({"email": email}, {"$set": {"passwordHash": updateSecret}})
    db.close()
    return Base.Answer(
        {},
        spent_time=timestamp() - t1,
    )


"""
    if resetPassword is True:
        data["level"] = 2
        data["purpose"] = "reset-password"
"""


@logregin.post("/g/s/auth/request-security-validation")
async def requestCode(request: Request):
    t1 = timestamp()
    try:
        data = await request.json()
        reciever = data["identity"]
        if (
            (not DeviceProcessor.Validate(data["deviceID"]))
            or (data["deviceID"] != request.headers["NDCDEVICEID"])
            or (data["type"] != 1)
        ):
            raise Exception()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    if not await EmailProcessor.Validate(reciever):
        return Errors.InvalidEmail(timestamp() - t1, lang=request.state.lang)

    inspector = Aether.encode("email:" + reciever).decode()
    turtle = await CacheProcessor.Get(inspector, prefix="turtlelimiter:")
    if turtle is None:
        await CacheProcessor.Make(
            inspector, "X", prefix="turtlelimiter:", expiring_after=60
        )
        turtle = "X"

    if turtle == "X":
        return Errors.VerificationRequired(
            Config.API_BASE_URL + "/api/v1/turtle/hello/email?inspector=" + inspector,
            timestamp() - t1,
            lang=request.state.lang,
        )

    if not Config.ENABLE_EMAIL:
        return Base.Answer(
            {
                "api:warning": "Emails are disabled. Maybe it's a development environment (if not, this warning should matter server owners'!). Enter any code to continue."
            },
            spent_time=timestamp() - t1,
        )

    db = await Database().init()
    table = db.get(table="VerificationCodes")
    code_req = {"$or": [{"deviceId": data["deviceID"]}, {"email": reciever}]}
    row = await table.find_one(code_req)
    uniqueCode, captchaAnswer = None, None
    if row is not None:
        if ceil(timestamp()) - row["timestamp"] <= 60:
            return Errors.WaitMinuteForAnotherCode(
                timestamp() - t1, lang=request.state.lang
            )
        else:
            await table.update_many(code_req, {"$set": {"timestamp": int(timestamp())}})
            uniqueCode = row["uniqueCode"]
            captchaAnswer = row["captchaAnswer"]

    if not uniqueCode:
        uniqueCode = Blake(
            data=data["deviceID"],
            key=Config.PASSWORD_SALT,
            salt=str(ceil(timestamp())),
            digest_size=32,
        ).hash

    c_img, c_answer, _ = ImageTools.generate_captcha(captchaAnswer)

    await table.insert_one(
        ModelFabric.Construct(
            Global.VerificationCodes,
            uniqueCode=uniqueCode,
            deviceId=data["deviceID"],
            captchaAnswer=c_answer,
            email=reciever,
        )
    )
    db.close()

    html = """<h3>You have requested a confirmation code for AltAmino. Please enter this code.</h3>{{ IMAGE }}<p>Can't see the code? Please click on the link below to see the code.</p>[LINK]<br><p>If this is not your AltAmino account, don't worry. Someone may have misspelled their email address.</p><p>If you have any difficulties or questions, please contact us.</p><br><p>Thanks,<br>Team AltAmino</p>"""
    text = "You have requested a confirmation code for AltAmino. Please visit the link to see the code: [LINK]"
    verification_link = f"{Config.API_BASE_URL}/verify?code={uniqueCode}"
    html = html.replace("[LINK]", verification_link)
    text = text.replace("[LINK]", verification_link)
    subject = "Confirmation code for AltAmino"

    try:
        await asyncio_thread(
            EmailProcessor.SendEmail,
            receiver=reciever,
            subject=subject,
            html=html,
            text=text,
            body_images={"IMAGE": c_img},
        )
    except Exception as e:
        print(e)
        return Errors.MailError(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(spent_time=timestamp() - t1)


"""
    "secret": f"0 {password}",
    "deviceID": deviceId,
    "email": email,
    "clientType": 100,
    "nickname": nickname,
    "clientCallbackURL": "narviiapp://relogin",
    "validationContext": {
        "data": {
            "code": verificationCode
        },
        "type": 1,
        "identity": email
    },
    "type": 1,
    "identity": email,
    "timestamp": int(timestamp() * 1000)
"""


@logregin.post("/g/s/auth/check-security-validation")
async def check_code(request: Request):
    data = await request.json()
    t1 = timestamp()

    try:
        if (
            (not DeviceProcessor.Validate(data["deviceID"]))
            or (data["deviceID"] != request.headers["NDCDEVICEID"])
            or (
                not await EmailProcessor.Validate(data["validationContext"]["identity"])
            )
            or (
                data["validationContext"]["type"] != 1
                or len(data["validationContext"]["data"]["code"]) != 6
            )
        ):
            raise Exception()
    except Exception:
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    email = data["validationContext"]["identity"]

    if not Config.ENABLE_EMAIL:
        return Base.Answer(
            {
                "api:warning": "Emails are disabled. Maybe it's a development environment (if not, this warning should matter server owners'!)."
            },
            spent_time=timestamp() - t1,
        )

    db = await Database().init()
    table = db.get(table="VerificationCodes")
    row = await table.find_one({"deviceId": data["deviceID"], "email": email})
    if row is None:
        return Errors.UnverifiedEmail(timestamp() - t1, lang=request.state.lang)
    if str(data["validationContext"]["data"]["code"]) != str(row["captchaAnswer"]):
        return Errors.InvalidVerificationCode(timestamp() - t1, lang=request.state.lang)

    print(
        await table.update_many(
            {"deviceId": data["deviceID"], "email": email},
            {"$set": {"codeVerified": True}},
        )
    )

    db.close()
    return Base.Answer(spent_time=timestamp() - t1)


@logregin.post("/g/s/auth/otp/confirm")
async def confirmOtp(request: Request):
    data = await request.json()
    uid, code, otp_type = data.get("uid"), data.get("code"), data.get("type")
    if uid is None or code is None or otp_type is None:
        return Errors.InvalidRequest(lang=request.state.lang)

    if otp_type == 1:
        db = await Database().init()
        table = db.get(table="Users")
        row = await table.find_one({"id": uid}, {"otpSecret": 1})
        db.close()

        if row is None or row.get("otpSecret") is None:
            return Errors.DataNotExist(lang=request.state.lang)

        # creating one:
        # pyotp.random_base32()
        totp = TOTP(row["otpSecret"])
        if not totp.verify(str(code)):
            return Errors.InvalidVerificationCode(lang=request.state.lang)

        # logic to let log in

        return Base.Answer()
    elif otp_type == 2:
        # email 2fa
        return Errors.PathNotImplemented(lang=request.state.lang)


@logregin.post("/g/s/auth/register")
async def register(request: Request):
    data = await request.json()
    t1 = timestamp()

    try:
        email = data.get("email") or data.get("identity")
        if (
            (not DeviceProcessor.Validate(data["deviceID"]))
            or (data["deviceID"] != request.headers["NDCDEVICEID"])
            or (not await EmailProcessor.Validate(email))
            or (data["secret"][:2] != "0 " or data["nickname"].strip() in [None, ""])
        ):
            raise Exception()

        if data.get("validationContext"):
            if (
                email != data["validationContext"]["identity"]
                or data["validationContext"]["type"] != 1
            ):
                raise Exception()
    except Exception as e:
        print(e)
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    db = await Database().init()

    if Config.ENABLE_EMAIL:
        codes = db.get(table="VerificationCodes")
        codes_row = await codes.find_one_and_update(
            {"deviceId": data["deviceID"], "email": email, "used": {"$ne": True}},
            {"$set": {"used": True}}
        )
        if codes_row is None:
            print("No codes or already used")
            db.close()
            return Errors.UnverifiedEmail(timestamp() - t1, lang=request.state.lang)
        if data.get("validationContext"):
            if str(data["validationContext"]["data"]["code"]) != str(
                codes_row["captchaAnswer"]
            ) and not codes_row.get("codeVerified"):
                print("Invalid code (somehow)")
                db.close()
                return Errors.InvalidVerificationCode(
                    timestamp() - t1, lang=request.state.lang
                )
            else:
                codes_row["codeVerified"] = True

        if not codes_row.get("codeVerified"):
            print("Code not verified")
            db.close()
            return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    users = db.get(table="Users")
    row = await users.find_one({"email": email})
    if row is not None:
        db.close()
        return Errors.EmailWasTaken(timestamp() - t1, lang=request.state.lang)

    uid = str(uuid4())

    passwordHash = Blake(
        data=data["secret"],
        key=Config.PASSWORD_SALT,
        digest_size=64,
    ).hash
    await users.insert_one(
        ModelFabric.Construct(
            Global.Users,
            id=uid,
            nickname=data["nickname"],
            email=email,
            passwordHash=passwordHash,
            aminoId=Generator.RandomAminoID(),
        )
    )
    row1 = await users.find_one({"id": uid})
    table = db.get(database="x0", table="Users")
    await table.insert_one(
        ModelFabric.Construct(Community.Users, id=uid, nickname=data["nickname"])
    )
    row2 = await table.find_one({"id": uid})
    await codes.delete_one({"deviceId": data["deviceID"], "email": email})
    db.close()

    return Base.Answer(
        {
            "newAccount": True,
            "auid": uid,
            "sid": await SessionProcessor.Make(
                uid, get_ip(request), data["clientType"]
            ),
            "account": User.OwnSensetiveProfile(row1),
            "userProfile": User.OwnNonSensetiveProfile(row1 | row2),
            "secret": data["secret"],
        },
        spent_time=timestamp() - t1,
    )


@logregin.post("/g/s/auth/register-check")
async def register_check(request: Request):
    data = await request.json()
    t1 = timestamp()

    try:
        if (not DeviceProcessor.Validate(data["deviceID"])) or (
            data["deviceID"] != request.headers["NDCDEVICEID"]
        ):
            raise Exception()

        email = data.get("email") or data.get("identity")
        if email:
            if not await EmailProcessor.Validate(email):
                raise Exception("Invalid email")

            db = await Database().init()
            gl_users = db.get(table="Users")
            row = await gl_users.find_one({"email": email})
            if row is not None:
                return Errors.EmailWasTaken(timestamp() - t1, lang=request.state.lang)
        elif "secret" in data:
            if data["secret"][:2] != "0 ":
                raise Exception("Invalid secret")
        else:
            raise Exception("What to do?")
    except Exception as e:
        print(e)
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)
    return Base.Answer(spent_time=timestamp() - t1)


@logregin.post("/g/s/auth/login")
async def login(request: Request):
    t1 = timestamp()
    data = await request.json()

    if data.get("email") is None or data.get("secret") is None:
        return Errors.InvalidLogin(timestamp() - t1, lang=request.state.lang)

    if not await EmailProcessor.Validate(data["email"]):
        return Errors.InvalidRequest(timestamp() - t1, lang=request.state.lang)

    secretSplitted = data["secret"].split()
    prefix = secretSplitted[0]
    if prefix == "0":
        passwordHash = Blake(
            data=data["secret"], key=Config.PASSWORD_SALT, digest_size=64
        ).hash

        db = await Database().init()
        table = db.get(table="Users")
        row = await table.find_one(
            {
                "passwordHash": passwordHash,
                "email": {"$regex": f"^{re.escape(data['email'])}$", "$options": "i"},
            }
        )

        if row is None:
            db.close()
            return Errors.InvalidLogin(timestamp() - t1, lang=request.state.lang)
        elif row.get("status", 0) == 9:
            db.close()
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)
        else:
            table = db.get("x0", "Users")
            additionalRow = await table.find_one({"id": row["id"]})

            ip = get_ip(request)
            tmstmp = ceil(timestamp())

            await SessionProcessor.End(request.headers.get("NDCAUTH"))
            db.close()

            ferrets_meal = dumps(
                {
                    "p": ip,
                    "t": tmstmp,
                    "i": row["id"],
                    "h": passwordHash,
                }
            )
            return Base.Answer(
                {
                    "auid": row["id"],
                    "account": User.OwnSensetiveProfile(row),
                    "userProfile": User.OwnNonSensetiveProfile(additionalRow | row),
                    "secondSecret": f"54 {Ferret.encrypt(ferrets_meal)}",
                    "secret": f"31 {row['id']} {ip} {b64encode(passwordHash.encode()).decode()} {tmstmp} {31 * tmstmp}",
                    "sid": await SessionProcessor.Make(
                        row["id"], ip, data["clientType"]
                    ),
                },
                spent_time=timestamp() - t1,
            )
    # [NOTE]: future login system
    elif prefix == "54":
        junk = secretSplitted[1]
        data = Ferret.decrypt(junk)

        db = await Database().init()
        table = db.get(table="Users")
        row = await table.find_one({"id": data["i"]})
        if row is None or row["passwordHash"] != data["h"]:
            db.close()
            return Errors.InvalidLogin(
                spent_time=timestamp() - t1, lang=request.state.lang
            )
        if row.get("status", 0) == 9:
            db.close()
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

        table = db.get(database="x0", table="Users")
        additionalRow = await table.find_one({"id": row["id"]})
        db.close()

        ip = get_ip(request)
        tmstmp = ceil(timestamp())
        await SessionProcessor.End(request.headers.get("NDCAUTH"))
        return Base.Answer(
            {
                "auid": row["id"],
                "account": User.OwnSensetiveProfile(row),
                "userProfile": User.OwnNonSensetiveProfile(additionalRow | row),
                "sid": await SessionProcessor.Make(row["id"], ip, data["clientType"]),
            },
            spent_time=timestamp() - t1,
        )
    # [DEPRECATED]
    # when password reset will be known as well working it will be wiped
    # for now its just a compatibility thing
    elif prefix == "31":
        if (len(secretSplitted) != 6) or (
            int(secretSplitted[0]) * int(secretSplitted[4]) != int(secretSplitted[5])
        ):
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )
        decodedPswdHash = b64decode(secretSplitted[3]).decode()
        db = await Database().init()
        table = db.get(table="Users")
        row = await table.find_one({"id": secretSplitted[1]})
        if row is None or row["passwordHash"] != decodedPswdHash:
            db.close()
            return Errors.InvalidLogin(
                spent_time=timestamp() - t1, lang=request.state.lang
            )
        if row.get("status", 0) == 9:
            db.close()
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

        table = db.get(database="x0", table="Users")
        additionalRow = await table.find_one({"id": row["id"]})
        db.close()

        ip = get_ip(request)
        tmstmp = ceil(timestamp())
        await SessionProcessor.End(request.headers.get("NDCAUTH"))
        return Base.Answer(
            {
                "auid": row["id"],
                "account": User.OwnSensetiveProfile(row),
                "userProfile": User.OwnNonSensetiveProfile(additionalRow | row),
                "sid": await SessionProcessor.Make(row["id"], ip, data["clientType"]),
            },
            spent_time=timestamp() - t1,
        )
    else:
        return Errors.InvalidRequest(
            spent_time=timestamp() - t1, lang=request.state.lang
        )


@logregin.post("/g/s/auth/logout")
async def logout(request: Request):
    t1 = timestamp()
    await request.json()

    await SessionProcessor.End(request.headers.get("NDCAUTH"))

    return Base.Answer(
        {"auid": request.state.session.get("uid", str(uuid4()))},
        spent_time=timestamp() - t1,
    )


@logregin.get("/g/s/device/dev-options")
async def dev_device(request: Request):
    t1 = timestamp()

    uid = request.state.session.get("uid")

    if uid:
        db = await Database().init()
        table = db.get(table="Users")
        row = await table.find_one({"id": uid})
        db.close()
        if row.get("status", 0) == 9:
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

    return Base.Answer({"devOptions": None}, timestamp() - t1)


@logregin.post("/g/s/device")
@logregin.post("/x{ndcId}/s/device")
async def device(request: Request, ndcId: int = 0):
    t1 = timestamp()

    uid = request.state.session.get("uid")
    if uid:
        db = await Database().init()
        table = db.get(f"x{ndcId}", "Users")
        row = await table.find_one({"id": uid})
        db.close()
        if row is None:
            return Errors.AccountNotExist(timestamp() - t1, lang=request.state.lang)
        if row.get("status", 0) == 9:
            return Errors.UserBanned(timestamp() - t1, lang=request.state.lang)

    try:
        await PushProcessor.Register(uid, await request.json())
    except Exception as e:
        print("/device register fail:", e)

    return Base.Answer({"devOptions": None}, timestamp() - t1)
