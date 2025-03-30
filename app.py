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
        user = self.user_info.get(user_id, {})
        await sio.emit('presence_update', {
            'user_id': user_id,
            'online': online,
            'name': user.get('name', ''),
            'username': user.get('username', ''),
            'avatar': user.get('avatar', '')
        }, skip_sid=user.get('sid'))
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

@app.on_event("startup")
def startup():
    init_db()

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

@sio.event
async def connect(sid, environ):
    logger.info(f"Cliente conectado: {sid}")
    await manager.update_user_count()

@sio.event
async def disconnect(sid):
    await manager.disconnect(sid)
    logger.info(f"Cliente desconectado: {sid}")

@sio.event
async def check_username(sid, data):
    username = data.get('username', '').lower().strip()
    if not re.match(r'^@[a-z0-9_]{3,20}$', username):
        await sio.emit('username_status', {
            'available': False,
            'message': 'Formato inválido. Debe ser @ seguido de 3-20 letras, números o _'
        }, to=sid)
        return
    with get_db_connection() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    await sio.emit('username_status', {
        'available': not exists,
        'username': username,
        'message': 'Disponible' if not exists else 'Este usuario ya existe'
    }, to=sid)

@sio.event
async def register(sid, data):
    name = data.get('name', '').strip()
    username = data.get('username', '').lower().strip()
    password = data.get('password', '')
    if not name or len(name) > 30:
        await sio.emit('register_error', {'message': 'Nombre inválido (máximo 30 caracteres)'}, to=sid)
        return
    if not re.match(r'^@[a-z0-9_]{3,20}$', username):
        await sio.emit('register_error', {'message': 'Usuario inválido. Debe ser @ seguido de 3-20 letras, números o _'}, to=sid)
        return
    if len(password) < 6:
        await sio.emit('register_error', {'message': 'La contraseña debe tener al menos 6 caracteres'}, to=sid)
        return
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            await sio.emit('register_error', {'message': 'El usuario ya existe'}, to=sid)
            return
        user_id = str(uuid.uuid4())
        session_id = secrets.token_hex(32)
        conn.execute("INSERT INTO users (id, name, username, password) VALUES (?, ?, ?, ?)", (user_id, name, username, password))
        conn.execute("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))", (session_id, user_id))
        conn.commit()
        await manager.connect(sid, user_id, name, username, '/static/default-avatar.png')
        await sio.emit('registered', {
            'session_id': session_id,
            'user_id': user_id,
            'name': name,
            'username': username,
            'profile_image': '/static/default-avatar.png'
        }, to=sid)

@sio.event
async def login(sid, data):
    username = data.get('username', '').lower().strip()
    password = data.get('password', '')
    with get_db_connection() as conn:
        user = conn.execute("SELECT id, name, profile_image FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        if not user:
            await sio.emit('login_error', {'message': 'Usuario o contraseña incorrectos'}, to=sid)
            return
        session_id = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))", (session_id, user['id']))
        conn.commit()
        await manager.connect(sid, user['id'], user['name'], username, user['profile_image'])
        await sio.emit('logged_in', {
            'session_id': session_id,
            'user_id': user['id'],
            'name': user['name'],
            'username': username,
            'profile_image': user['profile_image']
        }, to=sid)

@sio.event
async def update_avatar(sid, data):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    try:
        file_data = data.get('file')
        if not file_data or not file_data.get('type', '').startswith('image/'):
            await sio.emit('avatar_error', {'message': 'Archivo de imagen inválido'}, to=sid)
            return
        filename = f"{user_id}.jpg"
        image_path = await save_image(file_data, AVATARS_DIR, filename, max_size=500)
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET profile_image = ? WHERE id = ?", (image_path, user_id))
            conn.commit()
            manager.user_info[user_id]['avatar'] = image_path
            await sio.emit('avatar_updated', {'user_id': user_id, 'profile_image': image_path})
    except HTTPException as e:
        await sio.emit('avatar_error', {'message': e.detail}, to=sid)

