import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
import secrets
from fastapi.templating import Jinja2Templates

# Configuración inicial
app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
Base = declarative_base()

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de la base de datos ASÍNCRONA
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend")
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Modelos
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)
    password_hash = Column(String(200))
    sid = Column(String(100))
    status = Column(String(20), default='offline')
    last_seen = Column(DateTime)
    avatar = Column(String(200))

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    sender = Column(String(50))
    recipient = Column(String(50))
    content = Column(Text)
    status = Column(String(20), default='sent')  # sent, delivered, read
    timestamp = Column(DateTime, default=datetime.utcnow)

# Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio, app)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

templates = Jinja2Templates(directory="templates")

# Rutas HTTP
@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat")
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/api/register")
async def register(request: Request):
    data = await request.json()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == data['username']))
        if result.scalar():
            raise HTTPException(status_code=400, detail="Username already exists")

        user = User(
            username=data['username'],
            password_hash=pwd_context.hash(data['password']),
            avatar=f"https://ui-avatars.com/api/?name={data['username']}"
        )
        db.add(user)
        await db.commit()
        return {"status": "success"}

@app.post("/api/login")
async def login(request: Request, response: Response):
    data = await request.json()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == data['username']))
        user = result.scalar()

        if not user or not pwd_context.verify(data['password'], user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        session_token = secrets.token_urlsafe(32)
        user.sid = session_token
        user.status = 'online'
        user.last_seen = datetime.utcnow()
        await db.commit()

        response.set_cookie("session_token", session_token, httponly=True)
        return {
            "user": {
                "username": user.username,
                "avatar": user.avatar
            }
        }

@app.get("/api/check_session")
async def check_session(session_token: str = Cookie(None)):
    if not session_token:
        return {"status": "invalid"}

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == session_token))
        user = result.scalar()
        if not user:
            return {"status": "invalid"}

        return {
            "status": "valid",
            "user": {
                "username": user.username,
                "avatar": user.avatar
            }
        }

# Eventos Socket.IO
@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        user = result.scalar()
        if user:
            user.status = 'offline'
            user.sid = None
            await db.commit()
            await sio.emit('user_status', {
                'username': user.username,
                'status': 'offline'
            })

@sio.event
async def typing_start(sid):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        user = result.scalar()
        if user:
            user.status = 'typing'
            await db.commit()
            await sio.emit('user_status', {
                'username': user.username,
                'status': 'typing'
            })

@sio.event
async def typing_stop(sid):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        user = result.scalar()
        if user:
            user.status = 'online'
            await db.commit()
            await sio.emit('user_status', {
                'username': user.username,
                'status': 'online'
            })

@sio.event
async def send_message(sid, data):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        sender = result.scalar()
        if not sender:
            return

        message = Message(
            sender=sender.username,
            recipient=data['recipient'],
            content=data['message'],
            status='sent'
        )
        db.add(message)
        await db.commit()

        # Enviar al remitente
        await sio.emit('new_message', {
            'id': message.id,
            'sender': sender.username,
            'message': data['message'],
            'timestamp': message.timestamp.isoformat(),
            'status': 'sent',
            'is_own': True
        }, room=sid)

        # Enviar al destinatario si está conectado
        result = await db.execute(select(User).where(User.username == data['recipient']))
        recipient = result.scalar()
        if recipient and recipient.sid:
            message.status = 'delivered'
            await db.commit()
            await sio.emit('new_message', {
                'id': message.id,
                'sender': sender.username,
                'message': data['message'],
                'timestamp': message.timestamp.isoformat(),
                'status': 'delivered',
                'is_own': False
            }, room=recipient.sid)
            await sio.emit('message_status', {
                'message_id': message.id,
                'status': 'delivered'
            }, room=sid)

@sio.event
async def mark_as_read(sid, data):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Message).where(Message.id == data['message_id']))
        message = result.scalar()
        if message:
            message.status = 'read'
            await db.commit()
            result = await db.execute(select(User).where(User.username == message.sender))
            sender = result.scalar()
            if sender and sender.sid:
                await sio.emit('message_status', {
                    'message_id': message.id,
                    'status': 'read'
                }, room=sender.sid)

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
