from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from flask import request
import uuid
import sqlite3
from datetime import datetime
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'una_clave_secreta_muy_larga_y_aleatoria'  # Cambiar en producción
socketio = SocketIO(app, cors_allowed_origins="*")  # Ajustar en producción

# Configuración de la base de datos SQLite
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (sid TEXT, user_id TEXT PRIMARY KEY, username TEXT, online INTEGER, profile_pic BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, receiver_id TEXT,
                  message TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

# Obtener conexión a la base de datos
def get_db():
    conn = sqlite3.connect('chat.db')
    conn.row_factory = sqlite3.Row
    return conn

# Inicializar la base de datos al arrancar
init_db()

@socketio.on('connect')
def connect():
    print(f'Cliente conectado: {request.sid}')
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET online = 1 WHERE sid = ?", (request.sid,))
    conn.commit()
    conn.close()
    emit_user_list()

@socketio.on('disconnect')
def disconnect():
    print(f'Cliente desconectado: {request.sid}')
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET online = 0 WHERE sid = ?", (request.sid,))
    conn.commit()
    conn.close()

    user_id = get_user_id(request.sid)
    if user_id:
        emit('userDisconnected', user_id, broadcast=True)
        emit_user_list()

@socketio.on('setUsername')
def set_username(username):
    conn = get_db()
    c = conn.cursor()
    user_id = str(uuid.uuid4())
    c.execute("INSERT OR REPLACE INTO users (sid, user_id, username, online) VALUES (?, ?, ?, 1)", (request.sid, user_id, username))
    conn.commit()
    conn.close()
    emit('setUserId', {'userId': user_id}, session=True)
    emit_user_list()

@socketio.on('setProfilePic')
def set_profile_pic(data):
    conn = get_db()
    c = conn.cursor()
    user_id = get_user_id(request.sid)
    if user_id:
        profile_pic_data = base64.b64decode(data['profilePic'])
        c.execute("UPDATE users SET profile_pic = ? WHERE user_id = ?", (profile_pic_data, user_id))
        conn.commit()
        conn.close()
        emit_user_list()

@socketio.on('sendMessage')
def handle_message(data):
    sender_id = get_user_id(request.sid)
    receiver_socket_id = data['receiverSocketId']
    message = data['message']
    timestamp = datetime.now().isoformat()

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, message, timestamp) VALUES (?, ?, ?, ?)",
              (sender_id, receiver_socket_id, message, timestamp))
    conn.commit()
    conn.close()

    # Encontrar el username del remitente
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id = ?", (sender_id,))
    sender_data = c.fetchone()
    conn.close()
    sender_username = sender_data['username'] if sender_data else "Unknown"

    emit('receiveMessage', {'senderId': sender_id, 'senderUsername': sender_username, 'message': message}, room=receiver_socket_id)
    emit('receiveMessage', {'senderId': sender_id, 'senderUsername': sender_username, 'message': message}, room=request.sid) # Enviar al remitente también

@socketio.on('getHistory')
def get_history(receiverSocketId):
    sender_id = get_user_id(request.sid)
    receiver_id = get_user_id_by_sid(receiverSocketId) # Necesitamos el user_id del receptor

    if sender_id and receiver_id:
        conn = get_db()
        c = conn.cursor()
        c.execute("""SELECT m.message, m.sender_id, u.username
                       FROM messages m
                       JOIN users u ON m.sender_id = u.user_id
                       WHERE (m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?)
                       ORDER BY m.timestamp""", (sender_id, receiver_id, receiver_id, sender_id))
        history = [dict(row) for row in c.fetchall()]
        conn.close()
        emit('loadHistory', history, room=request.sid)

def get_user_id(sid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE sid = ?", (sid,))
    result = c.fetchone()
    conn.close()
    return result['user_id'] if result else None

def get_user_id_by_sid(sid):
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
    return render_template('chat.html')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
