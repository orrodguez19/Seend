from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from socketio import AsyncServer
import os
import aiosqlite
import uvicorn
from contextlib import asynccontextmanager
import logging
import socketio
from pathlib import Path

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración Socket.IO
sio = AsyncServer(async_mode='asgi', cors_allowed_origins=[])

# Configuración de SQLite
DATABASE_PATH = "chat.db"

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                bio TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent',
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        """)
        await db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar la base de datos
    await init_db()
    # Iniciar Socket.IO
    await sio.emit('server_start', {'message': 'Server started'})
    yield
    # Limpieza al apagar
    await sio.disconnect()

app = FastAPI(lifespan=lifespan)
socketio_app = socketio.ASGIApp(sio, app)

# Configuración
PORT = int(os.environ.get("PORT", 5000))

# Middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates y archivos estáticos
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Eventos Socket.IO (se mantienen igual)
@sio.event
async def connect(sid, environ):
    logger.info(f"Cliente conectado: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Cliente desconectado: {sid}")

@sio.event
async def join(sid, data):
    user_id = data.get('userId')
    if user_id:
        sio.enter_room(sid, str(user_id))
        logger.info(f"Usuario {user_id} unido a la sala")

@sio.event
async def send_message(sid, data):
    required_fields = ['sender_id', 'receiver_id', 'text', 'timestamp']
    if not all(field in data for field in required_fields):
        logger.warning(f"Mensaje recibido sin los campos requeridos: {data}")
        return

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO messages (sender_id, receiver_id, text, timestamp) VALUES (?, ?, ?, ?)",
                (data['sender_id'], data['receiver_id'], data['text'], data['timestamp'])
            )
            await db.commit()

            message = {
                'sender_id': data['sender_id'],
                'receiver_id': data['receiver_id'],
                'text': data['text'],
                'timestamp': data['timestamp'],
                'status': 'sent'
            }

            await sio.emit('new_message', message, room=str(data['receiver_id']))
            await sio.emit('new_message', message, room=str(data['sender_id']))
            logger.info(f"Mensaje enviado de {data['sender_id']} a {data['receiver_id']}")
    except Exception as e:
        logger.error(f"Error al procesar el mensaje: {e}")

# Rutas HTTP
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

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if action == "login":
                cursor = await db.execute(
                    "SELECT id, username FROM users WHERE username=? AND password=?",
                    (username, password)
                )
                user = await cursor.fetchone()
                if user:
                    request.session["user_id"] = user[0]
                    request.session["username"] = user[1]
                    return RedirectResponse(url="/", status_code=303)
                else:
                    return templates.TemplateResponse(
                        "login.html",
                        {"request": request, "error": "Credenciales incorrectas"}
                    )

            elif action == "register":
                email = form_data.get("email")
                try:
                    cursor = await db.execute(
                        "INSERT INTO users (username, password, email) VALUES (?, ?, ?) RETURNING id, username",
                        (username, password, email)
                    )
                    user = await cursor.fetchone()
                    await db.commit()
                    request.session["user_id"] = user[0]
                    request.session["username"] = user[1]
                    return RedirectResponse(url="/", status_code=303)
                except aiosqlite.IntegrityError:
                    return templates.TemplateResponse(
                        "login.html",
                        {"request": request, "error": "El usuario ya existe"}
                    )
    except Exception as e:
        logger.error(f"Error inesperado al procesar la solicitud de login/registro: {e}")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Error interno del servidor"})

@app.get("/api/users")
async def get_users(request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT id, username, email, bio FROM users")
            users = await cursor.fetchall()
            return [
                {
                    "id": user[0],
                    "name": user[1],
                    "email": user[2],
                    "bio": user[3],
                    "lastSeen": "En línea",
                    "isOnline": True
                }
                for user in users
            ]
    except Exception as e:
        logger.error(f"Error al obtener usuarios: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener la lista de usuarios")

@app.get("/api/messages/{receiver_id}")
async def get_messages(receiver_id: int, request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT sender_id, receiver_id, text, timestamp, status FROM messages "
                "WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) "
                "ORDER BY timestamp",
                (request.session["user_id"], receiver_id, receiver_id, request.session["user_id"])
            )
            messages = await cursor.fetchall()
            return [
                {
                    "sender_id": msg[0],
                    "receiver_id": msg[1],
                    "text": msg[2],
                    "timestamp": msg[3],
                    "status": msg[4]
                }
                for msg in messages
            ]
    except Exception as e:
        logger.error(f"Error al obtener mensajes con {receiver_id}: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener los mensajes")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

if __name__ == "__main__":
    uvicorn.run(
        "main:socketio_app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=int(os.environ.get("WEB_CONCURRENCY", 1))
    )