from flask import Flask, render_template, request, send_from_directory from flask_socketio import SocketIO, emit, disconnect import sqlite3 import secrets from datetime import datetime from werkzeug.security import generate_password_hash, check_password_hash import os

app = Flask(name) app.config['SECRET_KEY'] = secrets.token_hex(16) socketio = SocketIO(app, cors_allowed_origins="*")

def get_db(): conn = sqlite3.connect("seend.db") conn.row_factory = sqlite3.Row return conn

def init_db(): conn = get_db() cursor = conn.cursor()

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

cursor.execute('''
INSERT OR IGNORE INTO users (id, username, password, avatar_initials, online_status)
VALUES ('public', 'Chat Público', ?, 'GP', 'online')
''', (generate_password_hash("public"),))

conn.commit()
conn.close()

connected_users = {}

@app.route('/static/path:filename') def serve_static(filename): return send_from_directory('static', filename)

@app.route('/') def index(): return render_template('seend.html')

@socketio.on('connect') def handle_connect(): print(f'Cliente conectado: {request.sid}')

@socketio.on('disconnect') def handle_disconnect(): if request.sid in connected_users: user_id = connected_users[request.sid]["user_id"] db = get_db() db.execute( "UPDATE users SET online_status = 'offline', last_seen = ? WHERE id = ?", (datetime.now(), user_id) ) db.commit() db.close()

emit("user_status", {
        "user_id": user_id,
        "status": "offline",
        "last_seen": datetime.now().isoformat()
    }, broadcast=True)

    del connected_users[request.sid]
print(f'Cliente desconectado: {request.sid}')

@socketio.on('register') def handle_register(data): username = data.get('username') password = data.get('password')

db = get_db()
cursor = db.cursor()

try:
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        emit("register_response", {
            "success": False,
            "message": "El usuario ya existe"
        })
        return

    user_id = secrets.token_hex(8)
    avatar_initials = (username[:2]).upper()
    hashed_password = generate_password_hash(password)

    cursor.execute(
        "INSERT INTO users (id, username, password, avatar_initials) VALUES (?, ?, ?, ?)",
        (user_id, username, hashed_password, avatar_initials)
    )
    db.commit()

    emit("register_response", {
        "success": True,
        "user_id": user_id,
        "username": username,
        "avatar_initials": avatar_initials,
        "session_token": secrets.token_hex(16)
    })

except Exception as e:
    emit("register_response", {
        "success": False,
        "message": str(e)
    })
finally:
    db.close()

@socketio.on('login') def handle_login(data): username = data.get('username') password = data.get('password')

db = get_db()
cursor = db.cursor()

try:
    cursor.execute(
        "SELECT id, username, password, avatar_initials FROM users WHERE username = ?",
        (username,)
    )
    user = cursor.fetchone()

    if user and check_password_hash(user["password"], password):
        connected_users[request.sid] = {
            "user_id": user["id"],
            "username": user["username"],
            "avatar_initials": user["avatar_initials"],
            "status": "online"
        }

        cursor.execute(
            "UPDATE users SET online_status = 'online', last_seen = ? WHERE id = ?",
            (datetime.now(), user["id"])
        )
        db.commit()

        emit("login_response", {
            "success": True,
            "user_id": user["id"],
            "username": user["username"],
            "avatar_initials": user["avatar_initials"],
            "session_token": secrets.token_hex(16)
        })

        emit("user_status", {
            "user_id": user["id"],
            "status": "online",
            "username": user["username"],
            "avatar_initials": user["avatar_initials"]
        }, broadcast=True)

        send_user_list()

    else:
        emit("login_response", {
            "success": False,
            "message": "Credenciales incorrectas"
        })

except Exception as e:
    emit("login_response", {
        "success": False,
        "message": str(e)
    })
finally:
    db.close()

def send_user_list(): db = get_db() cursor = db.cursor() cursor.execute("SELECT id, username, avatar_initials, online_status, last_seen FROM users") users = [dict(user) for user in cursor.fetchall()] db.close() emit("user_list", users, broadcast=True)

