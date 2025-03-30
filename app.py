import os
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import socketio
from typing import Dict, Optional
from datetime import datetime
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, select, delete
from sqlalchemy.ext.declarative import declarative_base
import asyncpg
from passlib.context import CryptContext
from pydantic import BaseModel

# Configuración de seguridad
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Modelos Pydantic
class UserCreate(BaseModel):
    name: str
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# Configuración DB
DATABASE_URL = "postgresql+asyncpg://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Modelos DB
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200))
    sid = Column(String(100))
    status = Column(String(20), default='online')
    avatar = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_public = Column(Boolean, default=True)

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(50), nullable=False)
    recipient = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    avatar = Column(String(200))
    is_temporary = Column(Boolean, default=True)

class RecentChat(Base):
    __tablename__ = 'recent_chats'
    id = Column(Integer, primary_key=True)
    user_username = Column(String(50), ForeignKey('users.username'))
    contact_username = Column(String(50))
    last_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

app = FastAPI()

# Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio, app)

# Archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Helpers
async def get_user(username: str) -> Optional[User]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

async def update_recent_chat(session, user_username: str, contact_username: str, message: str):
    await session.execute(
        delete(RecentChat)
        .where(RecentChat.user_username == user_username)
        .where(RecentChat.contact_username == contact_username)
    )
    new_chat = RecentChat(
        user_username=user_username,
        contact_username=contact_username,
        last_message=message
    )
    session.add(new_chat)

# Eventos de inicio
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Rutas HTTP
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/register")
async def register(user_data: UserCreate):
    async with AsyncSessionLocal() as session:
        existing_user = await get_user(user_data.username)
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        new_user = User(
            name=user_data.name,
            username=user_data.username,
            password_hash=pwd_context.hash(user_data.password),
            avatar=f"https://ui-avatars.com/api/?name={user_data.username}&background=random"
        )
        session.add(new_user)
        await session.commit()
        return {"message": "User registered successfully"}

@app.post("/login")
async def login(user_data: UserLogin):
    user = await get_user(user_data.username)
    if not user or not pwd_context.verify(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful", "username": user.username}

@app.get("/public-users")
async def get_public_users():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.is_public == True))
        users = result.scalars().all()
        return [{
            "username": user.username,
            "name": user.name or user.username,
            "avatar": user.avatar
        } for user in users]

@app.get("/recent-chats/{username}")
async def get_recent_chats(username: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RecentChat)
            .where(RecentChat.user_username == username)
            .order_by(RecentChat.timestamp.desc())
            .limit(20)
        )
        chats = result.scalars().all()
        return [{
            "contact_username": chat.contact_username,
            "last_message": chat.last_message,
            "timestamp": chat.timestamp.isoformat()
        } for chat in chats]

# Eventos Socket.IO
@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.sid == sid))
        user = user.scalar_one_or_none()
        if user:
            user.status = 'offline'
            await session.commit()

@sio.event
async def login_socket(sid, data):
    username = data.get('username')
    if not username:
        return {'status': 'error', 'message': 'Username required'}
    
    async with AsyncSessionLocal() as session:
        user = await get_user(username)
        if not user:
            return {'status': 'error', 'message': 'User not found'}
        
        user.sid = sid
        user.status = 'online'
        await session.commit()
        
        return {'status': 'success', 'user': {
            'username': user.username,
            'name': user.name,
            'avatar': user.avatar
        }}

@sio.event
async def send_message(sid, data):
    async with AsyncSessionLocal() as session:
        # Verificar usuario remitente
        sender = await session.execute(select(User).where(User.sid == sid))
        sender = sender.scalar_one_or_none()
        if not sender:
            return
        
        # Crear mensaje temporal
        new_message = Message(
            sender=sender.username,
            recipient=data['recipient'],
            message=data['message'],
            avatar=sender.avatar,
            is_temporary=True
        )
        session.add(new_message)
        await session.commit()
        
        # Enviar mensaje
        message_data = {
            'id': str(uuid.uuid4()),
            'sender': sender.username,
            'message': data['message'],
            'timestamp': datetime.now().isoformat(),
            'avatar': sender.avatar
        }
        await sio.emit('new_message', message_data, room=data['recipient'])
        
        # Actualizar chat reciente
        await update_recent_chat(session, sender.username, data['recipient'], data['message'])
        await update_recent_chat(session, data['recipient'], sender.username, data['message'])
        await session.commit()
        
        # Eliminar mensaje después de enviar
        await session.execute(delete(Message).where(Message.id == new_message.id))
        await session.commit()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)