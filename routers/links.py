from re import search
from time import time as timestamp

from fastapi import APIRouter, Request

from helpers.database.models import Global, ModelFabric
from helpers.database.mongo import Database
from helpers.generator import Generator
from helpers.routers.cachable import CachableRoute
from objects import Base, Errors, Links, Communities

links = APIRouter()
links.route_class = CachableRoute


@links.post("/g/s/link-resolution")
@links.post("/g/s-x{ndcId}/link-resolution")
@links.post("/x{ndcId}/s/link-resolution")
@links.post("/g/s/link-translation")
@links.post("/g/s-x{ndcId}/link-translation")
@links.post("/x{ndcId}/s/link-translation")
async def make_link(request: Request, ndcId: int = 0):
    t1 = timestamp()
    data = await request.json()

    db = await Database().init()
    links_table = db.get(table="Links")

    if data["objectType"] == 0:
        if str(ndcId) in request.url.path:
            check_table = db.get(f"x{ndcId}", "Users")
        else:
            check_table = db.get(table="Users")
    elif data["objectType"] in [1, 2]:
        check_table = db.get(f"x{ndcId}", "Blogs")
    elif data["objectType"] == 12:
        check_table = db.get(f"x{ndcId}", "Chats")
    elif data["objectType"] == 15:
        check_table = db.get(f"x{ndcId}", "Communities")
    else:
        db.close()
        print(data)
        return Errors.UnimplementedPath(timestamp() - t1, lang=request.state.lang)

    check = await check_table.find_one({"id": data["objectId"]})
    if check is None:
        db.close()
        return Errors.MythicData(timestamp() - t1, lang=request.state.lang)

    link = await links_table.find_one(
        {"objectId": data["objectId"], "objectType": data["objectType"], "ndcId": ndcId}
    )

    if link is None:
        link = ModelFabric.Construct(
            Global.Links,
            code=(
                check["aminoId"]
                if data["objectType"] == 0 and ndcId == 0
                else Generator.RealString(8)
            ),
            targetCode=data.get("targetCode", 1),
            objectId=data["objectId"],
            objectType=data["objectType"],
            ndcId=ndcId,
        )
        await links_table.insert_one(link)
    db.close()

    if data["objectType"] == 0:
        return Base.Answer(Links.User(link), spent_time=timestamp() - t1)
    elif data["objectType"] in [1, 2]:
        return Base.Answer(Links.Blog(link), spent_time=timestamp() - t1)
    elif data["objectType"] == 12:
        return Base.Answer(Links.Chat(link), spent_time=timestamp() - t1)
    elif link["objectType"] == 15:
        return Base.Answer(Links.Community(link), spent_time=timestamp() - t1)


@links.get("/g/s/link-resolution")
@links.get("/g/s/link-resolution")
@links.get("/x{ndcId}/s/link-resolution")
@links.get("/g/s/link-translation")
@links.get("/x{ndcId}/s/link-translation")
@links.get("/g/s/link-identify")
@links.get("/x{ndcId}/s/link-identify")
async def resolute_link(request: Request, q: str, ndcId: int = 0):
    t1 = timestamp()
    db = await Database().init()
    links_table = db.get(table="Links")

    match = search(r"(http|https):\/\/altamino.top\/(?P<type>.*)\/(?P<code>.*)", q)
    if match is None:
        code_type = None
        query = q
    else:
        code_type, query = match.group("type"), match.group("code")

    if code_type == "c":
        cum_table = db.get(table="Communities")
        cum_data = await cum_table.find_one({"aminoId": query})
        db.close()
        if cum_data is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            Links.Community(
                {
                    "objectType": 16,
                    "ndcId": cum_data.get("id"),
                    "code": query,
                    "objectId": str(cum_data.get("id")),
                }
            ),
            spent_time=timestamp() - t1,
        )

    link = await links_table.find_one({"code": query})

    if code_type == "u" and link is None:
        gl_users_table = db.get(table="Users")
        link = await gl_users_table.find_one({"aminoId": query})
        db.close()
        if link is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            Links.User(
                {
                    "objectType": 0,
                    "ndcId": 0,
                    "code": query,
                    "objectId": str(link.get("id")),
                }
            ),
            spent_time=timestamp() - t1,
        )

    if code_type == "p" and link is None:
        blogs_table = db.get(table="Blogs")
        link = await blogs_table.find_one({"id": query})
        db.close()
        if link is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
        return Base.Answer(
            Links.Blog(
                {
                    "objectType": 1,
                    "ndcId": 0,
                    "code": query,
                    "objectId": str(link.get("id")),
                }
            ),
            spent_time=timestamp() - t1,
        )

    db.close()
    if link is None:
        return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)
    if link["objectType"] == 0:
        return Base.Answer(Links.User(link), spent_time=timestamp() - t1)
    elif link["objectType"] in [1, 2]:
        return Base.Answer(Links.Blog(link), spent_time=timestamp() - t1)
    elif link["objectType"] == 12:
        return Base.Answer(Links.Chat(link), spent_time=timestamp() - t1)


@links.get("/g/s/community/link-identify")
async def community_link_identify(request: Request, q: str = ""):
    t1 = timestamp()
    uid = request.state.session["uid"]
    db = await Database().init()
    try:
        q = q.strip()

        if "/c/" in q:
            aminoid_or_id = q[q.find("/c/") + 3 :]
            aminoid_or_id = aminoid_or_id.split("/")[0].split("?")[0].strip()
        else:
            aminoid_or_id = q

        table = db.get(table="Communities")
        community = await table.find_one({"aminoId": aminoid_or_id})
        if community is None:
            return Errors.DataNotExist(timestamp() - t1, lang=request.state.lang)

        community_info = await Communities.Info(community, db, uid)

        return Base.Answer(
            {
                "community": community_info,
                "path": f"x{community['id']}/community/{community['id']}",
                "isCurrentUserJoined": uid in community.get("memberList", []),
                "isMembershipRequestedByCurrentUser": False,
            },
            spent_time=timestamp() - t1,
        )
    finally:
        db.close()
