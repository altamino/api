from fastapi import Request
from fastapi import Request
from hashlib import blake2s
from .generator import Generator


def get_ip(request: Request) -> str:
    """since our servers under cloudflare, we need CF-Connecting-IP instead of X-Forwarded-For"""
    return request.headers.get("CF-Connecting-IP") or request.client.host or "1.1.1.1"


def get_hashed_ip(request: Request) -> str:
    return make_hash(get_ip(request), salt=b"ip")


def make_hash(*args: str | bytes, salt: bytes = None, need_salt: bool = False):
    """
    pass any data that string or bytes to make hash
    salt is max 8 bytes long
    """
    to_hash = b"".join(
        [item if isinstance(item, bytes) else item.encode() for item in args]
    )
    if need_salt and not salt:
        salt = Generator.Bytes(4)

    if salt:
        return blake2s(to_hash, salt=salt).hexdigest()
    return blake2s(to_hash).hexdigest()
