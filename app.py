from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import Dict
import sqlite3
import os
from datetime import datetime

# Configuración básica
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Función para inicializar la base de datos
def init_db():
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    
    # Crear tabla de usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    
    # Crear tabla de mensajes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            text TEXT,
            image_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    
    # Insertar usuarios iniciales si la tabla está vacía
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO users (user_id, username, password) VALUES (?, ?, ?)
        """, [
            ("1", "user1", "pass1"),
            ("2", "user2", "pass2")
        ])
    
    conn.commit()
    conn.close()

# Inicializar la base de datos al arrancar
init_db()

# Clase para manejar las conexiones WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        conn = sqlite3.connect("chat.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            self.active_connections[user_id] = websocket
            print(f"Usuario {user_id} conectado")
        else:
            await websocket.close(code=1008, reason="User ID inválido")
        conn.close()

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"Usuario {user_id} desconectado")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

# Ruta para la página de login
@app.get("/login", response_class=HTMLResponse)
async def get_login():
    with open("login.html") as f:
        return f.read()

# Ruta para la página del chat
@app.get("/chat", response_class=HTMLResponse)
async def get_chat():
    with open("chat.html") as f:
        return f.read()

# Endpoint para autenticación
@app.post("/auth")
async def authenticate(username: str, password: str):
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE username = ? AND password = ?", (username, password))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"user_id": result[0]}
    raise HTTPException(status_code=401, detail="Credenciales inválidas")

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user_id = websocket.query_params.get("user_id")
    if not user_id:
        await websocket.close(code=1008, reason="User ID requerido")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "send_message":
                conn = sqlite3.connect("chat.db")
                cursor = conn.cursor()
                if "text" in data:
                    # Guardar y enviar mensaje de texto
                    cursor.execute("INSERT INTO messages (user_id, text) VALUES (?, ?)", (user_id, data["text"]))
                    conn.commit()
                    await manager.broadcast({"type": "new_message", "text": data["text"]})
                elif "file" in data:
                    # Guardar y enviar archivo (imagen)
                    file_data = base64.b64decode(data["file"]["data"])
                    file_type = data["file"]["type"]
                    file_ext = file_type.split("/")[-1]
                    file_name = f"static/uploads/{user_id}_{datetime.now().timestamp()}.{file_ext}"
                    os.makedirs("static/uploads", exist_ok=True)
                    with open(file_name, "wb") as f:
                        f.write(file_data)
                    cursor.execute("INSERT INTO messages (user_id, image_path) VALUES (?, ?)", (user_id, file_name))
                    conn.commit()
                    await manager.broadcast({"type": "new_message", "image_path": f"/{file_name}"})
                conn.close()

            elif action == "get_users":
                # Enviar lista de usuarios en línea
                conn = sqlite3.connect("chat.db")
                cursor = conn.cursor()
                cursor.execute("SELECT username, user_id FROM users")
                users = [{"username": row[0], "online": row[1] in manager.active_connections} for row in cursor.fetchall()]
                conn.close()
                await manager.send_personal_message({"type": "users_list", "users": users}, user_id)

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        conn = sqlite3.connect("chat.db")
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        username = cursor.fetchone()[0]
        conn.close()
        await manager.broadcast({"type": "user_left", "username": username})

# Cargar mensajes previos al conectar (opcional)
@app.get("/messages")
async def get_messages():
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, text, image_path FROM messages ORDER BY timestamp ASC")
    messages = [{"user_id": row[0], "text": row[1], "image_path": row[2]} for row in cursor.fetchall()]
    conn.close()
    return messages

# Iniciar el servidor
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)