# import

from objects import *
from fastapi import FastAPI
from brotli_asgi import BrotliMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse, RedirectResponse

# routers

from routers.mock import mock
from routers.chats import chats
from routers.links import links
from routers.logregin import logregin
from routers.profile import profile_methods
from routers.upload_media import upload_media
from routers.configurations import configurations

# app things

app = FastAPI(
    title="AltAmino", version="1.0.0b1",
    docs_url=None, redoc_url=None
)

@app.get("/")
def redirect():
    return RedirectResponse("https://altamino.top")

app.include_router(mock, prefix="/api/v1")
app.include_router(chats, prefix="/api/v1")
app.include_router(links, prefix="/api/v1")
app.include_router(logregin, prefix="/api/v1")
app.include_router(upload_media, prefix="/api/v1")
app.include_router(configurations, prefix="/api/v1")
app.include_router(profile_methods, prefix="/api/v1")

app.add_middleware(
    BrotliMiddleware,
    gzip_fallback=True
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(403)
@app.exception_handler(422)
async def custom_403_handler(_, __):
    return Errors.Forbidden()

@app.exception_handler(404)
@app.exception_handler(405)
async def custom_404_handler(_, __):
    return Errors.InvalidPath()

@app.exception_handler(500)
async def custom_500_handler(_, __):
    if isinstance(__.args[0], ORJSONResponse):
        return __.args[0]
    print(_)
    print(__)
    return Errors.InternalServerError()
