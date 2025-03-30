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
from socketio import AsyncServer, ASGIApp
import aiofiles
from PIL import Image
import io
import uvicorn  # Importar uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')

DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = os.getenv('STATIC_DIR', 'static')
AVATARS_DIR = os.path.join(STATIC_DIR, 'avatars')
POSTS_DIR = os.path.join(STATIC_DIR, 'posts')
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif']

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(POSTS_DIR, exist_ok=True)

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

    async def update_presence(self, user_id: str, online: bool):
        sid = self.user_info.get(user_id, {}).get('sid')
        if online and sid and user_id not in self.user_info:
            self.user_info[user_id] = {'sid': sid}
            self.active_connections[sid] = user_id
            await sio.emit('user_connected', {'user_id': user_id}, broadcast=True, skip_sid=sid) # Emit user connected event
        elif not online and user_id in self.user_info:
            sid_to_remove = self.user_info[user_id]['sid']
            del self.user_info[user_id]
            if sid_to_remove in self.active_connections:
                del self.active_connections[sid_to_remove]
            await sio.emit('user_disconnected', {'user_id': user_id}, broadcast=True) # Emit user disconnected event

manager = ConnectionManager()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@sio.on('connect')
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.on('disconnect')
async def disconnect(sid):
    user_id = manager.active_connections.get(sid)
    if user_id:
        await manager.update_presence(user_id, False)
        logger.info(f"Client disconnected: {sid}, User ID: {user_id}")
    else:
        logger.info(f"Client disconnected: {sid}")

@sio.on('login')
async def login(sid, data):
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        await sio.emit('login_error', {'message': 'Se requieren usuario y contraseña'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            user = conn.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if user:
            user_id = user['id']
            await manager.update_presence(user_id, True)
            token = secrets.token_hex(16)
            await sio.emit('login_success', {'user_id': user_id, 'token': token}, to=sid)
            logger.info(f"User logged in: {username}, ID: {user_id}, SID: {sid}")
        else:
            await sio.emit('login_error', {'message': 'Credenciales inválidas'}, to=sid)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        await sio.emit('login_error', {'message': 'Error al iniciar sesión'}, to=sid)

@sio.on('register')
async def register(sid, data):
    name = data.get('name')
    username = data.get('username')
    password = data.get('password')
    if not name or not username or not password:
        await sio.emit('register_error', {'message': 'Todos los campos son requeridos'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            existing_user = cursor.fetchone()
            if existing_user:
                await sio.emit('register_error', {'message': 'El nombre de usuario ya existe'}, to=sid)
                return
            cursor.execute("INSERT INTO users (name, username, password) VALUES (?, ?, ?)", (name, username, password))
            conn.commit()
            await sio.emit('register_success', {'message': 'Registro exitoso, por favor inicie sesión'}, to=sid)
            logger.info(f"New user registered: {username}")
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        await sio.emit('register_error', {'message': 'Error al registrar usuario'}, to=sid)

@sio.on('set_profile')
async def set_profile(sid, data):
    user_id = manager.active_connections.get(sid)
    name = data.get('name')
    username = data.get('username')
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    if not name or not username:
        await sio.emit('profile_error', {'message': 'Nombre y usuario son requeridos'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET name = ?, username = ? WHERE id = ?", (name, username, user_id))
            conn.commit()
            await sio.emit('profile_updated', {'message': 'Perfil actualizado exitosamente'}, to=sid)
            logger.info(f"Profile updated for user ID: {user_id}, SID: {sid}")
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}")
        await sio.emit('profile_error', {'message': 'Error al actualizar el perfil'}, to=sid)

@sio.on('upload_avatar')
async def upload_avatar(sid, file: str = Form(...), filename: str = Form(...)):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    if not file or not filename:
        await sio.emit('upload_error', {'message': 'Se requiere un archivo'}, to=sid)
        return
    try:
        file_bytes = file.encode('latin-1') # Assuming base64 encoding
        image = Image.open(io.BytesIO(file_bytes))
        image_format = image.format.lower()
        if image_format not in ['jpeg', 'png', 'gif']:
            await sio.emit('upload_error', {'message': 'Formato de imagen no soportado'}, to=sid)
            return
        avatar_filename = f"{user_id}.{image_format}"
        avatar_path = os.path.join(AVATARS_DIR, avatar_filename)
        os.makedirs(AVATARS_DIR, exist_ok=True)
        image.save(avatar_path)
        avatar_url = f"/static/avatars/{avatar_filename}"
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET profile_image = ? WHERE id = ?", (avatar_url, user_id))
            conn.commit()
        await sio.emit('avatar_updated', {'avatar_url': avatar_url}, to=sid)
        logger.info(f"Avatar uploaded for user ID: {user_id}, SID: {sid}")
    except Exception as e:
        logger.error(f"Avatar upload error: {str(e)}")
        await sio.emit('upload_error', {'message': 'Error al subir el avatar'}, to=sid)

@sio.on('delete_account')
async def delete_account(sid):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        await sio.emit('account_deleted', {'message': 'Cuenta eliminada exitosamente'}, to=sid)
    except Exception as e:
        logger.error(f"Error eliminando cuenta: {str(e)}")
        await sio.emit('delete_error', {'message': 'Error al eliminar la cuenta'}, to=sid)

@sio.on('get_users')
async def get_users(sid):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            users = conn.execute("SELECT id, name, username, profile_image FROM users").fetchall()
        users_list = [dict(user) for user in users if user['id'] != user_id]
        for user in users_list:
            user['online'] = user['id'] in manager.user_info
        await sio.emit('users_list', {'users': users_list}, to=sid)
    except Exception as e:
        logger.error(f"Error getting users: {str(e)}")
        await sio.emit('get_users_error', {'message': 'Error al obtener la lista de usuarios'}, to=sid)

@sio.on('user_connected')
async def user_connected(sid, data):
    user_id = data.get('user_id')
    await sio.emit('update_user_presence', {'user_id': user_id, 'online': True}, broadcast=True, skip_sid=sid)

@sio.on('user_disconnected')
async def user_disconnected(sid, data):
    user_id = data.get('user_id')
    await sio.emit('update_user_presence', {'user_id': user_id, 'online': False}, broadcast=True, skip_sid=sid)

@app.get("/")
async def root():
    try:
        return FileResponse("templates/login.html")
    except:
        return HTMLResponse("<html><body><h1>Error</h1><p>No se encontró la página de inicio de sesión</p></body></html>")

@app.get("/chat")
async def chat_page():
    try:
        return FileResponse("templates/chat.html")
    except:
        return HTMLResponse("<html><body><h1>Error</h1><p>No se encontró la página de chat</p></body></html>")

app.mount("/", ASGIApp(sio))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run("app:app", host='0.0.0.0', port=port, reload=True)  # Usar uvicorn para ejecutar la aplicación