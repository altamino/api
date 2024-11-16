from re import match
from requests import get


class EmailProcessor:
    """
    Processor for validating and removing temp emails.
    You don't really want to use temp emails in social network don't you?
    """

    CANT_SEND_HERE = ["icloud.com"]

    @staticmethod
    def NotWorking(email: str) -> bool:
        """
        True if our mail server cant send code to provided email, False if bad
        """
        if not match(
            r"^([a-z0-9]+(?:[._-][a-z0-9]+)*)@([a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,})$",
            email,
        ):
            return False

        return email.partition("@")[2] in EmailProcessor.CANT_SEND_HERE

    @staticmethod
    def Validate(email: str) -> bool:
        """
        True if email is good, False if bad
        """
        if not match(
            r"^([a-z0-9]+(?:[._-][a-z0-9]+)*)@([a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,})$",
            email,
        ):
            return False

        try:
            info = get(f"https://disposable.debounce.io", {"email": email}).json()
        except:
            info = {}

        return info.get("disposable", False)
