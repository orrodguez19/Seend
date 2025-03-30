import os
from fastapi import FastAPI, Request, HTTPException, Depends, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import socketio
from typing import Dict, Optional
from datetime import datetime, timedelta
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, select, delete, update
from sqlalchemy.ext.declarative import declarative_base
import asyncpg
from passlib.context import CryptContext
from pydantic import BaseModel
import secrets
from fastapi.middleware.cors import CORSMiddleware

# Configuración inicial
app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configura CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/seend")
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Modelos
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

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey('users.id'))
    receiver_id = Column(Integer, ForeignKey('users.id'))
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    read = Column(Boolean, default=False)

class RecentChat(Base):
    __tablename__ = 'recent_chats'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    contact_id = Column(Integer, ForeignKey('users.id'))
    last_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio, app)

# Helpers
async def get_user(username: str) -> Optional[User]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

async def update_recent_chat(user_id: int, contact_id: int, message: str):
    async with AsyncSessionLocal() as session:
        # Elimina chat existente si existe
        await session.execute(
            delete(RecentChat)
            .where(RecentChat.user_id == user_id)
            .where(RecentChat.contact_id == contact_id)
        )
        
        # Crea nuevo chat reciente
        new_chat = RecentChat(
            user_id=user_id,
            contact_id=contact_id,
            last_message=message,
            timestamp=datetime.utcnow()
        )
        session.add(new_chat)
        await session.commit()

# Eventos de inicio
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Rutas HTTP
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return FileResponse("templates/login.html")

@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return FileResponse("templates/chat.html")

@app.post("/register")
async def register(request: Request):
    data = await request.json()
    async with AsyncSessionLocal() as session:
        existing_user = await get_user(data['username'])
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        new_user = User(
            name=data['name'],
            username=data['username'],
            password_hash=pwd_context.hash(data['password']),
            avatar=f"https://ui-avatars.com/api/?name={data['username']}&background=random"
        )
        session.add(new_user)
        await session.commit()
        return {"message": "User registered successfully"}

@app.post("/login")
async def login(request: Request, response: Response):
    data = await request.json()
    user = await get_user(data['username'])
    if not user or not pwd_context.verify(data['password'], user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_token = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as session:
        user.sid = session_token
        user.status = 'online'
        await session.commit()
    
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=86400,
        secure=False,
        samesite="lax"
    )
    
    await sio.emit("user_connected", {"username": user.username})
    return {
        "message": "Login successful",
        "user": {
            "username": user.username,
            "name": user.name,
            "avatar": user.avatar
        }
    }

@app.get("/check-session")
async def check_session(session_token: Optional[str] = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")
    
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.sid == session_token))
        user = user.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        return {
            "username": user.username,
            "name": user.name,
            "avatar": user.avatar
        }

@app.get("/recent-chats/{username}")
async def get_recent_chats(username: str):
    async with AsyncSessionLocal() as session:
        user = await get_user(username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        result = await session.execute(
            select(RecentChat, User.username, User.name, User.avatar)
            .join(User, RecentChat.contact_id == User.id)
            .where(RecentChat.user_id == user.id)
            .order_by(RecentChat.timestamp.desc())
        )
        
        chats = result.all()
        return [{
            "contact_username": contact_username,
            "contact_name": contact_name,
            "last_message": last_message,
            "timestamp": timestamp.isoformat(),
            "avatar": avatar
        } for _, contact_username, contact_name, avatar, last_message, timestamp in chats]

@app.get("/public-users")
async def get_public_users():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        return [{
            "username": user.username,
            "name": user.name,
            "avatar": user.avatar,
            "status": user.status
        } for user in users]

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
            await sio.emit("user_disconnected", {"username": user.username})

@sio.event
async def send_message(sid, data):
    async with AsyncSessionLocal() as session:
        sender = await session.execute(select(User).where(User.sid == sid))
        sender = sender.scalar_one_or_none()
        if not sender:
            return
        
        receiver = await get_user(data['recipient'])
        if not receiver:
            return
        
        new_message = Message(
            sender_id=sender.id,
            receiver_id=receiver.id,
            content=data['message']
        )
        session.add(new_message)
        await session.commit()
        
        message_data = {
            'sender': sender.username,
            'recipient': receiver.username,
            'message': data['message'],
            'timestamp': datetime.utcnow().isoformat(),
            'avatar': sender.avatar
        }
        
        await sio.emit('new_message', message_data, room=receiver.sid)
        await update_recent_chat(sender.id, receiver.id, data['message'])
        await update_recent_chat(receiver.id, sender.id, data['message'])

# Configuración de archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))