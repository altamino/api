from secrets import token_hex, token_urlsafe, token_bytes
from string import ascii_letters, digits
from random import Random, choices

class Generator:
    """
    Facade to provide quick access to generating tokens,
    strings and bunch of other stuff.
    """
    def Token(length: int = 16) -> str:
        return token_hex(length)
    
    def RealString(length: int = 16) -> str:
        return ''.join(choices(ascii_letters+digits, k=length))

    def String(length: int = 16) -> str:
        return token_urlsafe(length)
    
    def Bytes(length: int = 16, seed: int | float | str | bytes | bytearray | None = None):
        if seed:
            r = Random(seed)
            return bytes([r.randint(0, 255) for _ in range(length)])
        else:
            return token_bytes(length)