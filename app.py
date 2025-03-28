from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'seend-secret-2025')
socketio = SocketIO(app)

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT UNIQUE, 
                  password TEXT, 
                  email TEXT, 
                  bio TEXT DEFAULT 'Usuario nuevo',
                  phone TEXT,
                  dob TEXT,
                  profile_image TEXT DEFAULT 'https://www.svgrepo.com/show/452030/avatar-default.svg')''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  sender_id INTEGER, 
                  receiver_id INTEGER, 
                  text TEXT, 
                  timestamp TEXT, 
                  status TEXT DEFAULT 'sent',
                  is_read INTEGER DEFAULT 0)''')  # Nuevo campo para rastrear si el mensaje fue leído
    conn.commit()
    conn.close()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html')

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
            conn.close()
            return render_template('login.html', error="Usuario o contraseña incorrectos")
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

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/api/users', methods=['GET'])
def get_users():
    if 'user_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, username, email, bio, phone, dob, profile_image FROM users")
    users = [{'id': row[0], 'name': row[1], 'email': row[2], 'bio': row[3], 'phone': row[4], 'dob': row[5], 
              'profile_image': row[6], 'lastSeen': 'En línea', 'isOnline': True} for row in c.fetchall()]
    conn.close()
    return jsonify(users)

@app.route('/api/messages/<int:receiver_id>', methods=['GET'])
def get_messages(receiver_id):
    if 'user_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, sender_id, receiver_id, text, timestamp, status, is_read FROM messages WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) ORDER BY timestamp",
              (session['user_id'], receiver_id, receiver_id, session['user_id']))
    messages = [{'id': row[0], 'sender_id': row[1], 'receiver_id': row[2], 'text': row[3], 'timestamp': row[4], 'status': row[5], 'is_read': row[6]} for row in c.fetchall()]
    conn.close()
    return jsonify(messages)

@app.route('/api/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    data = request.get_json()
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    for field, value in data.items():
        c.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(str(session['user_id']))
        emit('user_status', {'userId': session['user_id'], 'isOnline': True, 'lastSeen': datetime.now().strftime('%H:%M')}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        leave_room(str(session['user_id']))
        emit('user_status', {'userId': session['user_id'], 'isOnline': False, 'lastSeen': datetime.now().strftime('%H:%M')}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    sender_id = session.get('user_id')
    if not sender_id:
        return
    
    receiver_id = data['receiver_id']
    text = data['text']
    timestamp = data['timestamp']
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, text, timestamp) VALUES (?, ?, ?, ?)",
              (sender_id, receiver_id, text, timestamp))
    message_id = c.lastrowid
    conn.commit()
    conn.close()
    
    message = {'id': message_id, 'sender_id': sender_id, 'receiver_id': receiver_id, 'text': text, 'timestamp': timestamp, 'status': 'sent', 'is_read': 0}
    
    # Notificar a ambos usuarios para agregar el chat si no existe
    emit('new_message', message, room=str(receiver_id))
    emit('new_message', message, room=str(sender_id))
    
    # Notificar creación de chat privado si es nuevo
    if not any(chat['memberId'] == receiver_id and not chat['isGroup'] for chat in chats_data(sender_id)):
        emit('new_chat', {'id': message_id, 'name': get_username(receiver_id), 'memberId': receiver_id, 'isGroup': False, 'lastMessage': text, 'unreadCount': 1}, room=str(sender_id))
        emit('new_chat', {'id': message_id, 'name': get_username(sender_id), 'memberId': sender_id, 'isGroup': False, 'lastMessage': text, 'unreadCount': 1}, room=str(receiver_id))

@socketio.on('create_group')
def handle_group_creation(data):
    creator_id = session.get('user_id')
    if not creator_id:
        return
    
    group_id = data['id']
    group_name = data['name']
    members = data['members']
    
    group_data = {'id': group_id, 'name': group_name, 'creatorId': creator_id, 'members': members, 'isGroup': True, 'lastMessage': 'Grupo creado', 'unreadCount': 0}
    
    # Notificar a todos los miembros del grupo
    for member_id in members:
        emit('new_chat', group_data, room=str(member_id))

@socketio.on('message_delivered')
def handle_delivered(data):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE messages SET status='delivered' WHERE id=?", (data['messageId'],))
    conn.commit()
    conn.close()
    emit('message_delivered', data, room=str(data['receiver_id']))

@socketio.on('message_read')
def handle_read(data):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE messages SET status='read', is_read=1 WHERE id=?", (data['messageId'],))
    conn.commit()
    conn.close()
    emit('message_read', data, room=str(data['receiver_id']))

@socketio.on('typing')
def handle_typing(data):
    emit('typing', data, room=str(data['chatId']))

@socketio.on('profile_update')
def handle_profile_update(data):
    emit('profile_update', data, broadcast=True)

def get_username(user_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else "Usuario"

def chats_data(user_id):
    # Esto es una simulación, en una app real deberías persistir chats en la base de datos
    return []  # Por ahora, devolvemos una lista vacía ya que chats se maneja en el frontend

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
