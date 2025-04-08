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
        reply_to_timestamp REAL,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS public_messages (
        id TEXT PRIMARY KEY,
        sender_id TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL,
        reply_to_timestamp REAL,
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
        SELECT u.username as sender, m.message, m.timestamp, m.status, m2.message as reply_message, m2.timestamp as reply_timestamp, u2.username as reply_sender
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        LEFT JOIN messages m2 ON m.reply_to_timestamp = m2.timestamp AND m.conversation_id = m2.conversation_id
        LEFT JOIN users u2 ON m2.sender_id = u2.id
        WHERE m.conversation_id = ?
        ORDER BY m.timestamp ASC
    """, (conversation_id,))

    messages = []
    for row in c.fetchall():
        message = {
            "sender": row[0],
            "message": row[1],
            "timestamp": row[2],
            "status": row[3]
        }
        if row[4]:  # Si hay mensaje al que se responde
            message["replyTo"] = {
                "sender": row[6],
                "message": row[4],
                "timestamp": row[5]
            }
        messages.append(message)
    conn.close()
    return jsonify({"messages": messages, "conversation_id": conversation_id})

@app.route('/api/public_messages')
def get_public_messages():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT u.username as sender, pm.message, pm.timestamp, pm2.message as reply_message, pm2.timestamp as reply_timestamp, u2.username as reply_sender
        FROM public_messages pm
        JOIN users u ON pm.sender_id = u.id
        LEFT JOIN public_messages pm2 ON pm.reply_to_timestamp = pm2.timestamp
        LEFT JOIN users u2 ON pm2.sender_id = u2.id
        ORDER BY pm.timestamp ASC
    """)
    messages = []
    for row in c.fetchall():
        message = {
            "sender": row[0],
            "message": row[1],
            "timestamp": row[2]
        }
        if row[3]:  # Si hay mensaje al que se responde
            message["replyTo"] = {
                "sender": row[5],
                "message": row[3],
                "timestamp": row[4]
            }
        messages.append(message)
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
    timestamp = data.get('timestamp')
    reply_to_timestamp = data.get('replyTo', {}).get('timestamp') if data.get('replyTo') else None
    if not message or not sender or not timestamp:
        return

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    message_id = f"pubmsg_{uuid.uuid4()}"
    c.execute("""
        INSERT INTO public_messages (id, sender_id, message, timestamp, reply_to_timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (message_id, session['user_id'], message, timestamp, reply_to_timestamp))
    conn.commit()
    conn.close()

    message_data = {
        "sender": sender,
        "message": message,
        "timestamp": timestamp
    }
    if reply_to_timestamp:
        conn = sqlite3.connect('chat.db')
        c = conn.cursor()
        c.execute("SELECT u.username, message, timestamp FROM public_messages pm JOIN users u ON pm.sender_id = u.id WHERE pm.timestamp = ?", (reply_to_timestamp,))
        reply_data = c.fetchone()
        conn.close()
        if reply_data:
            message_data["replyTo"] = {
                "sender": reply_data[0],
                "message": reply_data[1],
                "timestamp": reply_data[2]
            }

    emit('public_message', message_data, broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    if 'user_id' not in session:
        return

    receiver_id = data.get('receiver_id')
    message = data.get('message')
    sender = data.get('sender')
    conversation_id = data.get('conversation_id')
    timestamp = data.get('timestamp')
    reply_to_timestamp = data.get('replyTo', {}).get('timestamp') if data.get('replyTo') else None
    if not receiver_id or not message or not conversation_id or not timestamp:
        return

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    message_id = f"msg_{uuid.uuid4()}"
    receiver_sid = next((sid for sid, user in connected_users.items() if user['id'] == receiver_id), None)
    initial_status = 'delivered' if receiver_sid else 'sent'
    c.execute("""
        INSERT INTO messages (id, conversation_id, sender_id, message, timestamp, status, reply_to_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (message_id, conversation_id, session['user_id'], message, timestamp, initial_status, reply_to_timestamp))
    conn.commit()

    message_data = {
        "sender": sender,
        "message": message,
        "timestamp": timestamp,
        "conversation_id": conversation_id,
        "status": initial_status
    }
    if reply_to_timestamp:
        c.execute("""
            SELECT u.username, m.message, m.timestamp 
            FROM messages m 
            JOIN users u ON m.sender_id = u.id 
            WHERE m.conversation_id = ? AND m.timestamp = ?
        """, (conversation_id, reply_to_timestamp))
        reply_data = c.fetchone()
        if reply_data:
            message_data["replyTo"] = {
                "sender": reply_data[0],
                "message": reply_data[1],
                "timestamp": reply_data[2]
            }
    conn.close()

    sender_sid = request.sid
    emit('private_message', message_data, room=sender_sid)
    if receiver_sid:
        emit('private_message', message_data, room=receiver_sid)
        emit('message_status_update', {
            "conversation_id": conversation_id,
            "status": initial_status,
            "timestamp": timestamp
        }, room=sender_sid)

@socketio.on('message_status')
def handle_message_status(data):
    if 'user_id' not in session:
        return

    conversation_id = data.get('conversation_id')
    status = data.get('status')
    timestamp = data.get('timestamp')

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        UPDATE messages 
        SET status = ? 
        WHERE conversation_id = ? AND sender_id != ? AND timestamp = ? AND status != 'seen'
    """, (status, conversation_id, session['user_id'], timestamp))
    conn.commit()

    c.execute("""
        SELECT timestamp, status 
        FROM messages 
        WHERE conversation_id = ? AND timestamp = ?
    """, (conversation_id, timestamp))
    updated_message = c.fetchone()
    conn.close()

    if updated_message:
        sender_sid = next((sid for sid, user in connected_users.items() if user['id'] != session['user_id'] and conversation_id.startswith(f"conv_{min(user['id'], session['user_id'])}_{max(user['id'], session['user_id'])}")), None)
        if sender_sid:
            emit('message_status_update', {
                "conversation_id": conversation_id,
                "status": updated_message[1],
                "timestamp": updated_message[0]
            }, room=sender_sid)

@socketio.on('mark_all_as_seen')
def handle_mark_all_as_seen(data):
    if 'user_id' not in session:
        return

    conversation_id = data.get('conversation_id')
    receiver_id = data.get('receiver_id')

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        UPDATE messages 
        SET status = 'seen' 
        WHERE conversation_id = ? AND sender_id != ? AND status != 'seen'
    """, (conversation_id, session['user_id']))
    conn.commit()

    c.execute("""
        SELECT timestamp, status 
        FROM messages 
        WHERE conversation_id = ? AND sender_id != ?
    """, (conversation_id, session['user_id']))
    updated_messages = c.fetchall()
    conn.close()

    sender_sid = next((sid for sid, user in connected_users.items() if user['id'] == receiver_id), None)
    if sender_sid:
        emit('all_messages_seen', {
            "conversation_id": conversation_id,
            "messages": [{"timestamp": m[0], "status": m[1]} for m in updated_messages]
        }, room=sender_sid)

