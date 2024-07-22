from hashlib import sha1
from hmac import new

class DeviceProcessor:
    """
    Processor that validates devices.
    Made because there was a bunch of device ids.
    """

    did_keys = {
        "01": b'\xe9\xaf-\x7fC\x1e\x87\xa4\xf8\xc7\xb6\xf4^\xfc\x04\xb7\xe5\xf0\xeaO',
        "18": b'\xd1\x9d,\xb8F\x8a\xac\x9b\n\xe1k\xe4\xa6\xfaFK\xe67`\xce',
        "19": b"\xe70\x9e\xcc\tS\xc6\xfa`\x00['e\xf9\x9d\xbb\xc9e\xc8\xe9",
        "32": b'v\xb4\xa1V\xaa\xcc\xad\xe17\xb8\xb1\xe7{CZ\x81\x97\x1f\xbd>',
        "42": b'\x02\xb2X\xc65Y\xd8\x80C!\xc5\xd5\x06Z\xf3 5\x8d6o',
        "52": b'\xaeIU\x04X\xd8\xe7\xc5\x1dVi\x16\xb0H\x88\xbf\xb8\xb3\xca}',
    }

    @staticmethod
    def Validate(device_id: str):
        """
        True - device_id is valid
        False - device_id is NOT valid
        """

        did_keys = DeviceProcessor.did_keys
        device_id = device_id.upper()
        prefix, identifier, mac = device_id[:2], device_id[:-40], device_id[-40:]
        if prefix not in did_keys.keys():
            return False
        
        dev_key = did_keys[prefix]
        calculated_mac = new(dev_key, bytes.fromhex(identifier), sha1).hexdigest()
        return mac.upper() == calculated_mac.upper()