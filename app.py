import asyncio
import datetime
import os
import uuid  # For generating unique user IDs

import databases
import sqlalchemy
import socketio
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./seend_chat.db")
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# Define User Table
users_table = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.String, unique=True, default=lambda: str(uuid.uuid4())), # Unique user ID
    sqlalchemy.Column("username", sqlalchemy.String, unique=True),
    sqlalchemy.Column("password", sqlalchemy.String),  # Store hashed password in real app
    sqlalchemy.Column("status", sqlalchemy.String, default="En línea"),
    sqlalchemy.Column("last_seen", sqlalchemy.DateTime, nullable=True),
)

# Define Message Table
messages_table = sqlalchemy.Table(
    "messages",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("sender_id", sqlalchemy.String),  # Store sender's user ID
    sqlalchemy.Column("sender_username", sqlalchemy.String),
    sqlalchemy.Column("content", sqlalchemy.String),
    sqlalchemy.Column("timestamp", sqlalchemy.DateTime, default=datetime.datetime.utcnow),
)

engine = sqlalchemy.create_engine(DATABASE_URL)

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

# FastAPI and SocketIO Setup
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")
app = FastAPI()
templates = Jinja2Templates(directory="statics")
app.mount("/statics", StaticFiles(directory="statics"), name="statics")

@app.on_event("startup")
async def startup_event():
    await database.connect()
    await create_tables()
    global connected_users
    connected_users = {}

@app.on_event("shutdown")
async def shutdown_event():
    await database.disconnect()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return RedirectResponse("/auth")

@app.get("/auth", response_class=HTMLResponse)
async def auth_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request, "error": None})

@app.post("/register", response_class=HTMLResponse)
async def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    # In a real application, hash the password
    hashed_password = password
    try:
        query = users_table.insert().values(username=username, password=hashed_password)
        await database.execute(query)
        return RedirectResponse(url="/auth", status_code=303) # Redirect to login after registration
    except Exception as e:
        return templates.TemplateResponse("auth.html", {"request": request, "error": "Error al registrar el usuario. El nombre de usuario puede estar en uso."})

@app.post("/login", response_class=HTMLResponse)
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    # In a real application, verify the hashed password
    query = users_table.select().where(users_table.c.username == username)
    user = await database.fetch_one(query)
    if user and user["password"] == password:
        response = RedirectResponse(url="/chat", status_code=303)
        response.set_cookie(key="user_id", value=user["user_id"])
        response.set_cookie(key="username", value=user["username"])
        return response
    else:
        return templates.TemplateResponse("auth.html", {"request": request, "error": "Credenciales inválidas."})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    if not user_id or not username:
        return RedirectResponse(url="/auth", status_code=303)
    return templates.TemplateResponse("chat.html", {"request": request, "user_id": user_id, "username": username})

# SocketIO Event Handlers
connected_users = {}

@sio.on("connect")
async def connect(sid, environ, auth):
    user_id = auth.get("user_id")
    username = auth.get("username")
    if user_id and username:
        print(f"Client connected: {sid}, User ID: {user_id}, Username: {username}")
        connected_users[sid] = {"user_id": user_id, "username": username, "status": "En línea"}
        await update_user_list()
    else:
        print(f"Client connection rejected: {sid}, missing user_id or username")
        return False  # Reject connection

@sio.on("disconnect")
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    if sid in connected_users:
        del connected_users[sid]
        await update_user_list()

@sio.on("send_message")
async def send_message(sid, data):
    user_info = connected_users.get(sid)
    message = data.get("message")
    if user_info and message:
        user_id = user_info["user_id"]
        username = user_info["username"]
        await database.execute(messages_table.insert().values(sender_id=user_id, sender_username=username, content=message))
        timestamp = datetime.datetime.utcnow().isoformat()
        await sio.emit("receive_message", {"sender_id": user_id, "sender": username, "message": message, "timestamp": timestamp})

@sio.on("typing")
async def typing(sid, data):
    user_info = connected_users.get(sid)
    if user_info:
        username = user_info["username"]
        connected_users[sid]["status"] = "Escribiendo..."
        await update_user_list()
        asyncio.sleep(3)
        if sid in connected_users and connected_users[sid].get("username") == username and connected_users[sid]["status"] == "Escribiendo...":
            connected_users[sid]["status"] = "En línea"
            await update_user_list()

@sio.on("online")
async def online(sid, data):
    # Online status is now managed on connect
    pass

@sio.on("get_users")
async def get_users(sid):
    await sio.emit("user_list_updated", list(connected_users.values()), room=sid)

async def update_user_list():
    await sio.emit("user_list_updated", list(connected_users.values()))

# Integrate SocketIO with FastAPI
app = socketio.ASGIApp(sio, app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
