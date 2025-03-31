from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import sqlite3
import hashlib
import uvicorn
from typing import List, Dict
import asyncio

app = FastAPI()

# Modelos Pydantic para validación
class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# Configuración de la base de datos
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Gestión de WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_status: Dict[str, str] = {}  # Para rastrear estados (online, offline, typing)

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections[username] = websocket
        self.user_status[username] = "online"
        await self.broadcast({"type": "user_joined", "username": username})

    def disconnect(self, username: str):
        if username in self.active_connections:
            del self.active_connections[username]
            self.user_status[username] = "offline"
            asyncio.create_task(self.broadcast({"type": "user_left", "username": username}))

    async def send_personal_message(self, message: dict, username: str):
        if username in self.active_connections:
            await self.active_connections[username].send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

# Funciones de utilidad
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Rutas API
@app.post("/register")
async def register(user: UserRegister):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    c.execute("SELECT username FROM users WHERE username = ?", (user.username,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    
    hashed_password = hash_password(user.password)
    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", 
             (user.username, hashed_password))
    conn.commit()
    conn.close()
    return {"message": "User registered successfully"}

@app.post("/login")
async def login(user: UserLogin):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    hashed_password = hash_password(user.password)
    c.execute("SELECT username FROM users WHERE username = ? AND password = ?", 
             (user.username, hashed_password))
    
    result = c.fetchone()
    conn.close()
    
    if result:
        return {"message": "Login successful", "username": user.username}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/users")
async def get_users():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return {"users": users}

# WebSocket endpoint
@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    # Verificar si el usuario existe
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username = ?", (username,))
    if not c.fetchone():
        await websocket.close(code=1008)
        return
    conn.close()

    await manager.connect(websocket, username)
    try:
        while True:
            data = await websocket.receive_json()
            
            # Mensaje privado
            if data.get("type") == "message" and "to" in data:
                message = {
                    "type": "message",
                    "username": username,
                    "content": data["content"]
                }
                await manager.send_personal_message(message, data["to"])
                if username != data["to"]:  # Enviar al remitente también
                    await manager.send_personal_message(message, username)
            
            # Indicador de escritura
            elif data.get("type") == "typing" and "to" in data:
                if data["to"] in manager.active_connections:
                    await manager.send_personal_message({
                        "type": "typing",
                        "username": username
                    }, data["to"])
            
            # Mensaje visto
            elif data.get("type") == "message_seen" and "to" in data:
                if data["to"] in manager.active_connections:
                    await manager.send_personal_message({
                        "type": "message_seen",
                        "username": username
                    }, data["to"])
            
            # Mensaje broadcast (no usado en este caso, pero mantenido por compatibilidad)
            else:
                await manager.broadcast({
                    "type": "message",
                    "username": username,
                    "content": data.get("content", "")
                })
                
    except WebSocketDisconnect:
        manager.disconnect(username)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)