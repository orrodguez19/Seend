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

app = FastAPI()
sio = AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Configuración de directorios
DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = 'static'
AVATARS_DIR = os.path.join(STATIC_DIR, 'avatars')
TEMPLATES_DIR = 'templates'

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)

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
        self.active_connections: Dict[str, str] = {}
        self.user_info: Dict[str, Dict] = {}

    async def connect(self, sid: str, user_id: str, username: str):
        self.active_connections[sid] = user_id
        self.user_info[user_id] = {'username': username, 'sid': sid}
        await self.notify_users_update()

    async def disconnect(self, sid: str):
        if sid in self.active_connections:
            user_id = self.active_connections.pop(sid)
            if user_id in self.user_info:
                self.user_info.pop(user_id)
                await self.notify_users_update()

    async def notify_users_update(self):
        user_list = []
        with get_db_connection() as conn:
            users = conn.execute("SELECT id, username FROM users").fetchall()
            for user in users:
                user_list.append({
                    'id': user['id'],
                    'username': user['username'],
                    'online': user['id'] in self.user_info
                })
        await sio.emit('users_updated', {'users': user_list})

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
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id TEXT NOT NULL,
            text TEXT,
            image_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )""")
        conn.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Guardar imágenes
async def save_image(file_data: bytes, directory: str, filename: str, max_size: int = 800):
    try:
        image = Image.open(io.BytesIO(file_data))
        image.thumbnail((max_size, max_size))
        file_path = os.path.join(directory, filename)
        image.save(file_path, quality=85)
        return f"/static/avatars/{filename}"
    except Exception as e:
        logger.error(f"Error procesando imagen: {str(e)}")
        raise HTTPException(500, "Error procesando la imagen")

# Rutas HTTP para autenticación
@app.post("/api/login")
async def login_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    with get_db_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        
        if not user:
            return JSONResponse(
                status_code=400,
                content={"detail": "Usuario o contraseña incorrectos"}
            )
        
        session_id = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))",
            (session_id, user['id'])
        )
        conn.commit()
        
        response = JSONResponse(
            status_code=200,
            content={"message": "Inicio de sesión exitoso"}
        )
        response.set_cookie(
            key="access_token",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,
            path="/",
            samesite="Lax"
        )
        return response

@app.post("/api/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    if not username or len(username) < 3 or len(password) < 6:
        return JSONResponse(
            status_code=400,
            content={"detail": "Usuario debe tener al menos 3 caracteres y contraseña 6 caracteres"}
        )
    
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            return JSONResponse(
                status_code=400,
                content={"detail": "El usuario ya existe"}
            )
        
        user_id = str(uuid.uuid4())
        session_id = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO users (id, username, password) VALUES (?, ?, ?)",
            (user_id, username, password)
        )
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))",
            (session_id, user_id)
        )
        conn.commit()
        
        response = JSONResponse(
            status_code=200,
            content={"message": "Registro exitoso"}
        )
        response.set_cookie(
            key="access_token",
            value=session_id,
            httponly=True,
            max_age=30*24*60*60,
            path="/",
            samesite="Lax"
        )
        return response

# Eventos de Socket.IO
@sio.event
async def connect(sid, environ):
    try:
        cookies = environ.get('HTTP_COOKIE', '')
        session_id = None
        for cookie in cookies.split(';'):
            if 'access_token' in cookie.strip():
                session_id = cookie.split('=')[1].strip()
                break
        
        if not session_id:
            raise ConnectionRefusedError('No autenticado')
        
        with get_db_connection() as conn:
            session = conn.execute("""
                SELECT u.id, u.username 
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_id = ? AND s.expires_at > datetime('now')
            """, (session_id,)).fetchone()
            
            if not session:
                raise ConnectionRefusedError('Sesión expirada o inválida')
            
            await manager.connect(sid, session['id'], session['username'])
            await sio.emit('user_ready', {'username': session['username'], 'id': session['id']}, to=sid)
            logger.info(f"Cliente autenticado conectado: {sid}")
            
    except Exception as e:
        logger.error(f"Error de conexión: {str(e)}")
        raise ConnectionRefusedError('Autenticación fallida')

@sio.event
async def disconnect(sid):
    await manager.disconnect(sid)
    logger.info(f"Cliente desconectado: {sid}")

@sio.event
async def send_message(sid, data):
    user_id = manager.active_connections.get(sid)
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
    # Verificar cookie de acceso
    access_token = request.cookies.get("access_token")
    if not access_token:
        return RedirectResponse(url="/")
    
    with get_db_connection() as conn:
        session = conn.execute("""
            SELECT 1 FROM sessions 
            WHERE session_id = ? AND expires_at > datetime('now')
        """, (access_token,)).fetchone()
        
        if not session:
            response = RedirectResponse(url="/")
            response.delete_cookie("access_token")
            return response
    
    return FileResponse("templates/chat.html")

# Montar la aplicación de Socket.IO
app.mount("/", socketio.ASGIApp(sio))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)