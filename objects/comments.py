from .user import User
from typing import Union
from datetime import datetime

#import sys
#sys.path.append('../')
from helpers.database.mongo import Database

class Comments:
    @staticmethod
    async def Parent(row, commentId: str, parentId: str, g_users, xndcid_users, triggerUserId: str | None = None, parentType: int = 0, ndcId: int = 0, extenstions: dict = {}):
        return {
            "modifiedTime": row['modifiedTime'], 
            "ndcId": ndcId, 
            "votedValue": int(triggerUserId in row['likes']),
            "parentType": parentType, # im guessing its for posts and etc
            "commentId": commentId, # comment id
            "parentNdcId": ndcId,
            "mediaList": None if row['mediaList'] in [[], None] else User.MediaList(row['mediaList']), # if have images i guess
            "votesSum": len(row['likes']), # how many likes
            "subcommentsPreview": [], # subcomments preview
            "author": User.GetUserInfo(
                await g_users.find_one( {"id": row['authorId']} ) | await xndcid_users.find_one( {"id": row['authorId']} )
            ), 
            "content": row['content'],
            "extensions": {} | extenstions,
            "parentId": parentId,
            "createdTime": row['createdTime'],
            "subcommentsCount": len(row['subWMs']),
            "type": 0
        }
    @staticmethod
    async def Son(row, commentId: str, headCommentId: str, parentId: str, g_users, xndcid_users, triggerUserId: str | None = None, parentType: int = 0, ndcId: int = 0, extenstions: dict = {}):
        return {
            "headCommentId": headCommentId,
            "modifiedTime": row['modifiedTime'], 
            "ndcId": ndcId, 
            "votedValue": int(triggerUserId in row['likes']),
            "parentType": parentType, # im guessing its for posts and etc
            "commentId": commentId, # comment id
            "parentNdcId": ndcId,
            "mediaList": None if row['mediaList'] in [[], None] else User.MediaList(row['mediaList']), # if have images i guess
            "votesSum": len(row['likes']), # how many likes
            "author": User.GetUserInfo(
                await g_users.find_one( {"id": row['authorId']} ) | await xndcid_users.find_one( {"id": row['authorId']} )
            ), 
            "content": row['content'],
            "extensions": {} | extenstions,
            "parentId": parentId,
            "createdTime": row['createdTime'],
            "subcommentsCount": 0,
            "type": 0
        }