@socketio.on('delete_public_message')
def handle_delete_public_message(data):
    if 'user_id' not in session:
        return

    timestamp = data.get('timestamp')
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("DELETE FROM public_messages WHERE timestamp = ? AND sender_id = ?", (timestamp, session['user_id']))
    conn.commit()
    conn.close()

    emit('delete_public_message', {"timestamp": timestamp}, broadcast=True)

@socketio.on('delete_private_message')
def handle_delete_private_message(data):
    if 'user_id' not in session:
        return

    conversation_id = data.get('conversation_id')
    timestamp = data.get('timestamp')

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE conversation_id = ? AND timestamp = ? AND sender_id = ?", 
              (conversation_id, timestamp, session['user_id']))
    conn.commit()
    conn.close()

    sender_sid = request.sid
    receiver_sid = next((sid for sid, user in connected_users.items() if conversation_id.startswith(f"conv_{min(user['id'], session['user_id'])}_{max(user['id'], session['user_id'])}") and user['id'] != session['user_id']), None)
    emit('delete_private_message', {"conversation_id": conversation_id, "timestamp": timestamp}, room=sender_sid)
    if receiver_sid:
        emit('delete_private_message', {"conversation_id": conversation_id, "timestamp": timestamp}, room=receiver_sid)

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
    user_id = data.get('user_id')
    conversation_id = data.get('conversation_id')
    if not receiver_id or not conversation_id:
        return

    receiver_sid = next((sid for sid, user in connected_users.items() if user['id'] == receiver_id), None)
    if receiver_sid:
        emit('typing', {
            "user_id": user_id,
            "conversation_id": conversation_id
        }, room=receiver_sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)