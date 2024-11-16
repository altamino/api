from hmac import new
from hashlib import sha1
from typing import Union
from orjson import dumps
from base64 import b64encode, b64decode


class SignatureProcessor:
    """
    Processor that validates signatures (ndc-msg-sig).
    Made because there was a bunch of signatures.
    """

    sig_keys = {
        b"\x19": b"\xdf\xa5\xed\x19-\xdan\x88\xa1/\xe1!0\xdcb\x06\xb1%\x1eD",
        b"\x22": b"0|<\x8c\xd3\x89\xe6\x9d\xc2\x98\xd9Q4\x1f\x88A\x9a\x83w\xf4",
        b"\x32": b"\xfb\xf9\x8e\xb3\xa0z\x90B\xeeU\x93\xb1\x0c\xe9\xf3(ji\xd4\xe2",
        b"\x42": b"\xf8\xe7\xa6\x1a\xc3\xf7%\x94\x1e:\xc7\xca\xe2\xd6\x88\xbe\x97\xf3\x0b\x93",
        b"\x52": b"\xea\xb4\xf1\xb9\xe34\x0c\xd1c\x1e\xde;X|\xc3\xeb\xed\xf1\xaf\xa9",
    }

    @staticmethod
    def Validate(signature: str, data: Union[str, bytes, dict]):
        """
        True - signature is valid
        False - signature is NOT valid
        """

        signature = signature.strip()
        sig_keys = SignatureProcessor.sig_keys

        if isinstance(data, dict):
            data = dumps(data)
        elif isinstance(data, str):
            data = data.encode()
        elif isinstance(data, bytes):
            pass
        else:
            raise Exception(
                f"Invalid type of data (expected str, bytes or dict, but recieved {type(data)} instead)"
            )

        prefix = b64decode(signature)[:1]
        if prefix not in sig_keys:
            return False

        return signature == b64encode(
            prefix + new(sig_keys[prefix], data, sha1).digest()
        ).decode("utf-8")
