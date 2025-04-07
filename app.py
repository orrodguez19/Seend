from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
import time
import os
import uuid

# Configuración inicial
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app)

# Inicialización de la base de datos
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        user1_id TEXT NOT NULL,
        user2_id TEXT NOT NULL,
        created_at REAL NOT NULL,
        FOREIGN KEY (user1_id) REFERENCES users(id),
        FOREIGN KEY (user2_id) REFERENCES users(id),
        UNIQUE(user1_id, user2_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL,
        status TEXT DEFAULT 'sent',
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS public_messages (
        id TEXT PRIMARY KEY,
        sender_id TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL,
        FOREIGN KEY (sender_id) REFERENCES users(id)
    )''')

    conn.commit()
    conn.close()

init_db()
connected_users = {}

# Rutas de autenticación
@app.route('/')
def auth():
    return render_template('auth.html', error=request.args.get('error'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()

    if user:
        session['user_id'] = user[0]
        session['username'] = user[1]
        return redirect(url_for('index'))
    return redirect(url_for('auth', error='Credenciales inválidas'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    user_id = str(uuid.uuid4())

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (id, username, password) VALUES (?, ?, ?)", 
                  (user_id, username, password))
        conn.commit()
        session['user_id'] = user_id
        session['username'] = username
        return redirect(url_for('index'))
    except sqlite3.IntegrityError:
        return redirect(url_for('auth', error='Usuario ya existe'))
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

# Ruta principal del chat
@app.route('/chat')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth'))
    return render_template('index.html', user_id=session['user_id'], username=session['username'])

# API Endpoints
@app.route('/api/users')
def get_users():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id != ?", (session['user_id'],))
    users = [{
        "id": row[0],
        "name": row[1],
        "online": any(u["id"] == row[0] for u in connected_users.values())
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"users": users})

@app.route('/api/conversations/<user_id>')
def get_conversation_messages(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401

    user_ids = sorted([session['user_id'], user_id])
    conversation_id = f"conv_{user_ids[0]}_{user_ids[1]}"

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()

    c.execute("INSERT OR IGNORE INTO conversations (id, user1_id, user2_id, created_at) VALUES (?, ?, ?, ?)",
              (conversation_id, user_ids[0], user_ids[1], time.time()))
    conn.commit()

    c.execute("""
        SELECT u.username as sender, m.message, m.timestamp, m.status
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = ?
        ORDER BY m.timestamp ASC
    """, (conversation_id,))

    messages = [{
        "sender": row[0],
        "message": row[1],
        "timestamp": row[2],
        "status": row[3]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"messages": messages, "conversation_id": conversation_id})

@app.route('/api/public_messages')
def get_public_messages():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT u.username as sender, pm.message, pm.timestamp
        FROM public_messages pm
        JOIN users u ON pm.sender_id = u.id
        ORDER BY pm.timestamp ASC
    """)
    messages = [{
        "sender": row[0],
        "message": row[1],
        "timestamp": row[2]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"messages": messages})

# Eventos de Socket.IO
@socketio.on('connect')
def handle_connect():
    if 'user_id' not in session:
        return False
    connected_users[request.sid] = {
        "id": session['user_id'],
        "name": session['username']
    }
    emit('users_update', get_users().json, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in connected_users:
        del connected_users[request.sid]
    emit('users_update', get_users().json, broadcast=True)

@socketio.on('public_message')
def handle_public_message(data):
    if 'user_id' not in session:
        return

    message = data.get('message')
    sender = data.get('sender')
    if not message or not sender:
        return

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    message_id = f"pubmsg_{uuid.uuid4()}"
    timestamp = time.time()
    c.execute("""
        INSERT INTO public_messages (id, sender_id, message, timestamp)
        VALUES (?, ?, ?, ?)
    """, (message_id, session['user_id'], message, timestamp))
    conn.commit()
    conn.close()

    emit('public_message', {
        "sender": sender,
        "message": message,
        "timestamp": timestamp
    }, broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    if 'user_id' not in session:
        return

    receiver_id = data.get('receiver_id')
    message = data.get('message')
    sender = data.get('sender')
    conversation_id = data.get('conversation_id')
    if not receiver_id or not message or not conversation_id:
        return

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    message_id = f"msg_{uuid.uuid4()}"
    timestamp = time.time()
    receiver_sid = next((sid for sid, user in connected_users.items() if user['id'] == receiver_id), None)
    initial_status = 'delivered' if receiver_sid else 'sent'
    c.execute("""
        INSERT INTO messages (id, conversation_id, sender_id, message, timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (message_id, conversation_id, session['user_id'], message, timestamp, initial_status))
    conn.commit()
    conn.close()

    sender_sid = request.sid
    message_data = {
        "sender": sender,
        "message": message,
        "timestamp": timestamp,
        "conversation_id": conversation_id,
        "status": initial_status
    }
    emit('private_message', message_data, room=sender_sid)
    if receiver_sid:
        emit('private_message', message_data, room=receiver_sid)

@socketio.on('message_status')
def handle_message_status(data):
    if 'user_id' not in session:
        return

    conversation_id = data.get('conversation_id')
    status = data.get('status')

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        UPDATE messages 
        SET status = ? 
        WHERE conversation_id = ? AND sender_id != ? AND status != 'seen'
    """, (status, conversation_id, session['user_id']))
    conn.commit()
    conn.close()

    sender_sid = next((sid for sid, user in connected_users.items() if user['id'] != session['user_id'] and conversation_id.startswith(f"conv_{min(user['id'], session['user_id'])}_{max(user['id'], session['user_id'])}")), None)
    if sender_sid:
        emit('message_status_update', {
            "conversation_id": conversation_id,
            "status": status
        }, room=sender_sid)

@socketio.on('public_typing')
def handle_public_typing(data):
    if 'user_id' not in session:
        return

    sender = data.get('sender')
    if not sender:
        return

    emit('public_typing', {"sender": sender}, broadcast=True, include_self=False)

@socketio.on('typing')
def handle_typing(data):
    if 'user_id' not in session:
        return

    receiver_id = data.get('receiver_id')
    if not receiver_id:
        return

    receiver_sid = next((sid for sid, user in connected_users.items() if user['id'] == receiver_id), None)
    if receiver_sid:
        user_ids = sorted([session['user_id'], receiver_id])
        conversation_id = f"conv_{user_ids[0]}_{user_ids[1]}"
        emit('typing', {
            "user_id": session['user_id'],
            "conversation_id": conversation_id
        }, room=receiver_sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)