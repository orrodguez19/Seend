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

# Configuración de la base de datos ASÍNCRONA para SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./seend.db")
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
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default='pending')

# Configuración de SocketIO
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode='asgi')
socket_app = socketio.ASGIApp(sio, app)

templates = Jinja2Templates(directory="templates")

# Rutas API
@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat")
async def read_chat(request: Request, session_token: str = Cookie(None)):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == session_token))
        user = result.scalar()
        if user:
            return templates.TemplateResponse("chat.html", {"request": request, "username": user.username})
        else:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Sesión inválida"})

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
        user = result.scalar_one_or_none()
        if user and pwd_context.verify(data['password'], user.password_hash):
            session_token = secrets.token_urlsafe(32)
            user.sid = session_token
            await db.commit()
            response.set_cookie(key="session_token", value=session_token, httponly=True)
            return {"status": "success"}
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/check_session")
async def check_session(session_token: str = Cookie(None)):
    if not session_token:
        return {"logged_in": False}
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == session_token))
        user = result.scalar()
        if user:
            return {"logged_in": True, "username": user.username}
        else:
            return {"logged_in": False}

@sio.event
async def connect(sid, environ):
    async with AsyncSessionLocal() as db:
        try:
            session_token = environ.get('HTTP_COOKIE').split('session_token=')[1]
            result = await db.execute(select(User).where(User.sid == session_token))
            user = result.scalar()
            if user:
                user.status = 'online'
                user.sid = sid
                user.last_seen = datetime.utcnow()
                await db.commit()
                await sio.emit('user_connected', {'username': user.username}, broadcast=True, skip_sid=sid)
                await sio.emit('user_status', {'username': user.username, 'status': 'online'}, broadcast=True, skip_sid=sid)
                print(f"User {user.username} connected with session ID: {sid}")
            else:
                print(f"Anonymous user connected with session ID: {sid}")
        except (KeyError, IndexError):
            print(f"Anonymous user connected with session ID: {sid} (No session token found)")

@sio.event
async def disconnect(sid):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        user = result.scalar()
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
            user.sid = None
            await db.commit()
            await sio.emit('user_disconnected', {'username': user.username}, broadcast=True)
            await sio.emit('user_status', {'username': user.username, 'status': 'offline'}, broadcast=True)
            print(f"User {user.username} disconnected from session ID: {sid}")

@sio.on('get_online_users')
async def get_online_users(sid):
    online_users = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.status == 'online'))
        users = result.scalars().all()
        for user in users:
            online_users.append(user.username)
    await sio.emit('online_users', online_users, room=sid)

@sio.on('send_message')
async def send_message(sid, data):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.sid == sid))
        sender = result.scalar()
        if sender:
            message = Message(sender=sender.username, recipient=data['recipient'], message=data['message'])
            db.add(message)
            await db.commit()
            await sio.emit('new_message', {
                'id': message.id,
                'sender': sender.username,
                'message': data['message'],
                'timestamp': message.timestamp.isoformat(),
                'status': message.status,
                'is_own': True
            }, room=sid)
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

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
