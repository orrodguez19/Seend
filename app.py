import os
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import socketio
from typing import Dict, Optional
from datetime import datetime
import uuid
import aiofiles
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, Text, select
from sqlalchemy.ext.declarative import declarative_base
import asyncpg
from passlib.context import CryptContext
from pydantic import BaseModel

# Configuración de seguridad
security = HTTPBasic()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Modelos Pydantic para validación
class UserCreate(BaseModel):
    name: str
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# Configuración de la base de datos
DATABASE_URL = "postgresql+asyncpg://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Modelos de la base de datos
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

# Funciones de ayuda
def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str):
    return pwd_context.hash(password)

async def get_user(username: str) -> Optional[User]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

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

# Endpoints de autenticación
@app.post("/register")
async def register(user_data: UserCreate):
    async with AsyncSessionLocal() as session:
        # Verificar si el usuario ya existe
        existing_user = await get_user(user_data.username)
        if existing_user:
            raise HTTPException(status_code=400, detail="El nombre de usuario ya está en uso")
        
        # Crear nuevo usuario
        new_user = User(
            name=user_data.name,
            username=user_data.username,
            password_hash=get_password_hash(user_data.password),
            avatar=f"https://ui-avatars.com/api/?name={user_data.username}&background=random"
        )
        session.add(new_user)
        await session.commit()
        
        return {"message": "Usuario registrado exitosamente"}

@app.post("/login")
async def login(user_data: UserLogin):
    user = await get_user(user_data.username)
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    return {"message": "Inicio de sesión exitoso", "username": user.username}

# Eventos Socket.IO
@sio.event
async def connect(sid, environ):
    print(f"Cliente conectado: {sid}")

@sio.event
async def disconnect(sid):
    async with AsyncSessionLocal() as session:
        user = await session.execute(select(User).where(User.sid == sid))
        user = user.scalar_one_or_none()
        
        if user:
            user.status = 'offline'
            await session.commit()
            await sio.emit('user_disconnected', {'username': user.username})
    
    print(f"Cliente desconectado: {sid}")

@sio.event
async def login_socket(sid, data):
    username = data.get('username')
    if not username:
        return {'status': 'error', 'message': 'Username is required'}
    
    async with AsyncSessionLocal() as session:
        user = await get_user(username)
        if not user:
            return {'status': 'error', 'message': 'Usuario no encontrado'}
        
        # Actualizar SID y estado
        user.sid = sid
        user.status = 'online'
        await session.commit()
        
        # Obtener lista de usuarios
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        user_data = {
            'username': user.username,
            'status': user.status,
            'avatar': user.avatar
        }
        
        await sio.emit('user_connected', {
            'username': user.username,
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
        user = await session.execute(select(User).where(User.sid == sid))
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

# Manejo de errores
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# Manejo de archivos estáticos
@app.exception_handler(404)
async def custom_404_handler(request: Request, _):
    if request.url.path.startswith('/static/'):
        return FileResponse("static/index.html")
    return templates.TemplateResponse("404.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)