@socketio.on('send_message') def handle_send_message(data): if request.sid not in connected_users: return

sender_id = connected_users[request.sid]["user_id"]
content = data.get('content')
recipient_id = data.get('recipient_id', 'public')
reply_to = data.get('reply_to')

if not content:
    return

db = get_db()
cursor = db.cursor()

try:
    cursor.execute('''
    INSERT INTO messages (sender_id, recipient_id, content, reply_to)
    VALUES (?, ?, ?, ?)
    ''', (sender_id, None if recipient_id == 'public' else recipient_id, content, reply_to))

    message_id = cursor.lastrowid
    db.commit()

    timestamp = datetime.now().isoformat()
    sender_name = connected_users[request.sid]["username"]
    sender_avatar = connected_users[request.sid]["avatar_initials"]

    message_data = {
        "message_id": message_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_avatar": sender_avatar,
        "content": content,
        "timestamp": timestamp,
        "reply_to": reply_to,
        "is_read": recipient_id == 'public'
    }

    if recipient_id == 'public':
        emit("public_message", message_data, broadcast=True)
    else:
        message_data["recipient_id"] = recipient_id
        emit("private_message", message_data, room=request.sid)

        recipient_sid = next((s for s, u in connected_users.items() if u["user_id"] == recipient_id), None)

        if recipient_sid:
            emit("private_message", message_data, room=recipient_sid)
            cursor.execute("UPDATE messages SET is_read = TRUE WHERE id = ?", (message_id,))
            db.commit()
        else:
            emit("unread_count", {
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "count": 1
            }, room=request.sid)

except Exception as e:
    print(f"Error al enviar mensaje: {e}")
finally:
    db.close()

@socketio.on('typing_status') def handle_typing_status(data): if request.sid not in connected_users: return

user_id = connected_users[request.sid]["user_id"]
is_typing = data.get('is_typing', False)
recipient_id = data.get('recipient_id', 'public')

status = 'typing' if is_typing else 'online'
connected_users[request.sid]["status"] = status

db = get_db()
db.execute(
    "UPDATE users SET online_status = ? WHERE id = ?",
    (status, user_id)
)
db.commit()
db.close()

emit("user_typing", {
    "user_id": user_id,
    "is_typing": is_typing,
    "recipient_id": recipient_id
}, broadcast=True)

@socketio.on('mark_as_read') def handle_mark_as_read(data): if request.sid not in connected_users: return

message_id = data.get('message_id')
user_id = connected_users[request.sid]["user_id"]

db = get_db()
cursor = db.cursor()

try:
    cursor.execute('''
    UPDATE messages SET is_read = TRUE 
    WHERE id = ? AND recipient_id = ? AND is_read = FALSE
    ''', (message_id, user_id))

    if cursor.rowcount > 0:
        db.commit()
        emit("message_read", {
            "message_id": message_id,
            "reader_id": user_id
        }, broadcast=True)

except Exception as e:
    print(f"Error al marcar como leído: {e}")
finally:
    db.close()

@socketio.on('load_history') def handle_load_history(data): if request.sid not in connected_users: return

user_id = connected_users[request.sid]["user_id"]
peer_id = data.get("peer_id")

db = get_db()
cursor = db.cursor()

try:
    if peer_id == "public":
        cursor.execute("""
        SELECT * FROM messages WHERE recipient_id IS NULL
        ORDER BY timestamp ASC
        """)
    else:
        cursor.execute("""
        SELECT * FROM messages
        WHERE (sender_id = ? AND recipient_id = ?)
           OR (sender_id = ? AND recipient_id = ?)
        ORDER BY timestamp ASC
        """, (user_id, peer_id, peer_id, user_id))

    history = [dict(row) for row in cursor.fetchall()]
    emit("chat_history", {"peer_id": peer_id, "messages": history})

except Exception as e:
    print(f"Error al cargar historial: {e}")
finally:
    db.close()

init_db()

if name == 'main': port = int(os.environ.get('PORT', 5000)) socketio.run(app, host='0.0.0.0', port=port)

