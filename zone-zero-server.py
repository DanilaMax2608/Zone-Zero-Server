# -*- coding: utf-8 -*-

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Dict
import uuid
import json
import random

app = FastAPI()

lobbies: Dict[str, dict] = {}
clients: Dict[str, List[WebSocket]] = {}

class LobbyCreateRequest(BaseModel):
    username: str

class LobbyJoinRequest(BaseModel):
    creator: str
    username: str

class StartGameRequest(BaseModel):
    lobby_id: str
    username: str
    seed: int = 0

def is_valid_username(username: str) -> bool:
    return username.startswith("@") and len(username) > 1

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
        "scores": {username: 0},
        "seed": 0,
        "positions": {}
    }
    clients[lobby_id] = []
    
    return {
        "lobby_id": lobby_id,
        "creator": username,
        "players": [username],
        "status": "waiting"
    }

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
    
    await notify_clients(lobby["lobby_id"], {
        "lobby_id": lobby["lobby_id"],
        "players": lobby["players"],
        "status": lobby["status"]
    })
    
    return {
        "lobby_id": str(lobby["lobby_id"]),
        "creator": creator,
        "players": lobby["players"],
        "status": lobby["status"]
    }

@app.post("/start_game")
async def start_game(request: StartGameRequest):
    lobby_id = request.lobby_id
    username = request.username
    seed = request.seed
    
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
    lobby["seed"] = seed  
    
    await notify_clients(lobby_id, {
        "lobby_id": lobby_id,
        "players": lobby["players"],
        "status": "started",
        "seed": seed
    })
    
    return {"message": "Game has started"}

