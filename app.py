from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from mega import Mega
import sqlite3
import io
import uuid
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración MEGA (usa variables de entorno en producción)
mega = Mega().login('smorlando676@gmail.com', 'mO*061119')
DB_NAME = "chat_app.db"

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.writing_status = {}
        self.user_info = {}

    async def update_presence(self, user_id: str, online: bool):
        message = {
            'type': 'presence',
            'user_id': user_id,
            'online': online,
            'username': self.user_info.get(user_id, {}).get('username', ''),
            'avatar': self.user_info.get(user_id, {}).get('avatar', '')
        }
        for uid, ws in list(self.active_connections.items()):
            try: 
                await ws.send_json(message)
            except:
                await self.disconnect(uid)

    async def connect(self, websocket: WebSocket, user_id: str, username: str, avatar: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_info[user_id] = {'username': username, 'avatar': avatar}
        await self.update_presence(user_id, True)

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            await self.update_presence(user_id, False)

manager = ConnectionManager()

def get_db_connection():
    conn = sqlite3.connect(':memory:')
    db_bytes = mega.download(mega.find(DB_NAME)) if mega.find(DB_NAME) else io.BytesIO()
    if db_bytes.getbuffer().nbytes > 0:
        conn.executescript(db_bytes.read().decode('utf-8'))
    return conn

def save_db(conn):
    new_db = io.BytesIO()
    conn.backup(sqlite3.connect(':memory:')).dump(new_db)
    mega.upload(DB_NAME, new_db)

@app.on_event("startup")
def init_db():
    conn = get_db_connection()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            profile_image TEXT DEFAULT '/static/default-avatar.png',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        save_db(conn)
    finally:
        conn.close()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, token: str):
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM tokens WHERE token = ? AND user_id = ? AND expires_at > datetime('now')", 
                          (token, user_id)).fetchone():
            await websocket.close(code=1008)
            return
        
        user = conn.execute("SELECT username, profile_image FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            await websocket.close(code=1008)
            return
            
        await manager.connect(websocket, user_id, user[0], user[1])
        while True:
            data = await websocket.receive_json()
            if data['type'] == 'message':
                message_id = str(uuid.uuid4())
                conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, datetime('now'))",
                           (message_id, user_id, data['receiver_id'], data['text']))
                save_db(conn)
                await manager.send_personal_message({
                    'type': 'new_message',
                    'id': message_id,
                    'sender_id': user_id,
                    'text': data['text'],
                    'timestamp': datetime.now().isoformat()
                }, data['receiver_id'])
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    finally:
        conn.close()

@app.post("/register")
async def register(username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)).fetchone():
            raise HTTPException(400, detail="Usuario o email ya registrado")
        
        user_id = str(uuid.uuid4())
        conn.execute("INSERT INTO users (id, username, email, password) VALUES (?, ?, ?, ?)",
                   (user_id, username, email, password))
        
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO tokens VALUES (?, ?, datetime('now', '+7 days'))",
                   (token, user_id))
        
        save_db(conn)
        return {"token": token, "user_id": user_id}
    finally:
        conn.close()

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT id, profile_image FROM users WHERE username = ? AND password = ?",
                          (username, password)).fetchone()
        if not user:
            raise HTTPException(401, detail="Credenciales inválidas")
        
        token = secrets.token_hex(32)
        conn.execute("INSERT OR REPLACE INTO tokens VALUES (?, ?, datetime('now', '+7 days'))",
                   (token, user[0]))
        
        save_db(conn)
        return {"token": token, "user_id": user[0], "profile_image": user[1]}
    finally:
        conn.close()

@app.get("/api/profile")
async def get_profile(user_id: str):
    conn = get_db_connection()
    try:
        profile = conn.execute("""
            SELECT username, email, bio, profile_image 
            FROM users WHERE id = ?""", (user_id,)).fetchone()
        return {
            "username": profile[0],
            "email": profile[1],
            "bio": profile[2] or "",
            "profile_image": profile[3]
        }
    finally:
        conn.close()

@app.post("/api/update-profile")
async def update_profile(
    user_id: str = Form(...),
    username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    bio: Optional[str] = Form(None)
):
    conn = get_db_connection()
    try:
        if username:
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
        if email:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
        if bio:
            conn.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user_id))
        
        save_db(conn)
        return {"status": "success"}
    finally:
        conn.close()

@app.post("/api/update-avatar")
async def update_avatar(user_id: str = Form(...), file: UploadFile = File(...)):
    if not file.content_type.startswith('image/'):
        raise HTTPException(400, detail="Solo se permiten imágenes")
    
    file_path = f"static/avatars/{user_id}.jpg"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET profile_image = ? WHERE id = ?", 
                   (f"/{file_path}", user_id))
        save_db(conn)
        return {"profile_image": f"/{file_path}"}
    finally:
        conn.close()

@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/chat")
async def chat_page():
    return FileResponse("templates/chat.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
