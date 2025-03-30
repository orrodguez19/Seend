import os
import re
import sqlite3
import uuid
import logging
import secrets
from datetime import datetime
from typing import Optional, Dict
from PIL import Image
import io

from flask import Flask, request, send_from_directory, redirect, render_template, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')  # Set a secret key
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=None) # Using synchronous mode for simplicity
cors = CORS(app)

DB_PATH = os.getenv('DB_PATH', 'chat_app.db')
STATIC_DIR = os.getenv('STATIC_DIR', 'static')
AVATARS_DIR = os.path.join(STATIC_DIR, 'avatars')
POSTS_DIR = os.path.join(STATIC_DIR, 'posts')
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif']

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(POSTS_DIR, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                profile_image TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                UNIQUE (user1_id, user2_id),
                FOREIGN KEY (user1_id) REFERENCES users(id),
                FOREIGN KEY (user2_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id),
                FOREIGN KEY (sender_id) REFERENCES users(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                image TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()

create_tables()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, int] = {} # sid: user_id
        self.user_info: Dict[int, str] = {} # user_id: sid

    def connect(self, sid: str, user_id: int):
        self.active_connections[sid] = user_id
        self.user_info[user_id] = sid

    def disconnect(self, sid: str):
        user_id = self.active_connections.pop(sid, None)
        if user_id:
            self.user_info.pop(user_id, None)
            emit('presence_update', {'user_id': user_id, 'online': False}, broadcast=True)

    def get_user_id(self, sid: str) -> Optional[int]:
        return self.active_connections.get(sid)

    def get_sid(self, user_id: int) -> Optional[str]:
        return self.user_info.get(user_id)

manager = ConnectionManager()

def generate_session_id():
    return secrets.token_hex(16)

def create_session(user_id: int) -> str:
    session_id = generate_session_id()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO sessions (id, user_id) VALUES (?, ?)", (session_id, user_id))
        conn.commit()
    return session_id

def get_user_from_session(session_id: str):
    with get_db_connection() as conn:
        session = conn.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session:
            return conn.execute("SELECT id, name, username, profile_image FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    return None

def get_user_by_username(username: str):
    with get_db_connection() as conn:
        return conn.execute("SELECT id, name, username, password, profile_image FROM users WHERE username = ?", (username,)).fetchone()

def get_user_by_id(user_id: int):
    with get_db_connection() as conn:
        return conn.execute("SELECT id, name, username, profile_image FROM users WHERE id = ?", (user_id,)).fetchone()

def save_profile_image(user_id: int, image_data: bytes):
    try:
        img = Image.open(io.BytesIO(image_data))
        img = img.resize((150, 150))
        filename = f"{user_id}.png"
        filepath = os.path.join(AVATARS_DIR, filename)
        img.save(filepath)
        profile_image_path = f"/static/avatars/{filename}"
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET profile_image = ? WHERE id = ?", (profile_image_path, user_id))
            conn.commit()
        return profile_image_path
    except Exception as e:
        logger.error(f"Error saving profile image: {e}")
        return None

def save_post_image(image_data: bytes):
    try:
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((800, 800))
        filename = f"{uuid.uuid4().hex}.png"
        filepath = os.path.join(POSTS_DIR, filename)
        img.save(filepath)
        return f"/static/posts/{filename}"
    except Exception as e:
        logger.error(f"Error saving post image: {e}")
        return None

@socketio.on('connect')
def handle_connect():
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if user:
        manager.connect(request.sid, user['id'])
        emit('presence_update', {'user_id': user['id'], 'online': True}, broadcast=True)
    else:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    manager.disconnect(request.sid)

@socketio.on('register')
def handle_register(data):
    username = data.get('username')
    password = data.get('password')
    name = data.get('name')
    if not all([username, password, name]):
        emit('register_error', {'message': 'Todos los campos son requeridos'}, to=request.sid)
        return
    if not re.match(r'^@\w+$', username):
        emit('register_error', {'message': 'El usuario debe comenzar con @ y contener solo letras, números y guion bajo'}, to=request.sid)
        return
    if len(password) < 6:
        emit('register_error', {'message': 'La contraseña debe tener al menos 6 caracteres'}, to=request.sid)
        return
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            emit('register_error', {'message': 'El nombre de usuario ya existe'}, to=request.sid)
            return
        hashed_password = password # In a real app, hash the password!
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, username, password) VALUES (?, ?, ?)", (name, username, hashed_password))
        user_id = cursor.lastrowid
        conn.commit()
        session_id = create_session(user_id)
        emit('registered', {'token': session_id, 'userId': user_id}, to=request.sid)

@socketio.on('login')
def handle_login(data):
    username = data.get('username')
    password = data.get('password')
    user = get_user_by_username(username)
    if user and user['password'] == password: # In a real app, compare hashed passwords!
        session_id = create_session(user['id'])
        emit('logged_in', {'token': session_id, 'userId': user['id']}, to=request.sid)
    else:
        emit('login_error', {'message': 'Credenciales inválidas'}, to=request.sid)

@socketio.on('check_username')
def handle_check_username(data):
    username = data.get('username')
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            emit('username_status', {'available': False, 'message': 'El nombre de usuario no está disponible'}, to=request.sid)
        else:
            emit('username_status', {'available': True}, to=request.sid)

@socketio.on('get_profile')
def handle_get_profile():
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if user:
        emit('profile_data', dict(user), to=request.sid)
    else:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)

@socketio.on('update_profile')
def handle_update_profile(data):
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    name = data.get('name')
    if name:
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user['id']))
            conn.commit()
        emit('profile_updated', {'name': name}, to=request.sid)

