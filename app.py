from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from mega import Mega
import io
import uuid
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

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

# Pool de conexiones PostgreSQL
postgresql_pool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    host="dpg-cvk4cc8dl3ps73fomqq0-a",
    database="seend",
    user="seend_user",
    password="0pXiVWU99WyqRu39J0HcNESGIp5xTeQM",
    port="5432"
)

def get_db_connection():
    conn = postgresql_pool.getconn()
    conn.autocommit = True
    return conn

def close_db_connection(conn):
    postgresql_pool.putconn(conn)

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

@app.on_event("startup")
def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                bio TEXT DEFAULT '',
                profile_image TEXT DEFAULT '/static/default-avatar.png',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                FOREIGN KEY(sender_id) REFERENCES users(id),
                FOREIGN KEY(receiver_id) REFERENCES users(id)
            )""")
    finally:
        close_db_connection(conn)

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, token: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM tokens WHERE token = %s AND user_id = %s AND expires_at > NOW()", 
                         (token, user_id))
            if not cursor.fetchone():
                await websocket.close(code=1008)
                return
            
            cursor.execute("SELECT username, profile_image FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                await websocket.close(code=1008)
                return
                
            await manager.connect(websocket, user_id, user[0], user[1])
            while True:
                data = await websocket.receive_json()
                if data['type'] == 'message':
                    message_id = str(uuid.uuid4())
                    cursor.execute("""
                        INSERT INTO messages (id, sender_id, receiver_id, text, timestamp)
                        VALUES (%s, %s, %s, %s, NOW())
                    """, (message_id, user_id, data['receiver_id'], data['text']))
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
        close_db_connection(conn)

@app.post("/register")
async def register(username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE username = %s OR email = %s", (username, email))
            if cursor.fetchone():
                raise HTTPException(400, detail="Usuario o email ya registrado")
            
            user_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO users (id, username, email, password)
                VALUES (%s, %s, %s, %s)
            """, (user_id, username, email, password))
            
            token = secrets.token_hex(32)
            cursor.execute("""
                INSERT INTO tokens (token, user_id, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL '7 days')
            """, (token, user_id))
            
            return {"token": token, "user_id": user_id}
    finally:
        close_db_connection(conn)

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, profile_image FROM users 
                WHERE username = %s AND password = %s
            """, (username, password))
            user = cursor.fetchone()
            if not user:
                raise HTTPException(401, detail="Credenciales inválidas")
            
            token = secrets.token_hex(32)
            cursor.execute("""
                INSERT INTO tokens (token, user_id, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL '7 days')
                ON CONFLICT (token) DO UPDATE
                SET expires_at = NOW() + INTERVAL '7 days'
            """, (token, user[0]))
            
            return {"token": token, "user_id": user[0], "profile_image": user[1]}
    finally:
        close_db_connection(conn)

@app.get("/api/profile")
async def get_profile(user_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT username, email, bio, profile_image 
                FROM users WHERE id = %s
            """, (user_id,))
            profile = cursor.fetchone()
            return {
                "username": profile[0],
                "email": profile[1],
                "bio": profile[2] or "",
                "profile_image": profile[3]
            }
    finally:
        close_db_connection(conn)

@app.post("/api/update-profile")
async def update_profile(
    user_id: str = Form(...),
    username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    bio: Optional[str] = Form(None)
):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if username:
                cursor.execute("UPDATE users SET username = %s WHERE id = %s", (username, user_id))
            if email:
                cursor.execute("UPDATE users SET email = %s WHERE id = %s", (email, user_id))
            if bio:
                cursor.execute("UPDATE users SET bio = %s WHERE id = %s", (bio, user_id))
            
            return {"status": "success"}
    finally:
        close_db_connection(conn)

@app.post("/api/update-avatar")
async def update_avatar(user_id: str = Form(...), file: UploadFile = File(...)):
    if not file.content_type.startswith('image/'):
        raise HTTPException(400, detail="Solo se permiten imágenes")
    
    file_path = f"static/avatars/{user_id}.jpg"
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE users SET profile_image = %s 
                WHERE id = %s
            """, (f"/{file_path}", user_id))
            return {"profile_image": f"/{file_path}"}
    finally:
        close_db_connection(conn)

@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/chat")
async def chat_page():
    return FileResponse("templates/chat.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
