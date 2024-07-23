from random import choice
from typing import Union
from .base import Base

class Errors:
    @staticmethod
    def SUS(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=420024,
            html_status_code=420,
            api_message="🤨",
            spent_time=spent_time
        )

    @staticmethod
    def UnsupportedClient(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=100, 
            html_status_code=400,
            api_message="Looks like your client is unsupported. Try update app or contact devs.",
            spent_time=spent_time,
        )
    
    @staticmethod
    def ExpiredRequest(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=10501, 
            html_status_code=400,
            api_message="Request is expired. Please try again.",
            spent_time=spent_time,
        )

    @staticmethod
    def ExpiredSession(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=105, 
            html_status_code=440,
            api_message="Session is expired. Please relogin.",
            spent_time=spent_time,
        )

    @staticmethod
    def InvalidSession(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=105, 
            html_status_code=440,
            api_message="Session is invalid. Please relogin.",
            spent_time=spent_time,
        )

    @staticmethod
    def InternalServerError(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=500, 
            html_status_code=500,
            api_message="Internal server error. If this error staying too long, contact AltAmino's dev team.",
            spent_time=spent_time,
        )
    @staticmethod
    def MailError(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=500, 
            html_status_code=500,
            api_message="Mail error. If this error staying too long, contact AltAmino's dev team.",
            spent_time=spent_time,
        )
    
    @staticmethod
    def WaitMinuteForAnotherCode(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=219, 
            html_status_code=400,
            api_message="Not so fast, Sonic! Wait for a minute to get code again",
            spent_time=spent_time,
        )  
    @staticmethod
    def TooManyRequest(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=219, 
            html_status_code=400,
            api_message="Whoa! Slow down! You are sending requests too quickly.",
            spent_time=spent_time,
        )   
    @staticmethod
    def Forbidden(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=403, 
            html_status_code=403,
            api_message="You trying to access forbidden method, media or you temporary banned.",
            spent_time=spent_time,
        )    
    @staticmethod
    def IpFrozen(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=403, 
            html_status_code=403,
            api_message="Your client and IP is frozen due trying find vulnerabilities or doing sus things.",
            spent_time=spent_time,
        )    
    @staticmethod
    def OutdatedDevice(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=218, 
            html_status_code=400,
            api_message="We dont support your device as it outdated. Sorry. :(",
            spent_time=spent_time,
        )
    
    @staticmethod
    def InvalidPath(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=100, 
            html_status_code=404, 
            api_message="Path or method does not exists. Contact Team AltAmino if this request should work.",
            spent_time=spent_time
        )
    @staticmethod
    def UnimplementedPath(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=400, 
            api_message="This method is created but is not available. Try again later.",
            spent_time=spent_time
        )
    @staticmethod
    def PathUnderMaintenance(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=500, 
            api_message="This method is under maintenance. Try again later.",
            spent_time=spent_time
        )    
    @staticmethod
    def PathWorkingInvalid(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=500, 
            api_message="Looks like this path working invalid or some data is missing. Try again later or contact devs.",
            spent_time=spent_time
        )    
    @staticmethod
    def InvalidRequest(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=400, 
            api_message="Invalid request. Check all data that you sended or try again later.",
            spent_time=spent_time
        )
    @staticmethod
    def InvalidMediaContent(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=400, 
            api_message="Invalid media content. Check all data that you sended or try again later.",
            spent_time=spent_time
        )
    @staticmethod
    def BigMediaContent(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=102, 
            html_status_code=400, 
            api_message="Media content is larger, than 5MB.",
            spent_time=spent_time
        )
    @staticmethod
    def BigMessage(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1664, 
            html_status_code=400, 
            api_message="Message content is larger, than 2345 symbols.",
            spent_time=spent_time
        )
    
    @staticmethod
    def IncorrectVerificationCode(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=3102, 
            html_status_code=400, 
            api_message="Invalid verification code. Make sure that you copied correct code.",
            spent_time=spent_time
        )    
    @staticmethod
    def EmailWasTaken(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=215, 
            html_status_code=400, 
            api_message="Email was taken for another account. Try different one.",
            spent_time=spent_time
        )  
    @staticmethod
    def NotWorkingEmail(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=215, 
            html_status_code=400, 
            api_message="Sorry, but we can't send code to this email. Try different one.",
            spent_time=spent_time
        )
    @staticmethod
    def InvalidEmail(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=215, 
            html_status_code=400, 
            api_message="This email is invalid. Try different one.",
            spent_time=spent_time
        )
    @staticmethod
    def ExpiredVerificationCode(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=3103, 
            html_status_code=400, 
            api_message="Link and verification code are expired. Request new verification code.",
            spent_time=spent_time
        )
    @staticmethod
    def InvalidVerificationCode(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=3104, 
            html_status_code=400, 
            api_message="Link and verification code are invalid. Request new verification code.",
            spent_time=spent_time
        )
    @staticmethod
    def VerificationCodeAlreadySent(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=3105, 
            html_status_code=400, 
            api_message="Verification already sent to your email. Please wait, check spam folder or contact AltAmino's dev team.",
            spent_time=spent_time
        )
    
    @staticmethod
    def InvalidLogin(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=200, 
            html_status_code=400, 
            api_message="Invalid login. Are your credentials are valid?",
            spent_time=spent_time
        )    
    @staticmethod
    def AccountNotExist(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=216, 
            html_status_code=400, 
            api_message="This account does not exist.",
            spent_time=spent_time
        )     
    @staticmethod
    def DataNotExist(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=107, 
            html_status_code=400, 
            api_message="The requested data does not exist.",
            spent_time=spent_time
        )   
    @staticmethod
    def AccountDisabled(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=201, 
            html_status_code=400, 
            api_message="This account was banned by AltAmino Team.",
            spent_time=spent_time
        )
    @staticmethod
    def AccountDeleted(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=246, 
            html_status_code=400, 
            api_message="This account was deleted by its owner.",
            spent_time=spent_time
        )
    
    @staticmethod
    def UnverifiedEmail(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=246, 
            html_status_code=400, 
            api_message="This email not verified. Did you even requested code?",
            spent_time=spent_time
        )    
    

    @staticmethod
    def TooManyChatUsers(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1605, 
            html_status_code=400, 
            api_message="In chat can be only 1000 users max. :(",
            spent_time=spent_time
        )
    @staticmethod
    def TooManyInvitedUsers(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1606, 
            html_status_code=400, 
            api_message="In chat can be invited only 1000 users max. :(",
            spent_time=spent_time
        )
    @staticmethod
    def ChatInvitesForbidden(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1611, 
            html_status_code=400, 
            api_message="It's forbidden to invite users here. :(",
            spent_time=spent_time
        )
    @staticmethod
    def RemovedFromChat(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1612, 
            html_status_code=400, 
            api_message="You're been removed from this chat. For some reason...",
            spent_time=spent_time
        )
    @staticmethod
    def UserNotJoined(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1612, 
            html_status_code=400, 
            api_message="You or member you selected not in chat. Join first!",
            spent_time=spent_time
        )
    @staticmethod
    def MemberKickedByOrganizer(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1637, 
            html_status_code=400, 
            api_message="This user was removed from this chat and cannot be reinvited.",
            spent_time=spent_time
        )
    @staticmethod
    def UserBanned(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=229, 
            html_status_code=400, 
            api_message="You are banned.",
            spent_time=spent_time
        )
    @staticmethod
    def ViewModeEnabled(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1663, 
            html_status_code=400, 
            api_message="Shh! Chat in View Only mode. 🤫",
            spent_time=spent_time
        )
    @staticmethod
    def ChatMessageTooBig(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=1664, 
            html_status_code=400, 
            api_message="We can't send this message, it's too big.",
            spent_time=spent_time
        )
    @staticmethod
    def InvalidMessage(spent_time: Union[int, float] = 0):
        return Base.Answer(
            api_status_code=103, 
            html_status_code=400, 
            api_message="Message you trying send is invalid.",
            spent_time=spent_time
        )
    
    @staticmethod
    def NotEnoughRights(spent_time: Union[int, float] = 0):
        phrase = [
            "Nuh-uh. 😉",
            "You can't. 😐",
            "You can't. Just can't. 😐",
            "You don't have permission to do that, innit? 😉",
            "Just stop lying that you have permissions to do that. 😉",
            "Wooow. Keep trying, I bet you will recieve something as result. 😙",
            "...Nice try though. 🧐",
            "You definetly know how to press buttons. If you pressed any. 🥱",
            "Sesame doesn't want to open. Try another phrase. 🤔",
            "... 😶"
        ]
        return Base.Answer(
            api_status_code=110, 
            html_status_code=400, 
            api_message=choice(phrase),
            spent_time=spent_time
        )
    
    @staticmethod
    def MythicData(spent_time: Union[int, float] = 0):
        phrase = [
            "This data does not exists in this world. Try reload page.",
            "Dungeon have some bugs. Try enter it again.",
            "There are legends about this data ... They say all you have to do is reload the page...",
            "Sesame is bugging. Try again."
        ]
        return Base.Answer(
            api_status_code=1600, 
            html_status_code=400, 
            api_message=choice(phrase),
            spent_time=spent_time
        )