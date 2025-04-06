from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
import time
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app)

# Inicialización de la base de datos
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        receiver TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL
    )''')
    conn.commit()
    conn.close()

init_db()
connected_users = {}

# Endpoints
@app.route('/')
def auth():
    return render_template('auth.html', error=request.args.get('error'))

@app.route('/chat')
def index():
    if 'username' not in session:
        return redirect(url_for('auth'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()
    return redirect(url_for('index')) if user else redirect(url_for('auth', error='Credenciales inválidas'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        session['username'] = username
        return redirect(url_for('index'))
    except sqlite3.IntegrityError:
        return redirect(url_for('auth', error='Usuario ya existe'))
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('auth'))

@app.route('/api/users', methods=['GET'])
def get_users():
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username != ?", (session['username'],))
    users = [{"name": row[0], "online": any(u["name"] == row[0] for u in connected_users.values())} 
             for row in c.fetchall()]
    conn.close()
    return jsonify({"users": users})

@app.route('/api/messages/<username>', methods=['GET'])
def get_messages(username):
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT sender, receiver, message, timestamp 
        FROM messages 
        WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)
        ORDER BY timestamp ASC
    """, (session['username'], username, username, session['username']))
    messages = [{"sender": row[0], "receiver": row[1], "message": row[2], "timestamp": row[3]} 
                for row in c.fetchall()]
    conn.close()
    return jsonify({"messages": messages})

@app.route('/api/chats', methods=['GET'])
def get_chats():
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        WITH last_messages AS (
            SELECT 
                CASE WHEN sender = ? THEN receiver ELSE sender END AS contact,
                message,
                timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN sender = ? THEN receiver ELSE sender END 
                    ORDER BY timestamp DESC
                ) as rn
            FROM messages 
            WHERE sender = ? OR receiver = ?
        )
        SELECT contact, message, timestamp
        FROM last_messages
        WHERE rn = 1
        ORDER BY timestamp DESC
    """, (session['username'], session['username'], session['username'], session['username']))
    chats = [{
        "name": row[0],
        "online": any(u["name"] == row[0] for u in connected_users.values()),
        "last_message": row[1],
        "timestamp": row[2]
    } for row in c.fetchall()]
    conn.close()
    return jsonify({"chats": chats})

# WebSockets
@socketio.on('connect')
def handle_connect():
    if 'username' not in session:
        return False
    connected_users[request.sid] = {"name": session['username'], "online": True}
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
    if 'username' not in session:
        return
    sender = session['username']
    receiver = data.get('receiver')
    message = data.get('message')
    if not all([sender, receiver, message]):
        return
    
    timestamp = time.time()
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, message, timestamp) VALUES (?, ?, ?, ?)",
             (sender, receiver, message, timestamp))
    conn.commit()
    conn.close()
    
    emit('new_message', {
        "sender": sender,
        "receiver": receiver,
        "message": message,
        "timestamp": timestamp
    }, broadcast=True)
    emit('chats_update', get_chats().json, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))