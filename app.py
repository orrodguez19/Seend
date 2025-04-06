from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
import time
import os
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app)

def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()

init_db()
connected_users = {}

@app.route('/')
def auth():
    return render_template('auth.html', error=request.args.get('error'))

@app.route('/chat')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth'))
    return render_template('index.html')

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

@app.route('/api/users', methods=['GET'])
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

@app.route('/api/messages/<user_id>', methods=['GET'])
def get_messages(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT u1.username as sender, u2.username as receiver, message, timestamp 
        FROM messages m
        JOIN users u1 ON m.sender_id = u1.id
        JOIN users u2 ON m.receiver_id = u2.id
        WHERE (m.sender_id = ? AND m.receiver_id = ?) 
           OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY timestamp ASC
    """, (session['user_id'], user_id, user_id, session['user_id']))
    messages = [{
        "sender": row[0],
        "receiver": row[1],
        "message": row[2],
        "timestamp": row[3]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"messages": messages})

@app.route('/api/chats', methods=['GET'])
def get_chats():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        WITH last_messages AS (
            SELECT 
                CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END as contact_id,
                message,
                timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END 
                    ORDER BY timestamp DESC
                ) as rn
            FROM messages 
            WHERE sender_id = ? OR receiver_id = ?
        )
        SELECT u.id, u.username, lm.message, lm.timestamp
        FROM last_messages lm
        JOIN users u ON lm.contact_id = u.id
        WHERE lm.rn = 1
        ORDER BY lm.timestamp DESC
    """, (session['user_id'], session['user_id'], session['user_id'], session['user_id']))
    chats = [{
        "id": row[0],
        "name": row[1],
        "online": any(u["id"] == row[0] for u in connected_users.values()),
        "last_message": row[2],
        "timestamp": row[3]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"chats": chats})

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
    timestamp = time.time()
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (sender_id, receiver_id, message, timestamp)
        VALUES (?, ?, ?, ?)
    """, (session['user_id'], receiver_id, message, timestamp))
    conn.commit()
    conn.close()
    emit('new_message', {
        "sender": session['username'],
        "receiver_id": receiver_id,
        "message": message,
        "timestamp": timestamp
    }, broadcast=True)
    emit('chats_update', get_chats().json, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))