@socketio.on('upload_profile_image')
def handle_upload_profile_image(data):
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    try:
        image_data = data.get('image_data')
        if image_data:
            image_bytes = io.BytesIO(image_data.encode('latin-1')) # Assuming base64 was decoded on client
            profile_image_path = save_profile_image(user['id'], image_bytes.getvalue())
            if profile_image_path:
                emit('profile_image_updated', {'profile_image': profile_image_path}, to=request.sid)
            else:
                emit('upload_error', {'message': 'Error al guardar la imagen'}, to=request.sid)
        else:
            emit('upload_error', {'message': 'No se proporcionó imagen'}, to=request.sid)
    except Exception as e:
        logger.error(f"Error processing profile image upload: {e}")
        emit('upload_error', {'message': 'Error al procesar la imagen'}, to=request.sid)

@socketio.on('delete_account')
def handle_delete_account():
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    user_id = user['id']
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        manager.disconnect(request.sid)
        emit('account_deleted', {'message': 'Cuenta eliminada exitosamente'}, to=request.sid)
    except Exception as e:
        logger.error(f"Error eliminando cuenta: {str(e)}")
        emit('delete_error', {'message': 'Error al eliminar la cuenta'}, to=request.sid)

@socketio.on('get_users')
def handle_get_users():
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    user_id = user['id']
    with get_db_connection() as conn:
        users = conn.execute("SELECT id, name, username, profile_image FROM users").fetchall()
    users_list = [dict(user) for user in users if user['id'] != user_id]
    for user_data in users_list:
        user_data['online'] = user_data['id'] in manager.user_info
    emit('users_list', {'users': users_list}, to=request.sid)

@app.route("/")
def root():
    return redirect("/chat")

@app.route("/chat")
def chat_page():
    try:
        return render_template("chat.html")
    except FileNotFoundError:
        return "<html><body><h1>Error</h1><p>No se encontró la página de chat</p></body></html>"

@app.route("/login")
def login_page():
    try:
        return render_template("login.html")
    except FileNotFoundError:
        return "<html><body><h1>Error</h1><p>No se encontró la página de login</p></body></html>"

@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)

@socketio.on('send_message')
def handle_send_message(data):
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    sender_id = user['id']
    recipient_username = data.get('recipient')
    text = data.get('text')
    if not recipient_username or not text:
        return

    with get_db_connection() as conn:
        recipient_user = conn.execute("SELECT id FROM users WHERE username = ?", (recipient_username,)).fetchone()
        if recipient_user:
            chat = conn.execute("""
                SELECT id FROM chats
                WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
            """, (sender_id, recipient_user['id'], recipient_user['id'], sender_id)).fetchone()
            if not chat:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO chats (user1_id, user2_id) VALUES (?, ?)", (sender_id, recipient_user['id']))
                chat_id = cursor.lastrowid
                conn.commit()
            else:
                chat_id = chat['id']
            conn.execute("INSERT INTO messages (chat_id, sender_id, text) VALUES (?, ?, ?)", (chat_id, sender_id, text))
            conn.commit()

            recipient_sid = manager.get_sid(recipient_user['id'])
            message_data = {'sender': user['username'], 'text': text}
            emit('message_received', message_data, room=recipient_sid)
            emit('message_received', message_data, room=request.sid) # Send to sender as well
        else:
            emit('error', {'message': 'Usuario destinatario no encontrado'}, to=request.sid)

@socketio.on('get_chat_messages')
def handle_get_chat_messages(data):
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    other_username = data.get('username')
    if not other_username:
        return

    with get_db_connection() as conn:
        other_user = conn.execute("SELECT id FROM users WHERE username = ?", (other_username,)).fetchone()
        if other_user:
            chat = conn.execute("""
                SELECT id FROM chats
                WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)
            """, (user['id'], other_user['id'], other_user['id'], user['id'])).fetchone()
            if chat:
                messages = conn.execute("""
                    SELECT m.text, u.username AS sender
                    FROM messages m
                    JOIN users u ON m.sender_id = u.id
                    WHERE m.chat_id = ?
                    ORDER BY m.timestamp
                """, (chat['id'],)).fetchall()
                messages_list = [dict(msg) for msg in messages]
                emit('chat_messages', {'messages': messages_list, 'username': other_username}, to=request.sid)

@socketio.on('create_post')
def handle_create_post(data):
    session_id = request.cookies.get('session_id')
    user = get_user_from_session(session_id)
    if not user:
        emit('auth_error', {'message': 'No autenticado'}, to=request.sid)
        return
    text = data.get('text')
    image_data = data.get('image')
    if not text:
        emit('post_error', {'message': 'El texto de la publicación no puede estar vacío'}, to=request.sid)
        return

    image_path = None
    if image_data:
        try:
            image_bytes = io.BytesIO(image_data.encode('latin-1')) # Assuming base64 was decoded on client
            image_path = save_post_image(image_bytes.getvalue())
        except Exception as e:
            logger.error(f"Error processing post image: {e}")
            emit('post_error', {'message': 'Error al procesar la imagen de la publicación'}, to=request.sid)
            return

    with get_db_connection() as conn:
        conn.execute("INSERT INTO posts (user_id, text, image) VALUES (?, ?, ?)", (user['id'], text, image_path))
        conn.commit()
        emit('new_post', {'username': user['username'], 'text': text, 'image': image_path}, broadcast=True)

@socketio.on('get_posts')
def handle_get_posts():
    with get_db_connection() as conn:
        posts = conn.execute("""
            SELECT p.text, p.image, u.username
            FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.timestamp DESC
        """).fetchall()
    posts_list = [dict(post) for post in posts]
    emit('posts_list', {'posts': posts_list}, to=request.sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
