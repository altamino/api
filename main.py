# import

from brotli_asgi import BrotliMiddleware
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse, RedirectResponse
from routers.static_things import static_things

from objects import Errors

# routes
from routers.altacm import altacm
from routers.blogs import blog_methods
from routers.chats import chats
from routers.communities import communities
from routers.configurations import configurations
from routers.comments import comments_router
from routers.links import links
from routers.logregin import logregin
from routers.mock import mock
from routers.moderation_tools import moderation_tools
from routers.profile import profile_methods
from routers.turtle import turtle
from routers.upload_media import upload_media
from routers.altteam import altteam
from routers.store import store
from routers.notification import notification_methods

# app things

app = FastAPI(title="AltAmino", version="1", docs_url=None, redoc_url=None)


@app.get("/")
async def redirect():
    return RedirectResponse("https://altamino.top")


@app.get("/health")
async def health():
    return {"alive": True}


app.include_router(mock, prefix="/api/v1")
app.include_router(chats, prefix="/api/v1")
app.include_router(turtle, prefix="/api/v1")
app.include_router(links, prefix="/api/v1")
app.include_router(logregin, prefix="/api/v1")
app.include_router(upload_media, prefix="/api/v1")
app.include_router(configurations, prefix="/api/v1")
app.include_router(profile_methods, prefix="/api/v1")
app.include_router(communities, prefix="/api/v1")
app.include_router(blog_methods, prefix="/api/v1")
app.include_router(comments_router, prefix="/api/v1")
app.include_router(moderation_tools, prefix="/api/v1")
app.include_router(altacm, prefix="/api/v1")
app.include_router(altteam, prefix="/api/v1")
app.include_router(store, prefix="/api/v1")
app.include_router(notification_methods, prefix="/api/v1")
app.include_router(static_things)

# brotli can break amino libraries, but it's easy to fix
# either enable support for brotli, or just remove "brotli" from headers
app.add_middleware(BrotliMiddleware, gzip_fallback=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dont be like us, configure it, im lazy to do it rn
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(403)
async def custom_403_handler(_, __):
    return Errors.Forbidden(lang=_.headers.get("NDCLANG", "en"))


@app.exception_handler(404)
@app.exception_handler(405)
async def custom_404_handler(_, __):
    print("No path like: ", _.url.path, "(", await _.body(), ") | ", __)
    return Errors.InvalidPath(lang=_.headers.get("NDCLANG", "en"))


@app.exception_handler(422)
@app.exception_handler(RequestValidationError)
async def custom_422_handler(_, exc: RequestValidationError):
    print(exc.errors())
    return Errors.CantProcessData(lang=_.headers.get("NDCLANG", "en"))


@app.exception_handler(500)
async def custom_500_handler(_, __):
    try:
        if isinstance(__.args[0], ORJSONResponse) or isinstance(
            __.args[0], JSONResponse
        ):
            return __.args[0]
    except Exception:
        print("Not a status code that we returned!")

    try:
        print("What happened:", _, "//", __)
    except Exception:
        print("WE CAN'T EVEN FUCKING PRINT WHAT HAPPENED. COOL")

    return Errors.InternalServerError(lang=_.headers.get("NDCLANG", "en"))
