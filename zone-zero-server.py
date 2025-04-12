# -*- coding: utf-8 -*-

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Dict
import uuid
import json

app = FastAPI()

# Хранилище лобби (в памяти)
lobbies: Dict[str, dict] = {}
# Подключенные клиенты по lobby_id
clients: Dict[str, List[WebSocket]] = {}

class LobbyCreateRequest(BaseModel):
    username: str  # Например, "@Andrei"

class LobbyJoinRequest(BaseModel):
    creator: str   # Имя создателя лобби, например, "@Andrei"
    username: str  # Имя присоединяющегося, например, "@Bob"

class StartGameRequest(BaseModel):
    lobby_id: str
    username: str

# Валидация имени пользователя
def is_valid_username(username: str) -> bool:
    return username.startswith("@") and len(username) > 1

# Создание лобби
@app.post("/create_lobby")
async def create_lobby(request: LobbyCreateRequest):
    username = request.username
    if not is_valid_username(username):
        return {"error": "Invalid username"}
    
    if username in lobbies:
        return {"error": "A lobby with this name already exists."}
    
    lobby_id = str(uuid.uuid4())
    lobbies[username] = {
        "lobby_id": lobby_id,
        "creator": username,
        "players": [username],
        "status": "waiting",
        "max_players": 4,
        "scores": {username: 0}
    }
    clients[lobby_id] = []
    
    return {
        "lobby_id": lobby_id,
        "creator": username,
        "players": [username]
    }

# Присоединение к лобби
@app.post("/join_lobby")
async def join_lobby(request: LobbyJoinRequest):
    creator = request.creator
    username = request.username
    
    if not (is_valid_username(creator) and is_valid_username(username)):
        return {"error": "Invalid username"}
    
    if creator not in lobbies:
        return {"error": "Lobby not found"}
    
    lobby = lobbies[creator]
    if len(lobby["players"]) >= lobby["max_players"]:
        return {"error": "The lobby is full"}
    
    if username in lobby["players"]:
        return {"error": "You are already in the lobby"}
    
    lobby["players"].append(username)
    lobby["scores"][username] = 0
    
    # Уведомляем клиентов через WebSocket
    await notify_clients(lobby["lobby_id"], {
        "lobby_id": lobby["lobby_id"],
        "players": lobby["players"],
        "status": lobby["status"]
    })
    
    return {
        "lobby_id": lobby["lobby_id"],
        "creator": creator,
        "players": lobby["players"]
    }

# Запуск игры
@app.post("/start_game")
async def start_game(request: StartGameRequest):
    lobby_id = request.lobby_id
    username = request.username
    
    # Найти лобби по lobby_id
    lobby = None
    creator = None
    for c, l in lobbies.items():
        if l["lobby_id"] == lobby_id:
            lobby = l
            creator = c
            break
    
    if not lobby:
        return {"error": "Lobby not found"}
    
    if username != lobby["creator"]:
        return {"error": "Only the creator can start the game"}
    
    lobby["status"] = "started"
    
    # Уведомляем клиентов
    await notify_clients(lobby_id, {
        "lobby_id": lobby_id,
        "players": lobby["players"],
        "status": "started"
    })
    
    return {"message": "The game has started"}

# WebSocket для реального времени
@app.websocket("/ws/lobby")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            action = message.get("action")
            
            if action == "create":
                username = message.get("username")
                if not is_valid_username(username):
                    await websocket.send_json({"error": "Invalid username"})
                    continue
                
                if username in lobbies:
                    await websocket.send_json({"error": "A lobby with this name already exists."})
                    continue
                
                lobby_id = str(uuid.uuid4())
                lobbies[username] = {
                    "lobby_id": lobby_id,
                    "creator": username,
                    "players": [username],
                    "status": "waiting",
                    "max_players": 4,
                    "scores": {username: 0}
                }
                clients[lobby_id] = [websocket]
                
                await websocket.send_json({
                    "lobby_id": lobby_id,
                    "creator": username,
                    "players": [username]
                })
            
            elif action == "join":
                creator = message.get("creator")
                username = message.get("username")
                
                if not (is_valid_username(creator) and is_valid_username(username)):
                    await websocket.send_json({"error": "Invalid username"})
                    continue
                
                if creator not in lobbies:
                    await websocket.send_json({"error": "Lobby not found"})
                    continue
                
                lobby = lobbies[creator]
                if len(lobby["players"]) >= lobby["max_players"]:
                    await websocket.send_json({"error": "The lobby is full"})
                    continue
                
                if username in lobby["players"]:
                    await websocket.send_json({"error": "You are already in the lobby"})
                    continue
                
                lobby["players"].append(username)
                lobby["scores"][username] = 0
                clients[lobby["lobby_id"]].append(websocket)
                
                await notify_clients(lobby["lobby_id"], {
                    "lobby_id": lobby["lobby_id"],
                    "players": lobby["players"],
                    "status": lobby["status"]
                })
            
            elif action == "start":
                lobby_id = message.get("lobby_id")
                username = message.get("username")
                
                lobby = None
                creator = None
                for c, l in lobbies.items():
                    if l["lobby_id"] == lobby_id:
                        lobby = l
                        creator = c
                        break
                
                if not lobby:
                    await websocket.send_json({"error": "Lobby not found"})
                    continue
                
                if username != lobby["creator"]:
                    await websocket.send_json({"error": "Only the creator can start the game"})
                    continue
                
                lobby["status"] = "started"
                await notify_clients(lobby_id, {
                    "lobby_id": lobby_id,
                    "players": lobby["players"],
                    "status": "started"
                })
    
    except WebSocketDisconnect:
        # Удаляем клиента из всех лобби
        for lobby_id, client_list in clients.items():
            if websocket in client_list:
                client_list.remove(websocket)
                # Если лобби пустое, удаляем его
                for creator, lobby in list(lobbies.items()):
                    if lobby["lobby_id"] == lobby_id and not client_list:
                        del lobbies[creator]
                break

async def notify_clients(lobby_id: str, message: dict):
    if lobby_id in clients:
        for client in clients[lobby_id]:
            try:
                await client.send_json(message)
            except:
                clients[lobby_id].remove(client)