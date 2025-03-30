import os
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
import socketio
from typing import Dict
from datetime import datetime
import uuid
import aiofiles
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
import asyncpg

# Configuración de la base de datos
DATABASE_URL = "postgresql+asyncpg://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Modelos de la base de datos
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    sid = Column(String(100))
    status = Column(String(20), default='online')
    avatar = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    avatar = Column(String(200))

app = FastAPI()

# Configuración de Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio, app)

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Almacenamiento en memoria para conexiones activas
active_connections: Dict[str, WebSocket] = {}
user_rooms = {}

# Eventos de inicio/shutdown
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        # Crear tablas si no existen
        await conn.run_sync(Base.metadata.create_all)

# Rutas HTTP
@app.get("/", response_class=HTMLResponse, methods=["GET", "HEAD"])
async def read_root(request: Request):
    if request.method == "HEAD":
        return HTMLResponse(content="", status_code=200)
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse, methods=["GET", "HEAD"])
async def chat(request: Request):
    if request.method == "HEAD":
        return HTMLResponse(content="", status_code=200)
    return templates.TemplateResponse("chat.html", {"request": request})

# Eventos Socket.IO
@sio.event
async def connect(sid, environ):
    print(f"Cliente conectado: {sid}")

@sio.event
async def disconnect(sid):
    async with AsyncSessionLocal() as session:
        user = await session.execute(
            select(User).where(User.sid == sid)
        )
        user = user.scalar_one_or_none()
        
        if user:
            user.status = 'offline'
            await session.commit()
            await sio.emit('user_disconnected', {'username': user.username})
    
    print(f"Cliente desconectado: {sid}")

@sio.event
async def login(sid, data):
    username = data.get('username')
    if not username:
        return {'status': 'error', 'message': 'Username is required'}
    
    async with AsyncSessionLocal() as session:
        # Verificar si el usuario ya existe
        existing_user = await session.execute(
            select(User).where(User.username == username)
        )
        existing_user = existing_user.scalar_one_or_none()
        
        if existing_user:
            # Actualizar SID y estado
            existing_user.sid = sid
            existing_user.status = 'online'
        else:
            # Crear nuevo usuario
            new_user = User(
                username=username,
                sid=sid,
                status='online',
                avatar=f"https://ui-avatars.com/api/?name={username}&background=random"
            )
            session.add(new_user)
        
        await session.commit()
        
        # Obtener lista de usuarios
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        user_data = {
            'username': username,
            'status': 'online',
            'avatar': f"https://ui-avatars.com/api/?name={username}&background=random"
        }
        
        await sio.emit('user_connected', {
            'username': username,
            'users': [{
                'username': u.username,
                'status': u.status,
                'avatar': u.avatar
            } for u in users]
        })
        
        return {'status': 'success', 'user': user_data}

@sio.event
async def send_message(sid, data):
    message = data.get('message')
    if not message:
        return
    
    async with AsyncSessionLocal() as session:
        user = await session.execute(
            select(User).where(User.sid == sid)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            return
        
        # Guardar mensaje en la base de datos
        new_message = Message(
            sender=user.username,
            message=message,
            avatar=user.avatar
        )
        session.add(new_message)
        await session.commit()
        
        message_data = {
            'id': str(uuid.uuid4()),
            'sender': user.username,
            'message': message,
            'timestamp': datetime.now().isoformat(),
            'avatar': user.avatar
        }
        
        await sio.emit('new_message', message_data)

# Manejo de archivos estáticos
@app.exception_handler(404)
async def custom_404_handler(request: Request, _):
    if request.url.path.startswith('/static/'):
        return FileResponse("static/index.html")
    return templates.TemplateResponse("404.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)