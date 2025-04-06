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
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
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
    return render_template('index.html')

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
        SELECT u.username as sender, m.message, m.timestamp 
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.conversation_id = ?
        ORDER BY m.timestamp ASC
    """, (conversation_id,))

    messages = [{
        "sender": row[0],
        "message": row[1],
        "timestamp": row[2]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"messages": messages, "conversation_id": conversation_id})

@app.route('/api/chats')
def get_chats():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()

    c.execute("""
        SELECT 
            c.id,
            CASE WHEN c.user1_id = ? THEN u2.id ELSE u1.id END as contact_id,
            CASE WHEN c.user1_id = ? THEN u2.username ELSE u1.username END as contact_name,
            MAX(m.timestamp) as last_timestamp
        FROM conversations c
        JOIN users u1 ON c.user1_id = u1.id
        JOIN users u2 ON c.user2_id = u2.id
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE ? IN (c.user1_id, c.user2_id)
        GROUP BY c.id
        ORDER BY last_timestamp DESC
    """, (session['user_id'], session['user_id'], session['user_id']))

    chats = []
    for row in c.fetchall():
        online = any(u["id"] == row[1] for u in connected_users.values())
        
        chats.append({
            "conversation_id": row[0],
            "contact_id": row[1],
            "name": row[2],
            "online": online,
            "last_message": "Mensajes Privados",
            "timestamp": row[3]
        })

    conn.close()
    return jsonify({"chats": chats})

# Manejo de errores
@app.errorhandler(404)
def not_found(e):
    return redirect(url_for('auth'))

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
    emit('chats_update', get_chats().json, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in connected_users:
        del connected_users[request.sid]
    emit('users_update', get_users().json, broadcast=True)
    emit('chats_update', get_chats().json, broadcast=True)

@socketio.on('message')
def handle_message(data):
    if 'user_id' not in session:
        return

    receiver_id = data.get('receiver_id')
    message = data.get('message')
    if not receiver_id or not message:
        return

    user_ids = sorted([session['user_id'], receiver_id])
    conversation_id = f"conv_{user_ids[0]}_{user_ids[1]}"
    
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    
    c.execute("INSERT OR IGNORE INTO conversations (id, user1_id, user2_id, created_at) VALUES (?, ?, ?, ?)",
              (conversation_id, user_ids[0], user_ids[1], time.time()))
    
    message_id = f"msg_{uuid.uuid4()}"
    timestamp = time.time()
    c.execute("""
        INSERT INTO messages (id, conversation_id, sender_id, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (message_id, conversation_id, session['user_id'], message, timestamp))
    
    conn.commit()
    conn.close()

    emit('new_message', {
        "sender": session['username'],
        "receiver_id": receiver_id,
        "message": message,
        "timestamp": timestamp,
        "conversation_id": conversation_id
    }, broadcast=True)
    emit('chats_update', get_chats().json, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)