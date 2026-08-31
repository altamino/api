def uuid_to_long(uuid_string: str | int) -> int:
    if isinstance(uuid_string, int):return uuid_string
    return int(uuid_string.replace("-", ""), 16) % (2**63 - 1)  # android needed int for mod history:(
