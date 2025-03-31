from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import os
import asyncpg
from datetime import datetime
import uuid
from contextlib import asynccontextmanager

# Configuración de la aplicación
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de PostgreSQL
DATABASE_URL = "postgresql://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend"

# Conexión a la base de datos
async def get_db_connection():
    conn = await asyncpg.connect(DATABASE_URL)
    return conn

# Inicialización de la base de datos
async def init_db():
    conn = await get_db_connection()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                bio TEXT DEFAULT 'Usuario nuevo'
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT NOW(),
                status TEXT DEFAULT 'sent',
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id)
            )
        ''')
    finally:
        await conn.close()

# Manejo de conexiones WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)

manager = ConnectionManager()

# Evento de inicio
@app.on_event("startup")
async def startup_event():
    await init_db()

# Rutas principales
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if "user_id" not in request.session:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("chat.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request):
    form_data = await request.form()
    action = form_data.get("action")
    username = form_data.get("username")
    password = form_data.get("password")
    
    conn = await get_db_connection()
    try:
        if action == "login":
            user = await conn.fetchrow(
                "SELECT id, username FROM users WHERE username = $1 AND password = $2",
                username, password
            )
            if user:
                request.session["user_id"] = user["id"]
                request.session["username"] = user["username"]
                return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            else:
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "Credenciales incorrectas"}
                )
        
        elif action == "register":
            email = form_data.get("email")
            try:
                user = await conn.fetchrow(
                    "INSERT INTO users (username, password, email) VALUES ($1, $2, $3) RETURNING id, username",
                    username, password, email
                )
                request.session["user_id"] = user["id"]
                request.session["username"] = user["username"]
                return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            except asyncpg.UniqueViolationError:
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "El usuario ya existe"}
                )
    finally:
        await conn.close()

# API para obtener usuarios
@app.get("/api/users")
async def get_users(request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    conn = await get_db_connection()
    try:
        users = await conn.fetch("SELECT id, username, email, bio FROM users")
        return [
            {
                "id": user["id"],
                "name": user["username"],
                "email": user["email"],
                "bio": user["bio"],
                "lastSeen": "En línea",
                "isOnline": True
            }
            for user in users
        ]
    finally:
        await conn.close()

# API para obtener mensajes
@app.get("/api/messages/{receiver_id}")
async def get_messages(receiver_id: int, request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    conn = await get_db_connection()
    try:
        messages = await conn.fetch(
            """
            SELECT sender_id, receiver_id, text, timestamp, status 
            FROM messages 
            WHERE (sender_id = $1 AND receiver_id = $2) OR (sender_id = $2 AND receiver_id = $1) 
            ORDER BY timestamp
            """,
            request.session["user_id"], receiver_id
        )
        return [
            {
                "sender_id": msg["sender_id"],
                "receiver_id": msg["receiver_id"],
                "text": msg["text"],
                "timestamp": msg["timestamp"].isoformat(),
                "status": msg["status"]
            }
            for msg in messages
        ]
    finally:
        await conn.close()

# Ruta para cerrar sesión
@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

# WebSocket para mensajes en tiempo real
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            sender_id = data.get("sender_id")
            receiver_id = data.get("receiver_id")
            text = data.get("text")
            timestamp = data.get("timestamp")
            
            # Guardar mensaje en la base de datos
            conn = await get_db_connection()
            try:
                await conn.execute(
                    "INSERT INTO messages (sender_id, receiver_id, text, timestamp) VALUES ($1, $2, $3, $4)",
                    sender_id, receiver_id, text, timestamp
                )
                
                # Enviar mensaje al receptor y al remitente
                message = {
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "text": text,
                    "timestamp": timestamp,
                    "status": "sent"
                }
                await manager.send_personal_message(message, receiver_id)
                await manager.send_personal_message(message, sender_id)
            finally:
                await conn.close()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)