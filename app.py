from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
from flask import request
import uuid
import sqlite3
from datetime import datetime
import base64
import os  # Importar la librería os

app = Flask(__name__, static_folder='static', static_url_path='') # Configurar para servir archivos estáticos
app.config['SECRET_KEY'] = 'una_clave_secreta_muy_larga_y_aleatoria'  # Cambiar en producción
socketio = SocketIO(app, cors_allowed_origins="*")  # Ajustar en producción

# Configuración de la base de datos SQLite
DATABASE = 'chat.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (sid TEXT, user_id TEXT PRIMARY KEY, username TEXT, online INTEGER, profile_pic BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, receiver_id TEXT,
                  message TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

init_db()

@socketio.on('connect')
def handle_connect():
    user_id = str(uuid.uuid4())[:8]
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (sid, user_id, username, online) VALUES (?, ?, ?, ?)",
              (request.sid, user_id, f"User_{user_id}", 1))
    conn.commit()
    conn.close()
    emit('setUserId', {'userId': user_id}, room=request.sid)
    emit_user_list()

@socketio.on('registerProfile')
def handle_register_profile(data):
    username = data.get('username', f"User_{get_user_id(request.sid)}")
    profile_pic = data.get('profilePic')
    conn = get_db()
    c = conn.cursor()
    if profile_pic:
        profile_pic_binary = base64.b64decode(profile_pic.split(',')[1]) if ',' in profile_pic else base64.b64decode(profile_pic)
        c.execute("UPDATE users SET username = ?, sid = ?, profile_pic = ? WHERE sid = ?",
                  (username, request.sid, profile_pic_binary, request.sid))
    else:
        c.execute("UPDATE users SET username = ?, sid = ? WHERE sid = ?",
                  (username, request.sid, request.sid))
    conn.commit()
    conn.close()
    emit_user_list()

@socketio.on('requestUserList')
def handle_request_user_list():
    emit_user_list()

@socketio.on('sendMessage')
def handle_send_message(data):
    receiver_user_id = data['receiverSocketId']
    message = data['message']
    sender_sid = request.sid
    conn = get_db()
    c = conn.cursor()
    sender_id = get_user_id(sender_sid)
    c.execute("SELECT sid FROM users WHERE user_id = ?", (receiver_user_id,))
    result = c.fetchone()
    receiver_sid = result['sid'] if result else None
    if sender_id and receiver_user_id and receiver_sid:
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO messages (sender_id, receiver_id, message, timestamp) VALUES (?, ?, ?, ?)",
                  (sender_id, receiver_user_id, message, timestamp))
        conn.commit()
        c.execute("SELECT username FROM users WHERE user_id = ?", (sender_id,))
        sender_username = c.fetchone()['username']
        msg_data = {'senderId': sender_id, 'senderUsername': sender_username,
                    'message': message}
        emit('receiveMessage', msg_data, room=receiver_sid)
        emit('receiveMessage', msg_data, room=sender_sid)
    conn.close()

@socketio.on('getChatHistory')
def handle_get_chat_history(data):
    other_user_id = data['otherUserId']
    my_id = get_user_id(request.sid)
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT sender_id, receiver_id, message, timestamp, u.username AS sender_username
        FROM messages m
        JOIN users u ON m.sender_id = u.user_id
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        ORDER BY timestamp ASC
    """, (my_id, other_user_id, other_user_id, my_id))
    history = [dict(row) for row in c.fetchall()]
    conn.close()
    emit('chatHistory', history)

@socketio.on('disconnect')
def handle_disconnect():
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET online = 0 WHERE sid = ?", (request.sid,))
    conn.commit()
    conn.close()
    user_id = get_user_id(request.sid)
    if user_id:
        emit('userDisconnected', user_id, broadcast=True)
        emit_user_list()

def get_user_id(sid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE sid = ?", (sid,))
    result = c.fetchone()
    conn.close()
    return result['user_id'] if result else None

def emit_user_list():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id AS id, username, online, profile_pic FROM users")
    users = c.fetchall()
    user_list = []
    for user in users:
        user_dict = dict(user)
        if user['profile_pic']:
            user_dict['profile_pic'] = base64.b64encode(user['profile_pic']).decode('utf-8')
        user_list.append(user_dict)
    conn.close()
    emit('userList', user_list, broadcast=True)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'chat.html')

@app.route('/login')
def login_page():
    return send_from_directory(app.static_folder, 'login.html')

@app.route('/register')
def register_page():
    return send_from_directory(app.static_folder, 'register.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) # Obtener el puerto de la variable de entorno o usar 5000 por defecto
    socketio.run(app, debug=False, host='0.0.0.0', port=port) # Ejecutar en el puerto especificado y en todas las interfaces
