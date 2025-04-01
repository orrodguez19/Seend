import os
import socketio
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import uuid
import logging
import secrets
from datetime import datetime
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
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, sender_id INTEGER NOT NULL, text TEXT, image_path TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (sender_id) REFERENCES users(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at DATETIME NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id))")
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
        self.active_connections: Dict[str, str] = {}
        self.user_info: Dict[str, Dict] = {}

    async def connect(self, sid: str, user_id: str, username: str, session_token: str):
        self.active_connections[session_token] = user_id
        self.user_info[user_id] = {'username': username, 'sid': sid}
        await self.notify_users_update()

    async def disconnect(self, sid):
        user_id_to_remove = None
        session_token_to_remove = None
        for token, user_id in self.active_connections.items():
            if self.user_info.get(user_id, {}).get('sid') == sid:
                user_id_to_remove = user_id
                session_token_to_remove = token
                break
        if session_token_to_remove:
            del self.active_connections[session_token_to_remove]
        if user_id_to_remove in self.user_info:
            del self.user_info[user_id_to_remove]
            await self.notify_users_update()

    async def notify_users_update(self):
        user_list = []
        with get_db_connection() as conn:
            users = conn.execute("SELECT id, username FROM users").fetchall()
            for user in users:
                is_online = user['id'] in self.user_info
                user_list.append({'id': user['id'], 'username': user['username'], 'online': is_online})
        await sio.emit('users_updated', {'users': user_list})
        logger.info("Lista de usuarios actualizada enviada")

manager = ConnectionManager()

@app.post("/api/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return JSONResponse(status_code=400, content={"detail": "El nombre de usuario ya existe"})
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        logger.info(f"Usuario registrado: {username}")
        return {"message": "Usuario registrado exitosamente"}

@app.post("/api/login")
async def login_user(username: str = Form(...), password: str = Form(...)):
    with get_db_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if not user:
            return JSONResponse(status_code=400, content={"detail": "Usuario o contraseña incorrectos"})
        session_token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))", (session_token, user['id']))
        conn.commit()
        logger.info(f"Usuario {username} inició sesión, token: {session_token}")
        return {"message": "Inicio de sesión exitoso", "session_token": session_token}

@sio.event
async def connect(sid, environ, auth):
    try:
        session_token = auth.get('session_id')
        if not session_token:
            raise ConnectionRefusedError('No autenticado: Token de sesión no proporcionado')
        with get_db_connection() as conn:
            session = conn.execute("SELECT u.id, u.username FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.session_id = ? AND s.expires_at > datetime('now')", (session_token,)).fetchone()
            if not session:
                raise ConnectionRefusedError('No autenticado: Sesión inválida o expirada')
            await manager.connect(sid, str(session['id']), session['username'], session_token)
            await sio.emit('user_ready', {'username': session['username'], 'id': session['id']}, to=sid)
            messages = conn.execute("SELECT m.id, m.sender_id, u.username, m.text, m.image_path, m.created_at as timestamp FROM messages m JOIN users u ON m.sender_id = u.id ORDER BY m.created_at ASC").fetchall()
            await sio.emit('load_messages', {'messages': [dict(msg) for msg in messages]}, to=sid)
            await manager.notify_users_update()
            logger.info(f"Cliente conectado: {sid}, usuario: {session['username']}")
    except Exception as e:
        logger.error(f"Error de conexión: {str(e)}")
        raise ConnectionRefusedError(f'Autenticación fallida: {str(e)}')

@sio.event
async def disconnect(sid):
    await manager.disconnect(sid)
    logger.info(f"Cliente desconectado: {sid}")

@sio.event
async def send_message(sid, data):
    user_id = None
    for token, uid in manager.active_connections.items():
        if manager.user_info.get(uid, {}).get('sid') == sid:
            user_id = uid
            break
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    text = data.get('text', '').strip()
    logger.info(f"Mensaje recibido de {user_id}: {text}")
    message_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute("INSERT INTO messages (id, sender_id, text) VALUES (?, ?, ?)", (message_id, user_id, text))
        conn.commit()
        user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    message_data = {
        'id': message_id,
        'sender_id': user_id,
        'username': user['username'],
        'text': text,
        'timestamp': datetime.now().isoformat()
    }
    await sio.emit('new_message', message_data)
    logger.info(f"Nuevo mensaje enviado: {message_data}")

@sio.event
async def get_users(sid):
    await manager.notify_users_update()

@app.get("/", response_class=HTMLResponse)
@app.get("/auth", response_class=HTMLResponse)
async def auth_page():
    return FileResponse("templates/auth.html")

@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    logger.info("Sirviendo chat.html")
    return FileResponse("templates/chat.html")

app.mount("/", socketio.ASGIApp(sio))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)