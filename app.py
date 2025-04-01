from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from socketio import AsyncServer
import os
import asyncpg
import uvicorn
from contextlib import asynccontextmanager
import logging
import socketio

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración Socket.IO
sio = AsyncServer(async_mode='asgi', cors_allowed_origins=[])

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Iniciar Socket.IO
    await sio.emit('server_start', {'message': 'Server started'})
    yield
    # Limpieza al apagar
    await sio.disconnect()

app = FastAPI(lifespan=lifespan)
socketio_app = socketio.ASGIApp(sio, app)

# Configuración
PORT = int(os.environ.get("PORT", 5000))
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.error("La variable de entorno DATABASE_URL no está configurada.")
    # Puedes decidir si quieres detener la aplicación aquí o usar un valor por defecto menos seguro
    # raise EnvironmentError("DATABASE_URL environment variable not set")
    DATABASE_URL = "postgresql://seend_user:0pXiVWU99WyqRu39J0HcNESGIp5xTeQM@dpg-cvk4cc8dl3ps73fomqq0-a/seend" # Fallback, usar con precaución

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
        logger.warning(f"Mensaje recibido sin los campos requeridos: {data}")
        return

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
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
            logger.info(f"Mensaje enviado de {data['sender_id']} a {data['receiver_id']}")
        except Exception as e:
            logger.error(f"Error al guardar mensaje: {e}")
        finally:
            await conn.close()
    except asyncpg.exceptions.InvalidAuthorizationError as e:
        logger.error(f"Error de autenticación de la base de datos: {e}")
    except asyncpg.exceptions.ConnectionDoesNotExistError as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
    except Exception as e:
        logger.error(f"Error inesperado al procesar el mensaje: {e}")

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
        conn = await asyncpg.connect(DATABASE_URL)
        try:
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
        except asyncpg.exceptions.InvalidAuthorizationError as e:
            logger.error(f"Error de autenticación de la base de datos: {e}")
            return templates.TemplateResponse("login.html", {"request": request, "error": "Error de base de datos"})
        except asyncpg.exceptions.ConnectionDoesNotExistError as e:
            logger.error(f"No se pudo conectar a la base de datos: {e}")
            return templates.TemplateResponse("login.html", {"request": request, "error": "Error de conexión a la base de datos"})
        except Exception as e:
            logger.error(f"Error inesperado al procesar la solicitud de login/registro: {e}")
            return templates.TemplateResponse("login.html", {"request": request, "error": "Error interno del servidor"})
    finally:
        if 'conn' in locals():
            await conn.close()

@app.get("/api/users")
async def get_users(request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            users = await conn.fetch("SELECT id, username, email, bio FROM users")
            return [
                {
                    "id": user["id"],
                    "name": user["username"],
                    "email": user["email"],
                    "bio": user["bio"],
                    "lastSeen": "En línea", # Esto podría ser más dinámico en una aplicación real
                    "isOnline": True # Esto también podría ser gestionado de forma más precisa
                }
                for user in users
            ]
        except Exception as e:
            logger.error(f"Error al obtener usuarios: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener la lista de usuarios")
        finally:
            await conn.close()
    except asyncpg.exceptions.InvalidAuthorizationError as e:
        logger.error(f"Error de autenticación de la base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")
    except asyncpg.exceptions.ConnectionDoesNotExistError as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error de conexión a la base de datos")
    except Exception as e:
        logger.error(f"Error inesperado al procesar la solicitud de usuarios: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@app.get("/api/messages/{receiver_id}")
async def get_messages(receiver_id: int, request: Request):
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
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
            logger.error(f"Error al obtener mensajes con {receiver_id}: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener los mensajes")
        finally:
            await conn.close()
    except asyncpg.exceptions.InvalidAuthorizationError as e:
        logger.error(f"Error de autenticación de la base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error de base de datos")
    except asyncpg.exceptions.ConnectionDoesNotExistError as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error de conexión a la base de datos")
    except Exception as e:
        logger.error(f"Error inesperado al procesar la solicitud de mensajes: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

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