@sio.event
async def update_profile(sid, data):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    field = data.get('field')
    value = data.get('value')
    if field not in ['name', 'username', 'bio']:
        await sio.emit('profile_error', {'message': 'Campo inválido'}, to=sid)
        return
    with get_db_connection() as conn:
        if field == 'username' and not re.match(r'^@[a-z0-9_]{3,20}$', value):
            await sio.emit('profile_error', {'message': 'Usuario inválido'}, to=sid)
            return
        conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
        conn.commit()
        manager.user_info[user_id][field] = value
        await sio.emit('profile_updated', {'user_id': user_id, field: value})

@sio.event
async def create_post(sid, data):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    text = data.get('text', '').strip()
    file_data = data.get('file')
    if not text and not file_data:
        await sio.emit('post_error', {'message': 'Debes incluir texto o una imagen'}, to=sid)
        return
    try:
        image_path = None
        if file_data:
            filename = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
            image_path = await save_image(file_data, POSTS_DIR, filename, max_size=1200)
        post_id = str(uuid.uuid4())
        with get_db_connection() as conn:
            conn.execute("INSERT INTO posts (id, user_id, text, image_path) VALUES (?, ?, ?, ?)", (post_id, user_id, text, image_path))
            post = conn.execute("SELECT p.*, u.name, u.username, u.profile_image FROM posts p JOIN users u ON p.user_id = u.id WHERE p.id = ?", (post_id,)).fetchone()
            conn.commit()
        post_data = dict(post)
        post_data['created_at'] = post['created_at']
        await sio.emit('new_post', post_data)
    except HTTPException as e:
        await sio.emit('post_error', {'message': e.detail}, to=sid)

@sio.event
async def send_message(sid, data):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    receiver_id = data.get('receiver_id')
    text = data.get('text', '').strip()
    if not receiver_id or not text:
        await sio.emit('message_error', {'message': 'Faltan datos'}, to=sid)
        return
    message_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute("INSERT INTO messages (id, sender_id, receiver_id, text) VALUES (?, ?, ?, ?)", (message_id, user_id, receiver_id, text))
        message = conn.execute("SELECT m.*, u.name, u.username FROM messages m JOIN users u ON m.sender_id = u.id WHERE m.id = ?", (message_id,)).fetchone()
        conn.commit()
    message_data = dict(message)
    message_data['created_at'] = message['created_at']
    await sio.emit('new_message', message_data, room=receiver_id)
    await sio.emit('new_message', message_data, to=sid)

@sio.event
async def delete_account(sid):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to=sid)
        return
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM messages WHERE sender_id = ? OR receiver_id = ?", (user_id, user_id))
            conn.execute("DELETE FROM posts WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        await manager.disconnect(sid)
        await sio.emit('account_deleted', {'message': 'Cuenta eliminada exitosamente'}, to=sid)
    except Exception as e:
        logger.error(f"Error eliminando cuenta: {str(e)}")
        await sio.emit('delete_error', {'message': 'Error al eliminar la cuenta'}, to:sid)

@sio.event
async def get_users(sid):
    user_id = manager.active_connections.get(sid)
    if not user_id:
        await sio.emit('auth_error', {'message': 'No autenticado'}, to:sid)
        return
    with get_db_connection() as conn:
        users = conn.execute("SELECT id, name, username, profile_image FROM users").fetchall()
    users_list = [dict(user) for user in users if user['id'] != user_id]
    for user in users_list:
        user['online'] = user['id'] in manager.user_info
    await sio.emit('users_list', {'users': users_list}, to:sid)

@app.get("/")
async def root():
    return RedirectResponse(url="/chat")

@app.get("/chat")
async def chat_page():
    try:
        return FileResponse("templates/chat.html")
    except:
        return HTMLResponse("<html><body><h1>Error</h1><p>No se encontró la página de chat</p></body></html>")

app.mount("/", ASGIApp(sio))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run("app:app", reload=True, host='0.0.0.0', port=port)  # Usar uvicorn para ejecutar la aplicación