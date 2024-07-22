from re import match
from requests import get

class EmailProcessor:
    """
    Processor for validating and removing temp emails.
    You don't really want to use temp emails in social network don't you?
    """
    @staticmethod
    def Validate(email: str) -> bool:
        '''
            True if email is good, False if bad
        '''
        if not match(r"^([a-z0-9]+(?:[._-][a-z0-9]+)*)@([a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,})$", email): 
            return False
        
        try: info = get(f"https://disposable.debounce.io", {"email": email}).json()
        except: info = {}

        return info.get("disposable", False)