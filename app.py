import datetime
import os
import uuid
from contextlib import contextmanager

import sqlalchemy
import socketio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Database Configuration (síncrono)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./seend_chat.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
metadata = MetaData()

# Define User Table
users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", String, unique=True, default=lambda: str(uuid.uuid4())),
    Column("username", String, unique=True),
    Column("password", String),
    Column("status", String, default="En línea"),
    Column("last_seen", DateTime, nullable=True),
)

# Define Message Table
messages_table = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sender_id", String),
    Column("sender_username", String),
    Column("content", String),
    Column("timestamp", DateTime, default=datetime.datetime.utcnow),
)

def create_tables():
    metadata.create_all(engine)

# FastAPI and SocketIO Setup
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")
templates = Jinja2Templates(directory="templates")

connected_users = {}

@contextmanager
def lifespan(app: FastAPI):
    # Startup
    create_tables()
    connected_users.clear()
    yield
    # Shutdown (no hay conexión que cerrar en enfoque síncrono)

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
def read_root():
    return RedirectResponse("/auth")

@app.get("/auth", response_class=HTMLResponse)
def auth_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request, "error": None})

@app.post("/register", response_class=HTMLResponse)
def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    hashed_password = password  # En producción, usa bcrypt o similar para hashear
    try:
        with SessionLocal() as db:
            query = users_table.insert().values(
                username=username, 
                password=hashed_password,
                user_id=str(uuid.uuid4())
            )
            db.execute(query)
            db.commit()
        return RedirectResponse(url="/auth", status_code=303)
    except Exception as e:
        print(f"Error al registrar: {e}")
        return templates.TemplateResponse(
            "auth.html", 
            {"request": request, "error": "Error al registrar. El usuario puede existir."}
        )

@app.post("/login", response_class=HTMLResponse)
def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    with SessionLocal() as db:
        query = users_table.select().where(users_table.c.username == username)
        user = db.execute(query).fetchone()
        
        if user and user.password == password:
            response = RedirectResponse(url="/chat", status_code=303)
            response.set_cookie(key="user_id", value=user.user_id)
            response.set_cookie(key="username", value=user.username)
            return response
        else:
            return templates.TemplateResponse(
                "auth.html", 
                {"request": request, "error": "Credenciales inválidas."}
            )

@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    if not user_id or not username:
        return RedirectResponse(url="/auth", status_code=303)
    
    # Obtener historial de mensajes
    with SessionLocal() as db:
        query = messages_table.select().order_by(messages_table.c.timestamp.desc()).limit(50)
        messages = db.execute(query).fetchall()
    
    return templates.TemplateResponse(
        "chat.html", 
        {
            "request": request, 
            "user_id": user_id, 
            "username": username,
            "messages": reversed(messages)  # Mostrar del más antiguo al más nuevo
        }
    )

# SocketIO Event Handlers (mantenemos asíncrono para Socket.IO)
@sio.on("authenticate")
async def authenticate(sid, data):
    user_id = data.get("user_id")
    username = data.get("username")
    if user_id and username:
        print(f"User authenticated: {sid}, User ID: {user_id}, Username: {username}")
        connected_users[sid] = {
            "user_id": user_id, 
            "username": username, 
            "status": "En línea"
        }
        await update_user_list()
    else:
        print(f"Authentication failed: {sid}, missing user_id or username")
        return False

@sio.on("disconnect")
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    if sid in connected_users:
        # Actualizar last_seen en la base de datos
        user_id = connected_users[sid]["user_id"]
        with SessionLocal() as db:
            query = users_table.update()\
                .where(users_table.c.user_id == user_id)\
                .values(last_seen=datetime.datetime.utcnow())
            db.execute(query)
            db.commit()
        
        del connected_users[sid]
        await update_user_list()

@sio.on("send_message")
async def send_message(sid, data):
    user_info = connected_users.get(sid)
    message = data.get("message")
    if user_info and message:
        user_id = user_info["user_id"]
        username = user_info["username"]
        
        # Guardar en base de datos
        with SessionLocal() as db:
            query = messages_table.insert().values(
                sender_id=user_id,
                sender_username=username,
                content=message
            )
            db.execute(query)
            db.commit()
        
        timestamp = datetime.datetime.utcnow().isoformat()
        await sio.emit("receive_message", {
            "sender_id": user_id,
            "sender": username,
            "message": message,
            "timestamp": timestamp
        })

@sio.on("typing")
async def typing(sid, data):
    user_info = connected_users.get(sid)
    if user_info:
        username = user_info["username"]
        connected_users[sid]["status"] = "Escribiendo..."
        await update_user_list()
        await asyncio.sleep(3)
        if sid in connected_users and connected_users[sid].get("username") == username and connected_users[sid]["status"] == "Escribiendo...":
            connected_users[sid]["status"] = "En línea"
            await update_user_list()

async def update_user_list():
    await sio.emit("user_list_updated", list(connected_users.values()))

# Integrate SocketIO with FastAPI
app = socketio.ASGIApp(sio, app)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)