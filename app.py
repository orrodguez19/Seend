import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
import secrets
import asyncpg

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

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/seend")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    Base.metadata.create_all(bind=engine)

# Rutas HTTP
@app.get("/")
async def root():
    return FileResponse("static/login.html")

@app.get("/chat")
async def chat_page():
    return FileResponse("static/chat.html")

@app.post("/api/register")
async def register(request: Request):
    data = await request.json()
    db = SessionLocal()
    if db.query(User).filter(User.username == data['username']).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    
    user = User(
        username=data['username'],
        password_hash=pwd_context.hash(data['password']),
        avatar=f"https://ui-avatars.com/api/?name={data['username']}"
    )
    db.add(user)
    db.commit()
    return {"status": "success"}

@app.post("/api/login")
async def login(request: Request, response: Response):
    data = await request.json()
    db = SessionLocal()
    user = db.query(User).filter(User.username == data['username']).first()
    
    if not user or not pwd_context.verify(data['password'], user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    session_token = secrets.token_urlsafe(32)
    user.sid = session_token
    user.status = 'online'
    user.last_seen = datetime.utcnow()
    db.commit()
    
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
    
    db = SessionLocal()
    user = db.query(User).filter(User.sid == session_token).first()
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
    db = SessionLocal()
    user = db.query(User).filter(User.sid == sid).first()
    if user:
        user.status = 'offline'
        user.sid = None
        db.commit()
        await sio.emit('user_status', {
            'username': user.username,
            'status': 'offline'
        })

@sio.event
async def typing_start(sid):
    db = SessionLocal()
    user = db.query(User).filter(User.sid == sid).first()
    if user:
        user.status = 'typing'
        db.commit()
        await sio.emit('user_status', {
            'username': user.username,
            'status': 'typing'
        })

@sio.event
async def typing_stop(sid):
    db = SessionLocal()
    user = db.query(User).filter(User.sid == sid).first()
    if user:
        user.status = 'online'
        db.commit()
        await sio.emit('user_status', {
            'username': user.username,
            'status': 'online'
        })

@sio.event
async def send_message(sid, data):
    db = SessionLocal()
    sender = db.query(User).filter(User.sid == sid).first()
    if not sender:
        return
    
    message = Message(
        sender=sender.username,
        recipient=data['recipient'],
        content=data['message'],
        status='sent'
    )
    db.add(message)
    db.commit()
    
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
    recipient = db.query(User).filter(User.username == data['recipient']).first()
    if recipient and recipient.sid:
        message.status = 'delivered'
        db.commit()
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
    db = SessionLocal()
    message = db.query(Message).filter(Message.id == data['message_id']).first()
    if message:
        message.status = 'read'
        db.commit()
        sender = db.query(User).filter(User.username == message.sender).first()
        if sender and sender.sid:
            await sio.emit('message_status', {
                'message_id': message.id,
                'status': 'read'
            }, room=sender.sid)

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))