@app.websocket("/ws/lobby")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_host = websocket.client.host
    print(f"INFO: New WebSocket connection from {client_host}")
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
                print(f"DEBUG: Raw message received from {client_host}: {data}")

                try:
                    message = json.loads(data)
                except json.JSONDecodeError as e:
                    print(f"ERROR: Failed to parse JSON from {client_host}: {e}")
                    await websocket.send_json({"error": "Invalid JSON format"})
                    continue
                    
                print(f"DEBUG: Parsed message from {client_host}: {message}")

                action = message.get("action")
                if not action:
                    print(f"WARNING: No action in message from {client_host}")
                    await websocket.send_json({"error": "Missing action field"})
                    continue
                
                # Обработка update_position
                if action == "update_position":
                    username = message.get("username")
                    lobby_id = message.get("lobby_id")
                    position = message.get("position", {})
                    
                    if not username or not lobby_id:
                        print(f"WARNING: Missing fields in update_position from {client_host}: username={username}, lobby_id={lobby_id}")
                        await websocket.send_json({"error": "Missing username or lobby_id"})
                        continue
                    
                    print(f"DEBUG: Processing update_position from {username} in lobby {lobby_id}")
                    
                    # Находим лобби
                    lobby = None
                    for c, l in lobbies.items():
                        if l["lobby_id"] == lobby_id:
                            lobby = l
                            break
                    
                    if not lobby:
                        print(f"WARNING: Lobby {lobby_id} not found for {username}")
                        await websocket.send_json({"error": "Lobby not found"})
                        continue
                    
                    if username not in lobby["players"]:
                        print(f"WARNING: Player {username} not in lobby {lobby_id}")
                        await websocket.send_json({"error": "Player not in lobby"})
                        continue
                    
                    # Обновляем позицию
                    try:
                        lobby["positions"][username] = {
                            "x": float(position.get("x", 0)),
                            "y": float(position.get("y", 0)),
                            "z": float(position.get("z", 0))
                        }
                        print(f"DEBUG: Updated position for {username} in lobby {lobby_id}: {lobby['positions'][username]}")
                    except (TypeError, ValueError) as e:
                        print(f"ERROR: Invalid position data from {username}: {position}, error: {e}")
                        await websocket.send_json({"error": "Invalid position data"})
                        continue
                    
                    # Рассылаем обновление другим клиентам
                    await notify_clients(lobby_id, {
                        "action": "update_position",
                        "lobby_id": lobby_id,
                        "username": username,
                        "position": lobby["positions"][username]
                    }, exclude_sender=websocket)
                    
                # Обработка других действий
                elif action == "create":
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
                        "scores": {username: 0},
                        "seed": 0,
                        "positions": {}
                    }
                    clients[lobby_id] = [websocket]
                    
                    await websocket.send_json({
                        "lobby_id": str(lobby_id),
                        "creator": username,
                        "players": [username],
                        "status": "waiting"
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
                        "lobby_id": str(lobby["lobby_id"]),
                        "players": lobby["players"],
                        "status": lobby["status"]
                    })
                
                elif action == "start":
                    username = message.get("username")
                    lobby_id = message.get("lobby_id")
                    seed = message.get("seed", 0)
                    
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
                    lobby["seed"] = seed
                    
                    await notify_clients(lobby_id, {
                        "lobby_id": str(lobby_id),
                        "players": lobby["players"],
                        "status": "started",
                        "seed": seed
                    })
                
                elif action == "leave":
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
                    
                    if username == lobby["creator"]:
                        if lobby_id in clients:
                            for client in clients[lobby_id]:
                                if client != websocket:
                                    try:
                                        await client.send_json({"error": "Lobby closed by creator"})
                                        await client.close()
                                    except:
                                        pass
                            del clients[lobby_id]
                        del lobbies[creator]
                        print(f"INFO: Lobby {lobby_id} deleted by creator {username}")
                    else:
                        if username in lobby["players"]:
                            lobby["players"].remove(username)
                            del lobby["scores"][username]
                            if username in lobby["positions"]:
                                del lobby["positions"][username]
                            if lobby_id in clients:
                                if websocket in clients[lobby_id]:
                                    clients[lobby_id].remove(websocket)
                            await notify_clients(lobby_id, {
                                "lobby_id": lobby_id,
                                "players": lobby["players"],
                                "status": lobby["status"]
                            })
                
                else:
                    print(f"WARNING: Unknown action '{action}' from {client_host}")
                    await websocket.send_json({"error": "Unknown action"})
                    
            except WebSocketDisconnect:
                print(f"INFO: WebSocket disconnected by {client_host}")
                handle_disconnect(websocket)
                break
            except Exception as e:
                print(f"ERROR: Unexpected error handling message from {client_host}: {str(e)}")
                await websocket.send_json({"error": "Internal server error"})
                break
                
    except Exception as e:
        print(f"ERROR: WebSocket connection error with {client_host}: {str(e)}")
    finally:
        handle_disconnect(websocket)

def handle_disconnect(websocket: WebSocket):
    for lobby_id, client_list in list(clients.items()):
        if websocket in client_list:
            client_list.remove(websocket)
            for creator, lobby in list(lobbies.items()):
                if lobby["lobby_id"] == lobby_id:
                    if not client_list:
                        del lobbies[creator]
                        print(f"Lobby {lobby_id} deleted due to no clients")
                    else:
                        for username in list(lobby["players"]):
                            if username != lobby["creator"]:
                                lobby["players"].remove(username)
                                del lobby["scores"][username]
                                if username in lobby["positions"]:
                                    del lobby["positions"][username]
                                notify_clients(lobby_id, {
                                    "lobby_id": lobby_id,
                                    "players": lobby["players"],
                                    "status": lobby["status"]
                                })
            break

async def notify_clients(lobby_id: str, message: dict, exclude_sender=None):
    if lobby_id in clients:
        for client in list(clients[lobby_id]):
            if client != exclude_sender:
                try:
                    print(f"Sending to {client.client.host}: {message}")  # Лог отправки
                    await client.send_json(message)
                except Exception as e:
                    print(f"Failed to send to {client.client.host}: {e}")
                    clients[lobby_id].remove(client)