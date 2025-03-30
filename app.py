import os
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
import socketio
from typing import Dict
from datetime import datetime
import uuid
import aiofiles

app = FastAPI()

# Configuración de Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio, app)

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Almacenamiento en memoria (en producción usarías una base de datos)
users = {}
active_connections: Dict[str, WebSocket] = {}
user_rooms = {}

# Rutas HTTP
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

# Eventos Socket.IO
@sio.event
async def connect(sid, environ):
    print(f"Cliente conectado: {sid}")

@sio.event
async def disconnect(sid):
    if sid in users:
        username = users[sid]['username']
        del users[sid]
        await sio.emit('user_disconnected', {'username': username})
    print(f"Cliente desconectado: {sid}")

@sio.event
async def login(sid, data):
    username = data.get('username')
    if not username:
        return {'status': 'error', 'message': 'Username is required'}
    
    users[sid] = {
        'username': username,
        'sid': sid,
        'status': 'online',
        'avatar': f"https://ui-avatars.com/api/?name={username}&background=random"
    }
    await sio.emit('user_connected', {'username': username, 'users': list_users()})
    return {'status': 'success', 'user': users[sid]}

@sio.event
async def send_message(sid, data):
    message = data.get('message')
    if not message or not sid in users:
        return
    
    sender = users[sid]
    message_data = {
        'id': str(uuid.uuid4()),
        'sender': sender['username'],
        'message': message,
        'timestamp': datetime.now().isoformat(),
        'avatar': sender['avatar']
    }
    
    await sio.emit('new_message', message_data)

@sio.event
async def update_profile(sid, data):
    if sid not in users:
        return
    
    user = users[sid]
    user.update(data)
    await sio.emit('profile_updated', {
        'username': user['username'],
        'profile': user
    })

def list_users():
    return [{'username': u['username'], 'status': u['status'], 'avatar': u['avatar']} 
            for u in users.values()]

# Manejo de archivos estáticos
@app.exception_handler(404)
async def custom_404_handler(request: Request, _):
    if request.url.path.startswith('/static/'):
        return FileResponse("static/index.html")
    return templates.TemplateResponse("404.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=8000)