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
        "positions": {username: {"x": 0.0, "y": 0.0, "z": 0.0}},
        "items": {}
    }
    clients[lobby_id] = []
    
    print(f"Created lobby {lobby_id} for {username}")
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
    lobby["positions"][username] = {"x": 0.0, "y": 0.0, "z": 0.0}
    
    await notify_clients(lobby["lobby_id"], {
        "lobby_id": lobby["lobby_id"],
        "players": lobby["players"],
        "status": lobby["status"]
    })
    
    print(f"{username} joined lobby {lobby['lobby_id']}")
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
        "seed": seed,
        "items": lobby["items"]
    })
    
    print(f"Game started in lobby {lobby_id} with seed {seed}, generated {len(lobby['items'])} items")
    return {"message": "Game has started"}

@app.websocket("/ws/lobby")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_ip = websocket.client.host
    print(f"WebSocket client connected: {client_ip}")
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
                print(f"Received message from {client_ip}: {data}")
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
                        "scores": {username: 0},
                        "seed": 0,
                        "positions": {username: {"x": 0.0, "y": 0.0, "z": 0.0}},
                        "items": {}
                    }
                    clients[lobby_id] = [websocket]
                    
                    await websocket.send_json({
                        "lobby_id": str(lobby_id),
                        "creator": username,
                        "players": [username],
                        "status": "waiting"
                    })
                    print(f"Created lobby {lobby_id} for {username}")
                
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

                    if lobby["status"] == "started":
                        await websocket.send_json({"error": "Game already started, cannot join"})
                        continue
                    
                    lobby["players"].append(username)
                    lobby["scores"][username] = 0
                    lobby["positions"][username] = {"x": 0.0, "y": 0.0, "z": 0.0}
                    clients[lobby["lobby_id"]].append(websocket)
                    
                    await notify_clients(lobby["lobby_id"], {
                        "lobby_id": str(lobby["lobby_id"]),
                        "players": lobby["players"],
                        "status": lobby["status"]
                    })
                    print(f"{username} joined lobby {lobby['lobby_id']}")
                
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
                        "seed": seed,
                        "items": lobby["items"]
                    })
                    print(f"Game started in lobby {lobby_id} with seed {seed}, generated {len(lobby['items'])} items")
                
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
                                    except Exception as e:
                                        print(f"Error notifying client in lobby {lobby_id}: {e}")
                            del clients[lobby_id]
                        del lobbies[creator]
                        print(f"Lobby {lobby_id} deleted by creator {username}")
                        await websocket.send_json({"message": "Lobby closed"})
                    else:
                        if username in lobby["players"]:
                            lobby["players"].remove(username)
                            del lobby["scores"][username]
                            del lobby["positions"][username]
                            if lobby_id in clients:
                                if websocket in clients[lobby_id]:
                                    clients[lobby_id].remove(websocket)
                            await notify_clients(lobby_id, {
                                "lobby_id": lobby_id,
                                "players": lobby["players"],
                                "status": lobby["status"]
                            })
                            print(f"{username} left lobby {lobby_id}")
                            await websocket.send_json({"message": "Left lobby"})

                elif action == "player_ready":
                    username = message.get("username")
                    is_ready = message.get("is_ready", False)
                    lobby_id = message.get("lobby_id")
    
                    if lobby_id in lobbies:
                        lobby = None
                        for c, l in lobbies.items():
                            if l["lobby_id"] == lobby_id:
                                lobby = l
                                break
        
                        if lobby:
                            if "ready_players" not in lobby:
                                lobby["ready_players"] = {}
                            lobby["ready_players"][username] = is_ready
            
                            all_ready = all(lobby["ready_players"].get(p, False) for p in lobby["players"])
            
                            if all_ready:
                                await notify_clients(lobby_id, {
                                    "action": "all_players_ready",
                                    "lobby_id": lobby_id
                                })
                
                elif action == "update_position":
                    lobby_id = message.get("lobby_id")
                    username = message.get("username")
                    x = message.get("x", 0.0)
                    y = message.get("y", 0.0)
                    z = message.get("z", 0.0)
                    
                    lobby = None
                    for c, l in lobbies.items():
                        if l["lobby_id"] == lobby_id:
                            lobby = l
                            break
                    
                    if not lobby:
                        await websocket.send_json({"error": "Lobby not found"})
                        continue
                    
                    if username not in lobby["players"]:
                        await websocket.send_json({"error": "Player not in lobby"})
                        continue
                    
                    lobby["positions"][username] = {"x": x, "y": y, "z": z}
                    print(f"Updated position for {username} in lobby {lobby_id}: x={x}, y={y}, z={z}")
                    
                    await notify_clients(lobby_id, {
                        "action": "update_position",
                        "lobby_id": lobby_id,
                        "username": username,
                        "x": x,
                        "y": y,
                        "z": z
                    })
                
                elif action == "collect_item":
                    lobby_id = message.get("lobby_id")
                    username = message.get("username")
                    item_id = message.get("item_id")
                    
                    lobby = None
                    for c, l in lobbies.items():
                        if l["lobby_id"] == lobby_id:
                            lobby = l
                            break
                    
                    if not lobby:
                        await websocket.send_json({"error": "Lobby not found"})
                        continue
                    
                    if username not in lobby["players"]:
                        await websocket.send_json({"error": "Player not in lobby"})
                        continue
                    
                    if item_id not in lobby["items"]:
                        await websocket.send_json({"error": "Item not found"})
                        continue
                    
                    if lobby["items"][item_id]["collected"]:
                        await websocket.send_json({"error": "Item already collected"})
                        continue
                    
                    lobby["items"][item_id]["collected"] = True
                    lobby["scores"][username] = lobby["scores"].get(username, 0) + 1
                    print(f"Item {item_id} collected by {username} in lobby {lobby_id}, new score: {lobby['scores'][username]}")
                    
                    await notify_clients(lobby_id, {
                        "action": "item_collected",
                        "lobby_id": lobby_id,
                        "item_id": item_id,
                        "username": username,
                        "scores": lobby["scores"]
                    })

                elif action == "register_items":
                    lobby_id = message.get("lobby_id")
                    items = message.get("items", [])
        
                    lobby = None
                    for c, l in lobbies.items():
                        if l["lobby_id"] == lobby_id:
                            lobby = l
                            break
        
                    if not lobby:
                        await websocket.send_json({"error": "Lobby not found"})
                        continue
        
                    lobby["items"] = {}
                    for item in items:
                        item_id = item.get("item_id")
                        if item_id:
                            lobby["items"][item_id] = {
                                "collected": False,
                                "position": item.get("position", {"x": 0, "y": 0, "z": 0})
                            }
        
                    await notify_clients(lobby_id, {
                        "action": "items_registered",
                        "lobby_id": lobby_id,
                        "items_count": len(lobby["items"])
                    })
        
                    print(f"Registered {len(lobby['items'])} items in lobby {lobby_id}")
                
                elif action == "ping":
                    username = message.get("username", f"Unknown_{client_ip}")
                    await websocket.send_json({"action": "pong"})
                    print(f"Ping received from {username}, sent pong")
            
            except WebSocketDisconnect:
                await handle_disconnect(websocket)
                break
    
    except WebSocketDisconnect:
        await handle_disconnect(websocket)

async def handle_disconnect(websocket: WebSocket):
    client_ip = websocket.client.host
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
                                del lobby["positions"][username]
                                await notify_clients(lobby_id, {
                                    "lobby_id": lobby_id,
                                    "players": lobby["players"],
                                    "status": lobby["status"]
                                })
                                print(f"Removed {username} from lobby {lobby_id} due to disconnect")
            print(f"WebSocket client disconnected: {client_ip}")
            break

async def notify_clients(lobby_id: str, message: dict):
    if lobby_id in clients:
        for client in list(clients[lobby_id]):
            try:
                await client.send_json(message)
            except Exception as e:
                clients[lobby_id].remove(client)
                print(f"Removed disconnected client from lobby {lobby_id}: {e}")