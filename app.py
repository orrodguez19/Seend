import os
import socketio
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict
from socketio import AsyncServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = 'static'
TEMPLATES_DIR = 'templates'

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

create_tables()

app = FastAPI()
sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict] = {}  # {user_id: {sid, username}}

    async def connect(self, sid: str, user_id: str, username: str):
        self.active_connections[user_id] = {'sid': sid, 'username': username}
        await self.notify_users_update()

    async def disconnect(self, sid: str):
        user_id_to_remove = None
        for user_id, info in self.active_connections.items():
            if info['sid'] == sid:
                user_id_to_remove = user_id
                break
        
        if user_id_to_remove:
            del self.active_connections[user_id_to_remove]
            await self.notify_users_update()

    async def notify_users_update(self):
        with get_db_connection() as conn:
            users = conn.execute("SELECT id, username FROM users").fetchall()
            user_list = []
            for user in users:
                is_online = str(user['id']) in self.active_connections
                user_list.append({
                    'id': user['id'],
                    'username': user['username'],
                    'online': is_online
                })
        
        await sio.emit('users_updated', {'users': user_list})
        logger.info("Lista de usuarios actualizada enviada")

manager = ConnectionManager()

@app.post("/api/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    with get_db_connection() as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                return JSONResponse(
                    status_code=400,
                    content={"detail": "El nombre de usuario ya existe"}
                )
            
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            conn.commit()
            user_id = cursor.lastrowid
            
            logger.info(f"Usuario registrado: {username} (ID: {user_id})")
            return {
                "message": "Usuario registrado exitosamente",
                "user_id": user_id,
                "username": username
            }
        except Exception as e:
            logger.error(f"Error al registrar usuario: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Error interno del servidor"}
            )

@app.post("/api/login")
async def login_user(username: str = Form(...), password: str = Form(...)):
    with get_db_connection() as conn:
        try:
            user = conn.execute(
                "SELECT id, username FROM users WHERE username = ? AND password = ?",
                (username, password)
            ).fetchone()
            
            if not user:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Usuario o contraseña incorrectos"}
                )
            
            logger.info(f"Usuario autenticado: {username} (ID: {user['id']})")
            return {
                "message": "Inicio de sesión exitoso",
                "user_id": user['id'],
                "username": user['username']
            }
        except Exception as e:
            logger.error(f"Error al autenticar usuario: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Error interno del servidor"}
            )

@sio.event
async def connect(sid, environ, auth):
    try:
        user_id = auth.get('user_id')
        if not user_id:
            raise ConnectionRefusedError('Se requiere user_id para autenticación')
        
        with get_db_connection() as conn:
            user = conn.execute(
                "SELECT id, username FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            
            if not user:
                raise ConnectionRefusedError('Usuario no encontrado')
            
            await manager.connect(sid, str(user['id']), user['username'])
            await sio.emit('user_ready', {
                'username': user['username'],
                'id': user['id']
            }, to=sid)
            
            # Cargar últimos 50 mensajes
            messages = conn.execute("""
                SELECT m.id, m.sender_id, u.username, m.text, m.created_at as timestamp 
                FROM messages m JOIN users u ON m.sender_id = u.id 
                ORDER BY m.created_at DESC LIMIT 50
            """).fetchall()
            
            await sio.emit('load_messages', {
                'messages': [dict(msg) for msg in reversed(messages)]
            }, to=sid)
            
            await manager.notify_users_update()
            logger.info(f"Usuario conectado: {user['username']} (SID: {sid})")
            
    except Exception as e:
        logger.error(f"Error de conexión: {str(e)}")
        raise ConnectionRefusedError(f'Error de autenticación: {str(e)}')

@sio.event
async def disconnect(sid):
    await manager.disconnect(sid)
    logger.info(f"Cliente desconectado: {sid}")

@sio.event
async def send_message(sid, data):
    try:
        # Encontrar user_id por sid
        user_id = None
        username = None
        for uid, info in manager.active_connections.items():
            if info['sid'] == sid:
                user_id = uid
                username = info['username']
                break
        
        if not user_id:
            await sio.emit('auth_error', {
                'message': 'No autenticado'
            }, to=sid)
            return
        
        text = data.get('text', '').strip()
        if not text:
            return
        
        message_id = str(uuid.uuid4())
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO messages (id, sender_id, text) VALUES (?, ?, ?)",
                (message_id, user_id, text)
            )
            conn.commit()
        
        message_data = {
            'id': message_id,
            'sender_id': user_id,
            'username': username,
            'text': text,
            'timestamp': datetime.now().isoformat()
        }
        
        await sio.emit('new_message', message_data)
        logger.info(f"Nuevo mensaje de {username}: {text}")
        
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {str(e)}")

@sio.event
async def get_users(sid):
    await manager.notify_users_update()

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(os.path.join(TEMPLATES_DIR, "auth.html"))

@app.get("/auth", response_class=HTMLResponse)
async def auth_page():
    return FileResponse(os.path.join(TEMPLATES_DIR, "auth.html"))

@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return FileResponse(os.path.join(TEMPLATES_DIR, "chat.html"))

app.mount("/", socketio.ASGIApp(sio))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)