from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from flask import request
import uuid
import sqlite3
from datetime import datetime
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'una_clave_secreta_muy_larga_y_aleatoria'  # Cambiar en producción
socketio = SocketIO(app, cors_allowed_origins="http://localhost:5000")  # Restringir en producción

# Configuración de la base de datos SQLite
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    # Tabla de usuarios (agregamos campo para foto de perfil)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (sid TEXT, user_id TEXT PRIMARY KEY, username TEXT, online INTEGER, profile_pic BLOB)''')
    # Tabla de mensajes
    c.execute('''CREATE TABLE IF NOT EXISTS messages 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, receiver_id TEXT, 
                  message TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()

# Obtener conexión a la base de datos
def get_db():
    conn = sqlite3.connect('chat.db')
    conn.row_factory = sqlite3.Row  # Para devolver filas como diccionarios
    return conn

# Inicializar la base de datos al arrancar
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
    
    # Enviar lista de usuarios a todos
    emit_user_list()

@socketio.on('registerProfile')
def handle_register_profile(data):
    username = data.get('username', f"User_{get_user_id(request.sid)}")
    profile_pic = data.get('profilePic')  # Base64 de la imagen
    conn = get_db()
    c = conn.cursor()
    if profile_pic:
        # Decodificar Base64 a binario
        profile_pic_binary = base64.b64decode(profile_pic.split(',')[1]) if ',' in profile_pic else base64.b64decode(profile_pic)
        c.execute("UPDATE users SET username = ?, sid = ?, profile_pic = ? WHERE sid = ?", 
                  (username, request.sid, profile_pic_binary, request.sid))
    else:
        c.execute("UPDATE users SET username = ?, sid = ? WHERE sid = ?", 
                  (username, request.sid, request.sid))
    conn.commit()
    conn.close()
    
    # Actualizar lista de usuarios
    emit_user_list()

@socketio.on('sendMessage')
def handle_send_message(data):
    receiver_socket_id = data['receiverSocketId']
    message = data['message']
    sender_sid = request.sid
    
    conn = get_db()
    c = conn.cursor()
    
    # Obtener IDs de usuario
    sender_id = get_user_id(sender_sid)
    receiver_id = get_user_id(receiver_socket_id)
    
    if sender_id and receiver_id:
        # Guardar mensaje en la base de datos
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO messages (sender_id, receiver_id, message, timestamp) VALUES (?, ?, ?, ?)", 
                  (sender_id, receiver_id, message, timestamp))
        conn.commit()
        
        # Obtener nombre del emisor
        c.execute("SELECT username FROM users WHERE user_id = ?", (sender_id,))
        sender_username = c.fetchone()['username']
        
        # Enviar mensaje al receptor y al emisor
        msg_data = {'senderId': sender_id, 'senderUsername': sender_username, 'message': message}
        emit('receiveMessage', msg_data, room=receiver_socket_id)
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
    
    # Notificar desconexión y actualizar lista
    user_id = get_user_id(request.sid)
    if user_id:
        emit('userDisconnected', user_id, broadcast=True)
        emit_user_list()

# Función auxiliar para obtener user_id desde sid
def get_user_id(sid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE sid = ?", (sid,))
    result = c.fetchone()
    conn.close()
    return result['user_id'] if result else None

# Función para emitir la lista de usuarios
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