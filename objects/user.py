from typing import Union

class User:
    @staticmethod
    def OwnSensetiveProfile(row):
        return {
            "username": None,
            "status": row['status'],
            "uid": row['id'],
            "modifiedTime": row['modifiedTime'],
            "createdTime": row['createdTime'],
            "twitterID": None,
            "googleID": None,
            "appleID": None,
            "facebookID": None,
            "role": row.get('role', 0),
            "aminoIdEditable": True,
            "aminoId": row['aminoId'],
            "activation": 1,
            "phoneNumberActivation": 0,
            "emailActivation": 1,
            "nickname": row['nickname'],
            "mediaList": None,
            "icon": None if row['icon'] == "" else row['icon'],
            "securityLevel": 3, #idk what is it
            "phoneNumber": None,
            "membership": None,
            "advancedSettings": {
                "analyticsEnabled": 0
            },
            "email": row['email'],
            "extensions": {
                "contentLanguage": "en",
                "adsFlags": 2147483647, # change to hide ads
                "adsLevel": 2, # change to hide ads
                "deviceInfo": {
                    "lastClientType": 100 # i dont wanna store in memory that, its useless bro
                },
                "popupConfig": {
                    "ads": {
                        "status": 0,
                        "lastPopupTime": "1970-01-01T00:00:00Z"
                    }
                },
                "mediaLabAdsMigrationAugust2020": True,
                "adsEnabled": False
            }
        }

    @staticmethod
    def OwnNonSensetiveProfile(row, ndcId: int = 0, extenstions: dict = {}): 
        '''
            ndcId for another communities
            triggerUserId is who triggered this shit
        '''
        return {
            "status": row['status'],
            "uid": row['id'],
            "modifiedTime": row['modifiedTime'],
            "createdTime": row['createdTime'],
            "role": row.get('role', 0),
            "aminoId": row['aminoId'],
            "nickname": row['nickname'],
            "mediaList": None if row['mediaList'] in [[], None] else row['mediaList'],
            "icon": None if row['icon'] == "" else row['icon'],
            "accountMembershipStatus": int(row.get('isPaidSubscriber')),
            "ndcId": ndcId, # 0 is global
            "isGlobal": True if ndcId == 0 else False,
            "reputation": 0 if ndcId == 0 else row['reputation'],
            "level": 0 if ndcId == 0 else row['level'],
            "mood": None if ndcId == 0 else row['mood'],
            "content": None if row['description'] in ["", None] else row['description'].strip(),
            "joinedCount": len(row['following']),
            "followingStatus": 0,
            "membersCount": len(row['whoFollows']),
            "storiesCount": 0, # i will NOT implement stories, fuck them
            "blogsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "postsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "extenstions": extenstions,
            "moodSticker": None if ndcId == 0 else row['mood'], # [TODO]: check wtf is this
            "consecutiveCheckInDays": None if ndcId == 0 else row['consecutiveDaysOfCheckIns'],  # [TODO] when communitues will be implemented do that
            "onlineStatus": 2, # [TODO]: check wtf is this
            "isNicknameVerified": False,
            "notificationSubscriptionStatus":0,
            "pushEnabled": True,
            "membershipStatus": 0,
            "commentsCount": len(row['wall'])
        }
    
    @staticmethod
    def OtherProfile(row, triggerUserId: Union[str, None] = None, ndcId: int = 0, extenstions: dict = {}):
        if triggerUserId == None:
            membershipStatus = 0
        elif triggerUserId in row.get('whoFollows', []):
            membershipStatus = 1
        elif row['id'] in row.get('following', []):
            membershipStatus = 2
        else:
            membershipStatus = 0
        return {
            "status": row['status'],
            "uid": row['id'],
            "modifiedTime": row['modifiedTime'],
            "createdTime": row['createdTime'],
            "role": row.get('role', 0),
            "aminoId": row['aminoId'],
            "nickname": row['nickname'],
            "mediaList": None if row['mediaList'] in [[], None] else User.MediaList(row['mediaList']),
            "icon": None if row['icon'] == "" else row['icon'],
            "accountMembershipStatus": int(row.get('isPaidSubscriber')),
            "ndcId": ndcId, # 0 is global
            "isGlobal": ndcId == 0,
            "reputation": 0 if ndcId == 0 else row['reputation'],
            "level": 0 if ndcId == 0 else row['level'],
            "mood": None if ndcId == 0 else row['mood'],
            "content": None if row['description'] in ["", None] else row['description'].strip(),
            "joinedCount": len(row['whoFollows']),
            "followingStatus": membershipStatus,
            "membersCount": len(row['followers']),
            "storiesCount": 0, # i will NOT implement stories, fuck them
            "blogsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "postsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "extenstions": extenstions,
            "moodSticker": None if ndcId == 0 else row['mood'], # [TODO]: check wtf is this
            "consecutiveCheckInDays": None if ndcId == 0 else row['consecutiveDaysOfCheckIns'],  # [TODO] when communitues will be implemented do that
            "onlineStatus": 2, # [TODO]: check wtf is this
            "isNicknameVerified": False,
            "notificationSubscriptionStatus":0,
            "pushEnabled": True,
            "membershipStatus": membershipStatus,
            "commentsCount": len(row['wall'])
        }

    # [NOTE] onlineStatus : 1 when online, 2 when not
    # [NOTE] allowance : 1 when all, 2 when followers, 3 if not at all
    @staticmethod
    def GetUserInfo(row, ndcId: int = 0, triggerUserId: Union[str, None] = None, extenstions: dict = {}, membershipStatus: int | None = None):
        if membershipStatus == None:
            if triggerUserId == None:
                membershipStatus = 0
            elif triggerUserId in row['whoFollows'] and triggerUserId in row['following']:
                membershipStatus = 3
            elif triggerUserId in row['following']:
                membershipStatus = 2
            elif triggerUserId in row['whoFollows']:
                membershipStatus = 1
            else:
                membershipStatus = 0
        if row['id'] == triggerUserId:
            membershipStatus = 0
        return {
            "iconFrameId": row.get('frame'),
            "iconFrame": None if row.get('frame') == None else User.iconFrame(row.get('frame')),
            "status": row['status'],
            "uid": row['id'],
            "modifiedTime": row['modifiedTime'],
            "createdTime": row['createdTime'],
            "role": row.get('role', 0),
            "aminoId": row['aminoId'],
            "nickname": row['nickname'],
            "fanClubList": [],
            "mediaList": None if row['mediaList'] in [[], None] else User.MediaList(row['mediaList']),
            "icon": None if row['icon'] == "" else row['icon'],
            "accountMembershipStatus": int(row.get('isPaidSubscriber', 0)),
            "ndcId": ndcId, # 0 is global
            "isGlobal": ndcId == 0,
            "reputation": 0 if ndcId == 0 else row['reputation'],
            "level": 0 if ndcId == 0 else row['level'],
            "mood": None if ndcId == 0 else row['mood'],
            "moodSticker": None if ndcId == 0 else row['mood'], # [TODO]: check wtf is this
            "content": None if row['description'] in ["", None] else row['description'].strip(),
            "joinedCount": len(row['following']),
            "followingStatus": membershipStatus,
            "membersCount": len(row['whoFollows']),
            "storiesCount": 0, # i will NOT implement stories, fuck them
            "blogsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "postsCount": 0 if ndcId else 0, # [TODO] when communitues will be implemented do that
            "extenstions": {
                "privilegeOfCommentOnUserProfile": row['allowanceWriteToWall'],
                "privilegeOfChatInviteRequest": row['allowanceWriteToPM'],
                "coverAnimation": "none",
                "deviceInfo": {
                    "lastClientType": 100 # [TODO]: WTF IS LAST CLIENT TYPE WHY THEY SAVE IT AND GIVE IT TO RANDOM USER WHAT THE ACTUAL FUCK BRO
                },
                "contentLanguage": "en",
                "style": {
                    "backgroundColor": None if row['mediaList'] != [] else row['backgroundColor'],
                    "backgroundMediaList": User.MediaList(row['mediaList']) if row['mediaList'] != [] else None
                },
                "defaultBubbleId":"85045ed8-b05b-40de-907e-ec886889d086",
                "iconFrameId":"f3f280c5-a41a-4aa8-933a-4d740d67804e"
            } | extenstions,
            "consecutiveCheckInDays": None if ndcId == 0 else row['consecutiveDaysOfCheckIns'],  # [TODO] when communitues will be implemented do that
            "onlineStatus": 2, # [TODO]: check wtf is this
            "isNicknameVerified": False,
            "notificationSubscriptionStatus":0,
            "pushEnabled": True,
            "membershipStatus": membershipStatus,
            "commentsCount": len(row['wall']),
            "itemsCount": len(row['purchasedItems'].get("frames", []))+len(row['purchasedItems'].get("bubbles", [])),
            "visitPrivacy": 1,
            "visitorsCount": 0 # [TODO]: make visitors count as var in table and do smart count
        }

    '''
        "iconFrame":{
            "status":0,
            "ownershipStatus":1,
            "version":1,
            "resourceUrl":"http://af1.aminoapps.com/packages/8105/828d84a47df292b765d47b71d1dfbad2b347ce60.zip",
            "name":"Gray",
            "icon":"http://af1.aminoapps.com/8105/1c67b12dec2dfb63e8d0a96f735cd4f8238eff6c_00.gif",
            "frameType":1,
            "frameId":"93c220b6-2460-4c26-bde1-52095fffd6cd"
        }
    '''
    @staticmethod
    def iconFrame(frameId: str):
        return {
            "frameId": frameId
        }

    @staticmethod
    def MediaList(mediaList: list):
        return [User.MediaItem(item) for item in mediaList]
    
    @staticmethod
    def MediaItem(link: str):
        return [
            100,
            link,
            None,
            None,
            None,
            {

            }
        ]