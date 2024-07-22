from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from helpers.wsobjs import WSObjects
from datetime import datetime

import sys
sys.path.append('../')
from objects.errors import Errors
from helpers.database.mongo import Database
from helpers.middleware import CheckRequest


app = FastAPI()

clients = {}

@app.get("/")
async def index():
    return Errors.InvalidRequest()

@app.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    admin, uid, error = await CheckRequest(websocket)
    if error:
        return error, 400
    
    await websocket.accept()
    if not admin:
        clients.update({uid: websocket})

    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("t") and data.get("o"):
                if not data["o"].get("id"):
                    await websocket.send_json(WSObjects.WSError(1, "No ID of request"))
                    continue
                
                ws_req_id = data["o"].get("id")
                if data['t'] == 116:
                    await websocket.send_json(WSObjects.Pong(ws_req_id))
                    continue

                if data['t'] == 1001 and data['o'].get('markHasRead', None) != None:
                    if data['o']['markHasRead'] == True:
                        ndcId = data['o']['ndcId']
                        chatId = data['o']['threadId']
                        readTimestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                        
                        db = await Database().init()
                        chat = await db.get(f"x{ndcId}", "Chats")
                        await chat.update_one(
                            {"id": chatId},
                            {"$set": { f"lastReadedList.{uid}": readTimestamp }}
                        )
                        await db.close()
                    continue

            if data.get("ADMIN-SAYS") and admin:
                try:
                    js = data['ADMIN-SAYS']
                    users = js['VICTIMS']
                    payload = js['WEAPON']

                    if users == "ALL":
                        for _, ws in clients.items():
                            await ws.send_json(payload)
                    
                    else:
                        for user, ws in clients.items():
                            if user in users:
                                await ws.send_json(payload)
                    
                    await websocket.send_json({"status": "ok", "clients": len(clients)})
                except Exception as e:
                    await websocket.send_json({"status": "error", "reason": str(e)})
            
            continue

    except WebSocketDisconnect:
        if not admin:
            clients.pop(uid)
