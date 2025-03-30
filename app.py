import os
import re
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import uuid
import logging
import secrets
from datetime import datetime
from typing import Optional, Dict
from socketio import AsyncServer
from socketio import ASGIApp as SocketIOASGIApp  # Importación explícita para evitar errores
import aiofiles
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de FastAPI y Socket.IO
app = FastAPI()
sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Configuración de rutas y directorios
DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = os.getenv('STATIC_DIR', 'static')
AVATARS_DIR = os.path.join(STATIC_DIR, 'avatars')
POSTS_DIR = os.path.join(STATIC_DIR, 'posts')
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif']

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(POSTS_DIR, exist_ok=True)

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
        self.active_connections: Dict[str, str] = {}
        self.user_info: Dict[str, Dict] = {}

    async def update_presence(self, user_id: str, online: bool):
        user = self.user_info.get(user_id, {})
        await sio.emit(
            'presence_update',
            {
                'user_id': user_id,
                'online': online,
                'name': user.get('name', ''),
                'username': user.get('username', ''),
                'avatar': user.get('avatar', '')
            },
            skip_sid=user.get('sid')
        )
        await self.update_user_count()

    async def connect(self, sid: str, user_id: str, name: str, username: str, avatar: str):
        self.active_connections[sid] = user_id
        self.user_info[user_id] = {'name': name, 'username': username, 'avatar': avatar, 'sid': sid}
        await self.update_presence(user_id, True)

    async def disconnect(self, sid: str):
        if sid in self.active_connections:
            user_id = self.active_connections[sid]
            if user_id in self.user_info:
                del self.user_info[user_id]
            del self.active_connections[sid]
            await self.update_presence(user_id, False)

    async def update_user_count(self):
        with get_db_connection() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        await sio.emit('user_count_update', {'total_users': total_users})

manager = ConnectionManager()

# Base de datos
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            profile_image TEXT DEFAULT '/static/default-avatar.png',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            text TEXT,
            image_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )""")
        conn.commit()

# Contexto lifespan para inicialización
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Guardar imágenes
async def save_image(file_data: Dict, directory: str, filename: str, max_size: int = 800):
    content_type = file_data.get('type')
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Tipo de imagen no permitido")
    contents = file_data.get('data').split(',')[1].encode()
    import base64
    contents = base64.b64decode(contents)
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(400, "La imagen es demasiado grande (máximo 5MB)")
    try:
        image = Image.open(io.BytesIO(contents))
        if max_size:
            image.thumbnail((max_size, max_size))
        file_path = os.path.join(directory, filename)
        image.save(file_path, quality=85)
        return f"/static/{os.path.relpath(file_path, start='static')}"
    except Exception as e:
        logger.error(f"Error procesando imagen: {str(e)}")
        raise HTTPException(500, "Error procesando la imagen")

# Eventos de Socket.IO
@sio.event
async def connect(sid, environ):
    logger.info(f"Cliente conectado: {sid}")
    await manager.update_user_count()

@sio.event
async def disconnect(sid):
    await manager.disconnect(sid)
    logger.info(f"Cliente desconectado: {sid}")

# Resto del código (eventos de Socket.IO y rutas de FastAPI) permanece igual...

# Montaje de Socket.IO
app.mount("/", SocketIOASGIApp(sio))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)