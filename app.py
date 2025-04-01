from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from socketio import AsyncServer
import os
import asyncpg
import uvicorn
import socketio
from contextlib import asynccontextmanager
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración Socket.IO
sio = AsyncServer(async_mode='asgi', cors_allowed_origins=[])

# Configuración
PORT = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend")

async def create_database_tables():
    """Función para crear las tablas necesarias en la base de datos"""
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Crear tabla de usuarios
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE,
                bio TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        ''')
        
        # Crear tabla de mensajes
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL REFERENCES users(id),
                receiver_id INTEGER NOT NULL REFERENCES users(id),
                text TEXT NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                status VARCHAR(20) DEFAULT 'sent'
            )
        ''')
        
        logger.info("✅ Tablas creadas exitosamente")
    except Exception as e:
        logger.error(f"❌ Error al crear tablas: {e}")
        raise
    finally:
        if conn:
            await conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manager del ciclo de vida de la aplicación"""
    # Crear tablas al iniciar
    await create_database_tables()
    
    # Iniciar Socket.IO
    await sio.emit('server_start', {'message': 'Server started'})
    yield
    # Limpieza al apagar
    await sio.disconnect()

app = FastAPI(lifespan=lifespan)
socketio_app = socketio.ASGIApp(sio, app)

# Configuración de middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key="tu_clave_secreta_muy_segura")

# Templates y archivos estáticos
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Eventos Socket.IO
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
        return

    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            "INSERT INTO messages (sender_id, receiver_id, text, timestamp) VALUES ($1, $2, $3, $4)",
            data['sender_id'], data['receiver_id'], data['text'], data['timestamp']
        )
        
        message = {
            'sender_id': data['sender_id'],
            'receiver_id': data['receiver_id'],
            'text': data['text'],
            'timestamp': data['timestamp'],
            'status': 'sent'
        }
        
        await sio.emit('new_message', message, room=str(data['receiver_id']))
        await sio.emit('new_message', message, room=str(data['sender_id']))
    except Exception as e:
        logger.error(f"Error al guardar mensaje: {e}")
    finally:
        if conn:
            await conn.close()

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
    
    if not username or not password:
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Usuario y contraseña son requeridos"}
        )
    
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        if action == "login":
            user = await conn.fetchrow(
                "SELECT id, username FROM users WHERE username=$1 AND password=$2",
                username, password
            )
            if user:
                request.session["user_id"] = user["id"]
                request.session["username"] = user["username"]
                return RedirectResponse(url="/", status_code=303)
            else:
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "Credenciales incorrectas"}
                )
        
        elif action == "register":
            email = form_data.get("email")
            if not email:
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "Email es requerido para registro"}
                )
            try:
                user = await conn.fetchrow(
                    "INSERT INTO users (username, password, email) VALUES ($1, $2, $3) RETURNING id, username",
                    username, password, email
                )
                request.session["user_id"] = user["id"]
                request.session["username"] = user["username"]
                return RedirectResponse(url="/", status_code=303)
            except asyncpg.UniqueViolationError:
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "El usuario ya existe"}
                )
            except Exception as e:
                logger.error(f"Error en registro: {e}")
                return templates.TemplateResponse(
                    "login.html", 
                    {"request": request, "error": "Error al crear usuario"}
                )
    
    except asyncpg.PostgresError as e:
        logger.error(f"Error de base de datos: {e}")
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Error al conectar con la base de datos"}
        )
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        return templates.TemplateResponse(
            "login.html", 
            {"request": request, "error": "Error interno del servidor"}
        )
    finally:
        if conn:
            await conn.close()

@app.get("/api/users")
async def get_users(request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        users = await conn.fetch("SELECT id, username, email, bio FROM users")
        return [
            {
                "id": user["id"],
                "name": user["username"],
                "email": user["email"],
                "bio": user["bio"],
                "lastSeen": "En línea",
                "isOnline": True
            }
            for user in users
        ]
    except Exception as e:
        logger.error(f"Error al obtener usuarios: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener usuarios")
    finally:
        if conn:
            await conn.close()

@app.get("/api/messages/{receiver_id}")
async def get_messages(receiver_id: int, request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    conn = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        messages = await conn.fetch(
            "SELECT sender_id, receiver_id, text, timestamp, status FROM messages "
            "WHERE (sender_id=$1 AND receiver_id=$2) OR (sender_id=$2 AND receiver_id=$1) "
            "ORDER BY timestamp",
            request.session["user_id"], receiver_id
        )
        return [
            {
                "sender_id": msg["sender_id"],
                "receiver_id": msg["receiver_id"],
                "text": msg["text"],
                "timestamp": msg["timestamp"].isoformat(),
                "status": msg["status"]
            }
            for msg in messages
        ]
    except Exception as e:
        logger.error(f"Error al obtener mensajes: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener mensajes")
    finally:
        if conn:
            await conn.close()

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

if __name__ == "__main__":
    uvicorn.run(
        "app:socketio_app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        workers=int(os.environ.get("WEB_CONCURRENCY", 1))
    )