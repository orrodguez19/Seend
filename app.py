from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import sqlite3
import time
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app)

# Conexión a la base de datos SQLite
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    
    # Crear tabla de usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')
    
    # Crear tabla de mensajes
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        receiver TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp REAL NOT NULL
    )''')
    
    conn.commit()
    conn.close()

# Inicializar la base de datos al arrancar
init_db()

# Almacenamiento en memoria para usuarios conectados
connected_users = {}  # {sid: {"name": username, "online": True}}

@app.route('/')
def auth():
    error = request.args.get('error')
    return render_template('auth.html', error=error)

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
    
    if user:
        session['username'] = username
        return redirect(url_for('index'))
    return redirect(url_for('auth', error='Usuario o contraseña incorrectos'))

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
        return redirect(url_for('auth', error='El usuario ya existe'))
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
    c.execute("SELECT username FROM users")
    all_users = [row[0] for row in c.fetchall()]
    conn.close()
    
    users_list = []
    for username in all_users:
        online = any(user["name"] == username for user in connected_users.values())
        users_list.append({"name": username, "online": online})
    
    return jsonify({"users": users_list})

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
    messages_data = [{'sender': row[0], 'receiver': row[1], 'message': row[2], 'timestamp': row[3]} for row in c.fetchall()]
    conn.close()
    
    return jsonify({"messages": messages_data})

@app.route('/api/chats', methods=['GET'])
def get_chats():
    if 'username' not in session:
        return jsonify({"error": "No autenticado"}), 401
    
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT CASE 
            WHEN sender = ? THEN receiver 
            ELSE sender 
        END AS contact
        FROM messages 
        WHERE sender = ? OR receiver = ?
    """, (session['username'], session['username'], session['username']))
    chats = [row[0] for row in c.fetchall()]
    conn.close()
    
    chats_list = []
    for contact in chats:
        online = any(user["name"] == contact for user in connected_users.values())
        chats_list.append({"name": contact, "online": online})
    
    return jsonify({"chats": chats_list})

@socketio.on('connect')
def handle_connect():
    if 'username' not in session:
        return False
    sid = request.sid
    connected_users[sid] = {"name": session['username'], "online": True}
    emit('users_update', {"users": get_users().json["users"]}, broadcast=True)
    emit('chats_update', {"chats": get_chats().json["chats"]}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in connected_users:
        del connected_users[sid]
    emit('users_update', {"users": get_users().json["users"]}, broadcast=True)
    emit('chats_update', {"chats": get_chats().json["chats"]}, broadcast=True)

@socketio.on('message')
def handle_message(data):
    sid = request.sid
    sender = connected_users.get(sid, {"name": "Unknown"})["name"]
    receiver = data.get('receiver')
    message = data.get('message')
    timestamp = time.time()
    
    if sender and receiver and message:
        conn = sqlite3.connect('chat.db')
        c = conn.cursor()
        c.execute("INSERT INTO messages (sender, receiver, message, timestamp) VALUES (?, ?, ?, ?)",
                 (sender, receiver, message, timestamp))
        conn.commit()
        conn.close()
        
        message_data = {
            'sender': sender,
            'receiver': receiver,
            'message': message,
            'timestamp': timestamp
        }
        
        emit('new_message', message_data, broadcast=True)
        emit('chats_update', {"chats": get_chats().jsovand["chats"]}, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)