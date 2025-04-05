from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, disconnect
import sqlite3
import secrets
from datetime import datetime
import os
from flask_cors import CORS

# Configuración de la aplicación
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = secrets.token_hex(16)
CORS(app)  # Habilita CORS para todas las rutas
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Configuración de la base de datos
def get_db():
    conn = sqlite3.connect("seend.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Tabla de usuarios
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar_initials TEXT,
            online_status TEXT DEFAULT 'offline',
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Tabla de mensajes
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            recipient_id TEXT,
            content TEXT NOT NULL,
            reply_to INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (recipient_id) REFERENCES users (id)
        )
        ''')
        
        # Chat público por defecto
        cursor.execute('''
        INSERT OR IGNORE INTO users (id, username, password, avatar_initials, online_status)
        VALUES ('public', 'Chat Público', 'public', 'GP', 'online')
        ''')
        
        conn.commit()
        print("✅ Base de datos inicializada correctamente")
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {e}")
    finally:
        conn.close()

# Estado de la aplicación
connected_users = {}

# Rutas HTTP
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

# Eventos Socket.IO
@socketio.on('connect')
def handle_connect():
    print(f'🔌 Cliente conectado - SID: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'🔌 Cliente desconectado - SID: {request.sid}')
    if request.sid in connected_users:
        user_id = connected_users[request.sid]["user_id"]
        update_user_status(user_id, 'offline')
        del connected_users[request.sid]

def update_user_status(user_id, status):
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET online_status = ?, last_seen = ? WHERE id = ?",
            (status, datetime.now() if status == 'offline' else None, user_id)
        )
        db.commit()
        
        user = db.execute(
            "SELECT username, avatar_initials FROM users WHERE id = ?", 
            (user_id,)
        ).fetchone()
        
        if user:
            emit("user_status", {
                "user_id": user_id,
                "status": status,
                "username": user["username"],
                "avatar_initials": user["avatar_initials"],
                "last_seen": datetime.now().isoformat() if status == 'offline' else None
            }, broadcast=True)
    except Exception as e:
        print(f"Error al actualizar estado: {e}")
    finally:
        db.close()

@socketio.on('authenticate')
def handle_authenticate(data):
    user_id = data.get('user_id')
    session_token = data.get('session_token')  # En producción, validar el token
    
    if not user_id:
        emit("auth_failed")
        return
    
    db = get_db()
    try:
        user = db.execute(
            "SELECT id, username, avatar_initials FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        
        if user:
            connected_users[request.sid] = {
                "user_id": user["id"],
                "username": user["username"],
                "avatar_initials": user["avatar_initials"]
            }
            
            update_user_status(user["id"], 'online')
            send_user_list()
        else:
            emit("auth_failed")
    except Exception as e:
        print(f"Error en autenticación: {e}")
        emit("auth_failed")
    finally:
        db.close()

@socketio.on('register')
def handle_register(data):
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        emit("register_response", {"success": False, "message": "Datos incompletos"})
        return
    
    db = get_db()
    try:
        # Verificar si el usuario ya existe
        if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            emit("register_response", {
                "success": False,
                "message": "El usuario ya existe"
            })
            return
        
        user_id = secrets.token_hex(8)
        avatar_initials = (username[:2]).upper()
        
        db.execute(
            "INSERT INTO users (id, username, password, avatar_initials) VALUES (?, ?, ?, ?)",
            (user_id, username, password, avatar_initials)
        )
        db.commit()
        
        emit("register_response", {
            "success": True,
            "user_id": user_id,
            "username": username,
            "avatar_initials": avatar_initials,
            "session_token": secrets.token_hex(16)  # En producción, usar JWT
        })
    except Exception as e:
        emit("register_response", {
            "success": False,
            "message": f"Error en el registro: {str(e)}"
        })
    finally:
        db.close()

@socketio.on('login')
def handle_login(data):
    username = data.get('username')
    password = data.get('password')
    
    db = get_db()
    try:
        user = db.execute(
            "SELECT id, username, avatar_initials FROM users WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        
        if user:
            connected_users[request.sid] = {
                "user_id": user["id"],
                "username": user["username"],
                "avatar_initials": user["avatar_initials"]
            }
            
            update_user_status(user["id"], 'online')
            
            emit("login_response", {
                "success": True,
                "user_id": user["id"],
                "username": user["username"],
                "avatar_initials": user["avatar_initials"],
                "session_token": secrets.token_hex(16)  # En producción, usar JWT
            })
        else:
            emit("login_response", {
                "success": False,
                "message": "Credenciales incorrectas"
            })
    except Exception as e:
        emit("login_response", {
            "success": False,
            "message": f"Error en el login: {str(e)}"
        })
    finally:
        db.close()

def send_user_list():
    db = get_db()
    try:
        users = db.execute('''
            SELECT id, username, avatar_initials, online_status, last_seen 
            FROM users
            ORDER BY online_status DESC, username ASC
        ''').fetchall()
        
        emit("user_list", [dict(user) for user in users], broadcast=True)
    except Exception as e:
        print(f"Error al enviar lista de usuarios: {e}")
    finally:
        db.close()

@socketio.on('send_message')
def handle_send_message(data):
    if request.sid not in connected_users:
        return
    
    sender_id = connected_users[request.sid]["user_id"]
    content = data.get('content', '').strip()
    recipient_id = data.get('recipient_id', 'public')
    reply_to = data.get('reply_to')
    
    if not content:
        return
    
    db = get_db()
    try:
        # Insertar mensaje
        cursor = db.execute('''
            INSERT INTO messages (sender_id, recipient_id, content, reply_to)
            VALUES (?, ?, ?, ?)
        ''', (sender_id, recipient_id if recipient_id != 'public' else None, content, reply_to))
        
        message_id = cursor.lastrowid
        db.commit()
        
        # Obtener detalles del mensaje
        message = db.execute('''
            SELECT m.*, u.username as sender_name, u.avatar_initials as sender_avatar
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.id = ?
        ''', (message_id,)).fetchone()
        
        if message:
            message_data = {
                "message_id": message["id"],
                "sender_id": message["sender_id"],
                "sender_name": message["sender_name"],
                "sender_avatar": message["sender_avatar"],
                "content": message["content"],
                "timestamp": message["timestamp"],
                "reply_to": message["reply_to"],
                "is_read": message["is_read"]
            }
            
            if recipient_id == 'public':
                emit("public_message", dict(message_data), broadcast=True)
            else:
                message_data["recipient_id"] = recipient_id
                emit("private_message", dict(message_data), room=request.sid)
                
                # Enviar al destinatario si está conectado
                recipient_sid = next(
                    (sid for sid, user in connected_users.items() 
                     if user["user_id"] == recipient_id), None)
                
                if recipient_sid:
                    emit("private_message", dict(message_data), room=recipient_sid)
                    db.execute("UPDATE messages SET is_read = TRUE WHERE id = ?", (message_id,))
                    db.commit()
    except Exception as e:
        print(f"Error al enviar mensaje: {e}")
    finally:
        db.close()

@socketio.on('typing_status')
def handle_typing_status(data):
    if request.sid not in connected_users:
        return
    
    user_id = connected_users[request.sid]["user_id"]
    is_typing = data.get('is_typing', False)
    recipient_id = data.get('recipient_id', 'public')
    
    status = 'typing' if is_typing else 'online'
    update_user_status(user_id, status)
    
    emit("user_typing", {
        "user_id": user_id,
        "is_typing": is_typing,
        "recipient_id": recipient_id
    }, broadcast=True)

@socketio.on('mark_as_read')
def handle_mark_as_read(data):
    if request.sid not in connected_users:
        return
    
    message_id = data.get('message_id')
    user_id = connected_users[request.sid]["user_id"]
    
    db = get_db()
    try:
        db.execute('''
            UPDATE messages SET is_read = TRUE 
            WHERE id = ? AND recipient_id = ? AND is_read = FALSE
        ''', (message_id, user_id))
        
        if db.total_changes > 0:
            db.commit()
            emit("message_read", {
                "message_id": message_id,
                "reader_id": user_id
            }, broadcast=True)
    except Exception as e:
        print(f"Error al marcar como leído: {e}")
    finally:
        db.close()

# Inicialización
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)