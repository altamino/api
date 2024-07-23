from helpers.routers.cachable import CachableRoute
from helpers.imageTools import ImageTools
from string import ascii_letters, digits
from fastapi import APIRouter, Request
from time import time as timestamp
from helpers.config import Config
from boto3 import resource
from random import choice
from objects import *

import sys
sys.path.append('../')

upload_media = APIRouter()
upload_media.route_class = CachableRoute

@upload_media.post('/g/s/media/upload')
async def upload(request: Request):
    t1 = timestamp()
    if not request.state.session.get("uid"):
        return Errors.InvalidSession(timestamp()-t1)
    
    # this is getting data
    body = await request.body()
    headers = request.headers
    
    if len(body) > Config.MAX_FILE_SIZE:
        return Errors.BigMediaContent(timestamp()-t1)
        
    # init s3 class
    s3 = resource(
        service_name=Config.S3_SERVICE_NAME,
        aws_access_key_id=Config.S3_ACCESS_KEY,
        aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
        endpoint_url=Config.S3_ENDPOINT_URL
    )

    # generating filename
    content_type = headers.get("Content-Type", "")
    if "," in content_type:
        arr_c_t = content_type.split(",")
        for i in arr_c_t:
            if "image" in i:
                content_type = i
                break

    filetype_dict = {
        "image/jpg": ".jpg",
        "image/jpeg": ".jpeg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif"
    }
    filetype = filetype_dict.get(content_type, "")
    if filetype == "":
        return Errors.InvalidMediaContent(spent_time=timestamp()-t1)
    filename = ''.join([choice(ascii_letters+digits) for _ in range(64)])+filetype
        
    # compress + resize if needed
    body = ImageTools.compress(body, filetype[1:])

    # upload file
    s3.Bucket(Config.S3_BUCKET_NAME).put_object(
        Key = filename,
        Body = body
    )
    return Base.Answer({
        "mediaValue": Config.MEDIA_BASE_URL + filename
    }, timestamp()-t1)

@upload_media.post('/g/s/media/upload/target/{target}')
async def upload_with_target(request: Request, target: str):
    t1 = timestamp()
    if not request.state.session.get("uid"):
        return Errors.InvalidSession(timestamp()-t1)
    
    # this is getting data
    body = await request.body()
    headers = request.headers

    if len(body) > Config.MAX_FILE_SIZE:
        return Errors.BigMediaContent(timestamp()-t1)
        
    # init s3 class
    s3 = resource(
        service_name=Config.S3_SERVICE_NAME,
        aws_access_key_id=Config.S3_ACCESS_KEY,
        aws_secret_access_key=Config.S3_SECRET_ACCESS_KEY,
        endpoint_url=Config.S3_ENDPOINT_URL
    )

    # generating filename
    content_type = headers.get("Content-Type", "")
    filetype_dict = {
        "image/jpg": ".jpg",
        "image/jpeg": ".jpeg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif"
    }
    filetype = filetype_dict.get(content_type, "")
    if filetype == "":
        return Errors.InvalidMediaContent(spent_time=timestamp()-t1)
    filename = ''.join([choice(ascii_letters+digits) for _ in range(64)])+filetype
        
    # compress + resize if needed
    body = ImageTools.compress(body, filetype[1:])

    # upload file
    s3.Bucket(Config.S3_BUCKET_NAME).put_object(
        Key = filename,
        Body = body
    )
    return Base.Answer({
        "mediaValue": Config.MEDIA_BASE_URL + filename
    }, timestamp()-t1)
