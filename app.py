import os
import re
import socketio
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
import sqlite3
import uuid
import logging
import secrets
from datetime import datetime
from typing import Optional, Dict
from socketio import AsyncServer
from contextlib import asynccontextmanager
import aiofiles
from PIL import Image
import io
import base64

# Configuración inicial
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de directorios
DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = 'static'
AVATARS_DIR = os.path.join(STATIC_DIR, 'avatars')
TEMPLATES_DIR = 'templates'

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)

# Función para obtener la conexión a la base de datos
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Función para crear las tablas si no existen
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id INTEGER NOT NULL,
            text TEXT,
            image_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

# Crear las tablas al inicio de la aplicación
create_tables()

app = FastAPI()
sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Configuración de templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Montaje de archivos estáticos
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gestión de conexiones
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, str] = {} # session_token: user_id
        self.user_info: Dict[str, Dict] = {} # user_id: {'username': ..., 'sid': ...}

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

    async def get_user_id_by_session_token(self, session_token: str) -> Optional[str]:
        return self.active_connections.get(session_token)

    async def notify_users_update(self):
        user_list = []
        with get_db_connection() as conn:
            users = conn.execute("SELECT id, username FROM users").fetchall()
            for user in users:
                is_online = user['id'] in self.user_info
                user_list.append({
                    'id': user['id'],
                    'username': user['username'],
                    'online': is_online
                })
        await sio.emit('users_updated', {'users': user_list})

manager = ConnectionManager()

async def save_image(image_data: bytes, directory: str, filename: str) -> str:
    filepath = os.path.join(directory, filename)
    async with aiofiles.open(filepath, 'wb') as f:
        await f.write(image_data)
    return f"/static/avatars/{filename}"

@app.post("/api/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    if len(username) < 3 or len(password) < 6:
        raise HTTPException(status_code=400, detail="El nombre de usuario debe tener al menos 3 caracteres y la contraseña al menos 6.")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing_user = cursor.fetchone()
        if existing_user:
            raise HTTPException(status_code=400, detail="El nombre de usuario ya existe.")
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return {"message": "Usuario registrado exitosamente."}

@app.post("/api/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_db_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if not user:
            return JSONResponse(status_code=400, content={"detail": "Usuario o contraseña incorrectos"})

        session_token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))", (session_token, user['id']))
        conn.commit()

        return JSONResponse(content={"message": "Inicio de sesión exitoso", "session_token": session_token})

@sio.event
async def connect(sid, environ, auth):
    try:
        session_token = auth.get('session_id')
        if not session_token:
            raise ConnectionRefusedError('No autenticado: Token de sesión no proporcionado')

        with get_db_connection() as conn:
            session = conn.execute("""
                SELECT u.id, u.username
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_id = ? AND s.expires_at > datetime('now')
            """, (session_token,)).fetchone()

            if not session:
                raise ConnectionRefusedError('No autenticado: Sesión inválida o expirada')

            await manager.connect(sid, session['id'], session['username'], session_token)
            await sio.emit('user_ready', {'username': session['username'], 'id': session['id']}, to=sid)
            logger.info(f"Cliente autenticado conectado: {sid}")

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
    image_path = None

    if 'image' in data:
        try:
            image_data = data['image'].split(',')[1].encode()
            image_data = base64.b64decode(image_data)
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
            image_path = await save_image(image_data, AVATARS_DIR, filename)
        except Exception as e:
            logger.error(f"Error procesando imagen: {str(e)}")
            await sio.emit('error', {'message': 'Error al procesar la imagen'}, to=sid)
            return

    message_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute("INSERT INTO messages (id, sender_id, text, image_path) VALUES (?, ?, ?, ?)",
                    (message_id, user_id, text, image_path))
        conn.commit()

    with get_db_connection() as conn:
        user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()

    message_data = {
        'id': message_id,
        'sender_id': user_id,
        'username': user['username'],
        'text': text,
        'image_path': image_path,
        'timestamp': datetime.now().isoformat()
    }

    await sio.emit('new_message', message_data)

@sio.event
async def get_history(sid):
    with get_db_connection() as conn:
        messages = conn.execute("""
            SELECT m.id, m.text, m.image_path, m.created_at as timestamp,
                   u.username, u.id as sender_id
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            ORDER BY m.created_at DESC
            LIMIT 50
        """).fetchall()

        messages_sorted = sorted([dict(msg) for msg in messages], key=lambda x: x['timestamp'])
        await sio.emit('history', {'messages': messages_sorted}, to=sid)

@sio.event
async def get_users(sid):
    await manager.notify_users_update()

# Rutas de FastAPI
@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("templates/login.html")

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return FileResponse("templates/login.html")

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return FileResponse("templates/chat.html")

# Montar la aplicación de Socket.IO
app.mount("/", socketio.ASGIApp(sio))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
