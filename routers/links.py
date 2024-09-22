from fastapi import APIRouter, Request
from time import time as timestamp

# import sys
# sys.path.append('../')
from objects import *
from helpers.database.mongo import *
from helpers.generator import Generator
from helpers.routers.cachable import CachableRoute

links = APIRouter()
links.route_class = CachableRoute


@links.post("/g/s/link-resolution")
@links.post("/g/s/link-translation")
async def make_link(request: Request):
    t1 = timestamp()
    data = await request.json()

    db = await Database().init()
    links_table = await db.get(table="Links")

    if data["objectType"] == 0:
        check_table = await db.get(table="Users")
    elif data["objectType"] == 12:
        check_table = await db.get("x0", "Chats")
    else:
        await db.close()
        return Errors.UnimplementedPath(timestamp() - t1)

    check = await check_table.find_one({"id": data["objectId"]})
    if check == None:
        await db.close()
        return Errors.MythicData(timestamp() - t1)

    link = await links_table.find_one(
        {"objectId": data["objectId"], "objectType": data["objectType"]}
    )
    if link == None:
        link = ModelFabric.Construct(
            Global.Links,
            code=(
                check["aminoId"] if data["objectType"] == 0 else Generator.RealString(8)
            ),
            targetCode=data.get("targetCode", 1),
            objectId=data["objectId"],
            objectType=data["objectType"],
        )
        await links_table.insert_one(link)
    await db.close()

    if data["objectType"] == 0:
        return Base.Answer(Links.User(link), spent_time=timestamp() - t1)
    elif data["objectType"] == 12:
        return Base.Answer(Links.Chat(link), spent_time=timestamp() - t1)


@links.get("/g/s/link-resolution")
@links.get("/g/s/link-translation")
async def resolute_link(request: Request, q: str):
    t1 = timestamp()

    db = await Database().init()
    links_table = await db.get(table="Links")

    q = (
        q.replace("http://aminoapps.com/", "http://altamino.top/")
        .replace("https://aminoapps.com/", "http://altamino.top/")
        .replace("http://altamino.top/u/", "")
        .replace("http://altamino.top/p/", "")
    )

    link = await links_table.find_one({"code": q})
    print(q)
    print(link)
    await db.close()

    if link == None:
        return Errors.InvalidRequest(timestamp() - t1)

    if link["objectType"] == 0:
        return Base.Answer(Links.User(link), spent_time=timestamp() - t1)
    elif link["objectType"] == 12:
        return Base.Answer(Links.Chat(link), spent_time=timestamp() - t1)
