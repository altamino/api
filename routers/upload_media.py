from io import BytesIO
from random import choice
from string import ascii_letters, digits
from time import time as timestamp
from zipfile import ZipFile

from boto3 import resource
from fastapi import APIRouter, Request
from orjson import loads

from helpers.config import Config
from helpers.database.mongo import Database
from helpers.decorators.bbnonsfw import bbnonsfw
from helpers.decorators.validauth import validauth_required
from helpers.functions import detect_file_ext
from helpers.imageTools import ImageTools
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors
from objects.types.users import UserRole as RoleTypes

upload_media = APIRouter()
upload_media.route_class = CachableRoute


@upload_media.post("/g/s/media/upload")
@upload_media.post("/x{ndcId}/s/media/upload")
@upload_media.post("/g/s/media/upload/target/{target}")
@upload_media.post("/x{ndcId}/s/media/upload/target/{target}")
@validauth_required
@bbnonsfw(target="body")
async def upload(request: Request, ndcId: int = 0, target: str = ""):
    t1 = timestamp()
    uid = request.state.session.get("uid")

    # this is getting data
    body = await request.body()

    if len(body) > Config.MAX_FILE_SIZE:
        return Errors.BigMediaContent(timestamp() - t1, lang=request.state.lang)

    # init s3 class
    s3 = resource(
        service_name=Config.S3_SERVICE_NAME,
        aws_access_key_id=Config.S3_ACCESS_KEY,
        aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
        endpoint_url=Config.S3_ENDPOINT_URL,
    )

    # validating imagw and getting its type
    # [note]: its still not safe,
    # but better and still fast then content-type
    file_ext = detect_file_ext(body)
    is_zip = body.startswith(b"PK\x03\x04")
    if file_ext is None and not is_zip:
        return Errors.InvalidMediaContent(
            spent_time=timestamp() - t1, lang=request.state.lang
        )

    if is_zip:
        # themes are basically zips
        if target == "theme":
            # ain't trust anyone! better check if it's leader/agent/astral
            db = await Database().init()
            g = db.get(table="Users")
            global_user_info = await g.find_one({"id": uid})
            if not RoleTypes.is_global_staff(global_user_info.get("role", 0)):
                table = db.get(f"x{ndcId}", table="Users")
                user_info = await table.find_one({"id": uid})
                if not RoleTypes.is_local_admin(user_info.get("role", 0)):
                    return Errors.NotEnoughRights()

            # if its valid zip we can get theme config and revision here
            # so that way we both checking theme and its config
            try:
                with BytesIO(body) as buffer:
                    with ZipFile(buffer) as zip_ref:
                        with zip_ref.open("theme_info.json") as f:
                            theme_config = loads(f.read())
                rev = theme_config["revision"]
            except Exception as e:
                return Errors.InvalidMediaContent(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

            filename = Config.S3_NDCTHEMES_FOLDER + f"x{ndcId}-rev{rev}.ndthemepack"
        elif target in ("avatar-frame", "chat-bubble", "sticker"):
            db = await Database().init()
            try:
                g = db.get(table="Users")
                user_info = await g.find_one({"id": uid})
                if not user_info or not RoleTypes.is_global_staff(
                    user_info.get("role", 0)
                ):
                    return Errors.NotEnoughRights(
                        timestamp() - t1, lang=request.state.lang
                    )
            finally:
                db.close()

            try:
                with BytesIO(body) as buffer:
                    with ZipFile(buffer) as zip_ref:
                        if zip_ref.testzip() is not None:
                            raise ValueError("bad zip")
            except Exception as e:
                return Errors.InvalidMediaContent(
                    spent_time=timestamp() - t1, lang=request.state.lang
                )

            filename = (
                Config.S3_STORE_FOLDER
                + "".join(choice(ascii_letters + digits) for _ in range(64))
                + ".zip"
            )

        else:
            return Errors.InvalidRequest(
                spent_time=timestamp() - t1, lang=request.state.lang
            )

    else:
        # generating filename
        filename = (
            Config.S3_IMAGES_FOLDER
            + "".join([choice(ascii_letters + digits) for _ in range(64)])
            + file_ext
        )

        # compress + resize if needed
        body = ImageTools.compress(body, file_ext[1:])

    # upload file
    s3.Bucket(Config.S3_BUCKET_NAME).put_object(Key=filename, Body=body)
    return Base.Answer(
        {"mediaValue": Config.MEDIA_BASE_URL + filename}, timestamp() - t1
    )