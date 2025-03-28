from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'seend-secret-2025'  # Cambia esto por una clave segura
socketio = SocketIO(app)

# Inicializar base de datos SQLite
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT UNIQUE, 
                  password TEXT, 
                  email TEXT, 
                  bio TEXT DEFAULT 'Usuario nuevo')''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  sender_id INTEGER, 
                  receiver_id INTEGER, 
                  text TEXT, 
                  timestamp TEXT, 
                  status TEXT DEFAULT 'sent')''')
    conn.commit()
    conn.close()

# Ruta principal
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html')

# Ruta de login y registro
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form['action']
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        if action == 'login':
            c.execute("SELECT id, username FROM users WHERE username=? AND password=?", (username, password))
            user = c.fetchone()
            if user:
                session['user_id'] = user[0]
                session['username'] = user[1]
                conn.close()
                return redirect(url_for('index'))
            else:
                conn.close()
                return render_template('login.html', error="Credenciales incorrectas")
        
        elif action == 'register':
            email = request.form['email']
            try:
                c.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)", (username, password, email))
                conn.commit()
                c.execute("SELECT id, username FROM users WHERE username=?", (username,))
                user = c.fetchone()
                session['user_id'] = user[0]
                session['username'] = user[1]
                conn.close()
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                conn.close()
                return render_template('login.html', error="El usuario ya existe")
    
    return render_template('login.html')

# API para obtener todos los usuarios
@app.route('/api/users', methods=['GET'])
def get_users():
    if 'user_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, username, email, bio FROM users")
    users = [{'id': row[0], 'name': row[1], 'email': row[2], 'bio': row[3], 'lastSeen': 'En línea', 'isOnline': True} for row in c.fetchall()]
    conn.close()
    return jsonify(users)

# API para obtener mensajes de un chat
@app.route('/api/messages/<int:receiver_id>', methods=['GET'])
def get_messages(receiver_id):
    if 'user_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT sender_id, receiver_id, text, timestamp, status FROM messages WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) ORDER BY timestamp",
              (session['user_id'], receiver_id, receiver_id, session['user_id']))
    messages = [{'sender_id': row[0], 'receiver_id': row[1], 'text': row[2], 'timestamp': row[3], 'status': row[4]} for row in c.fetchall()]
    conn.close()
    return jsonify(messages)

# Cerrar sesión
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

# Eventos de SocketIO
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(str(session['user_id']))

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        leave_room(str(session['user_id']))

@socketio.on('send_message')
def handle_message(data):
    sender_id = session.get('user_id')
    if not sender_id:
        return
    
    receiver_id = data['receiver_id']
    text = data['text']
    timestamp = data['timestamp']
    
    # Guardar mensaje en la base de datos
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, text, timestamp) VALUES (?, ?, ?, ?)",
              (sender_id, receiver_id, text, timestamp))
    conn.commit()
    conn.close()
    
    # Enviar mensaje al receptor y al remitente
    message = {'sender_id': sender_id, 'receiver_id': receiver_id, 'text': text, 'timestamp': timestamp, 'status': 'sent'}
    emit('new_message', message, room=str(receiver_id))
    emit('new_message', message, room=str(sender_id))

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
