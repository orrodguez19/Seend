from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import time
import os
import uuid
import requests

app = Flask(__name__, template_folder='templates', static_folder='public')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
socketio = SocketIO(app)

def get_db_connection():
    conn = sqlite3.connect('chat.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        avatar TEXT,
        birthday TEXT,
        gender TEXT,
        home TEXT,
        created_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        user1_id TEXT,
        user2_id TEXT,
        group_name TEXT,
        is_group INTEGER DEFAULT 0,
        created_at REAL NOT NULL,
        FOREIGN KEY (user1_id) REFERENCES users(id),
        FOREIGN KEY (user2_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversation_members (
        conversation_id TEXT,
        user_id TEXT,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        PRIMARY KEY (conversation_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        message TEXT NOT NULL,
        image TEXT,
        timestamp REAL NOT NULL,
        status TEXT DEFAULT 'sent',
        reply_to_timestamp REAL,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (sender_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()

init_db()
connected_users = {}

@app.route('/')
def auth():
    return render_template('auth.html', error=request.args.get('error'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE username = ? AND password = ?", (username, password))
    user = c.fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        return redirect(url_for('index'))
    return redirect(url_for('auth', error='Credenciales inválidas'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    password = request.form['password']
    user_id = str(uuid.uuid4())
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (id, username, password, created_at) VALUES (?, ?, ?, ?)", 
                  (user_id, username, password, time.time()))
        conn.commit()
        session['user_id'] = user_id
        session['username'] = username
        return redirect(url_for('index'))
    except sqlite3.IntegrityError:
        conn.rollback()
        return redirect(url_for('auth', error='Usuario ya existe'))
    finally:
        conn.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

@app.route('/chat')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth'))
    return render_template('index.html', user_id=session['user_id'], username=session['username'])

@app.route('/api/users')
def get_users():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE id != ?", (session['user_id'],))
    users = [{"id": row['id'], "name": row['username'], "online": row['id'] in connected_users} 
             for row in c.fetchall()]
    conn.close()
    return jsonify({"users": users})

@app.route('/api/conversations')
def get_conversations():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT c.id, c.group_name, c.is_group, c.user1_id, c.user2_id, 
               COUNT(CASE WHEN m.status != 'seen' AND m.sender_id != ? THEN 1 END) as unread_count
        FROM conversations c
        LEFT JOIN messages m ON c.id = m.conversation_id
        WHERE c.user1_id = ? OR c.user2_id = ? OR EXISTS (
            SELECT 1 FROM conversation_members cm WHERE cm.conversation_id = c.id AND cm.user_id = ?
        )
        GROUP BY c.id, c.group_name, c.is_group, c.user1_id, c.user2_id
    """, (session['user_id'], session['user_id'], session['user_id'], session['user_id']))
    conversations = c.fetchall()
    result = []
    for conv in conversations:
        if conv['is_group']:
            name = conv['group_name']
            user_id = None
        else:
            other_user_id = conv['user1_id'] if conv['user2_id'] == session['user_id'] else conv['user2_id']
            c.execute("SELECT username FROM users WHERE id = ?", (other_user_id,))
            name = c.fetchone()['username'] if other_user_id else "Usuario desconocido"
            user_id = other_user_id
        online = user_id in connected_users if user_id else False
        result.append({
            "id": conv['id'],
            "name": name,
            "is_group": bool(conv['is_group']),
            "user_id": user_id,
            "unread_count": conv['unread_count'] or 0,
            "online": online
        })
    conn.close()
    return jsonify({"conversations": result})

@app.route('/api/conversations/<conversation_id>')
def get_conversation_messages(conversation_id):
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT u.username, m.message, m.image, m.timestamp, m.status, 
               m2.message, m2.timestamp, u2.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        LEFT JOIN messages m2 ON m.reply_to_timestamp = m2.timestamp AND m.conversation_id = m2.conversation_id
        LEFT JOIN users u2 ON m2.sender_id = u2.id
        WHERE m.conversation_id = ?
        ORDER BY m.timestamp ASC
    """, (conversation_id,))
    messages = [
        {
            "sender": row['username'],
            "message": row['message'],
            "image": row['image'],
            "timestamp": row['timestamp'],
            "status": row['status'],
            "replyTo": {"sender": row['username_1'], "message": row['message_1'], "timestamp": row['timestamp_1']} if row['message_1'] else None
        }
        for row in c.fetchall()
    ]
    conn.close()
    return jsonify({"messages": messages, "conversation_id": conversation_id})

@app.route('/api/profile/<user_id>')
def get_profile(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, created_at, avatar, birthday, gender, home FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return jsonify({
            "id": user['id'],
            "username": user['username'],
            "joined": time.strftime('%d/%m/%Y', time.localtime(user['created_at'])),
            "avatar": user['avatar'],
            "birthday": user['birthday'],
            "gender": user['gender'],
            "home": user['home'],
            "isOnline": user['id'] in connected_users,
            "isOwnProfile": user_id == session['user_id']
        })
    return jsonify({"error": "Usuario no encontrado"}), 404

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    new_username = request.form.get('username')
    new_id = request.form.get('id')
    birthday = request.form.get('birthday')
    gender = request.form.get('gender')
    home = request.form.get('home')
    avatar_file = request.files.get('avatar')
    conn = get_db_connection()
    c = conn.cursor()
    try:
        update_fields = []
        update_values = []
        if new_username and new_username != session['username']:
            update_fields.append("username = ?")
            update_values.append(new_username)
        if new_id and new_id != session['user_id']:
            update_fields.append("id = ?")
            update_values.append(new_id)
        if birthday:
            update_fields.append("birthday = ?")
            update_values.append(birthday)
        if gender:
            update_fields.append("gender = ?")
            update_values.append(gender)
        if home:
            update_fields.append("home = ?")
            update_values.append(home)
        if avatar_file:
            response = requests.put(f"https://transfer.sh/{avatar_file.filename}", data=avatar_file.read())
            if response.status_code == 200:
                avatar_url = response.text.strip()
                update_fields.append("avatar = ?")
                update_values.append(avatar_url)
            else:
                return jsonify({"error": "Error al subir el avatar"}), 500
        if update_fields:
            update_values.append(session['user_id'])
            query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ?"
            c.execute(query, update_values)
            conn.commit()
            if new_username:
                session['username'] = new_username
            if new_id:
                session['user_id'] = new_id
                if session['user_id'] in connected_users:
                    del connected_users[session['user_id']]
                connected_users[new_id] = new_id
            socketio.emit('users_update', get_users().get_json(), broadcast=True)
            socketio.emit('profile_updated', {
                "user_id": session['user_id'],
                "username": session['username']
            }, broadcast=True)
            return jsonify({"success": True})
        return jsonify({"error": "No se enviaron datos para actualizar"}), 400
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Nombre de usuario o ID ya existe"}), 400
    finally:
        conn.close()

@app.route('/api/profile/delete', methods=['POST'])
def delete_profile():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM users WHERE id = ?", (session['user_id'],))
        conn.commit()
        session.clear()
        socketio.emit('users_update', get_users().get_json(), broadcast=True)
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/groups', methods=['POST'])
def create_group():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json()
    group_name = data.get('name')
    members = data.get('members', [])
    if not group_name or len(members) < 1:
        return jsonify({"error": "Nombre del grupo y al menos un miembro son requeridos"}), 400
    conn = get_db_connection()
    c = conn.cursor()
    conversation_id = f"conv_{uuid.uuid4()}"
    try:
        c.execute("INSERT INTO conversations (id, group_name, is_group, created_at) VALUES (?, ?, 1, ?)",
                  (conversation_id, group_name, time.time()))
        for member_id in members + [session['user_id']]:
            c.execute("INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?, ?)",
                      (conversation_id, member_id))
        conn.commit()
        socketio.emit('users_update', get_users().get_json(), broadcast=True)
        return jsonify({"success": True, "conversation_id": conversation_id})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Error al crear el grupo"}), 500
    finally:
        conn.close()

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return jsonify({"error": "No autenticado"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "No se envió archivo"}), 400
    file = request.files['file']
    conversation_id = request.form.get('conversation_id')
    receiver_id = request.form.get('receiver_id')
    is_group = request.form.get('is_group') == 'true'
    timestamp = float(request.form.get('timestamp', time.time()))
    
    response = requests.put(f"https://transfer.sh/{file.filename}", data=file.read())
    if response.status_code != 200:
        return jsonify({"error": "Error al subir el archivo a transfer.sh"}), 500
    
    file_url = response.text.strip()
    
    conn = get_db_connection()
    c = conn.cursor()
    message_id = f"msg_{uuid.uuid4()}"
    initial_status = 'delivered' if receiver_id in connected_users else 'sent'
    c.execute("""
        INSERT INTO messages (id, conversation_id, sender_id, message, image, timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (message_id, conversation_id, session['user_id'], "Multimedia", file_url, timestamp, initial_status))
    conn.commit()

    message_data = {
        "sender": session['username'],
        "message": "Multimedia",
        "image": file_url,
        "timestamp": timestamp,
        "conversation_id": conversation_id,
        "status": initial_status
    }

    emit('private_message', message_data, room=session['user_id'])

    c.execute("SELECT is_group FROM conversations WHERE id = ?", (conversation_id,))
    is_group_result = c.fetchone()
    if is_group_result and is_group_result['is_group']:
        c.execute("SELECT user_id FROM conversation_members WHERE conversation_id = ? AND user_id != ?", 
                  (conversation_id, session['user_id']))
        members = [row['user_id'] for row in c.fetchall()]
        for member_id in members:
            if member_id in connected_users:
                emit('private_message', message_data, room=member_id)
    else:
        if receiver_id and receiver_id in connected_users:
            emit('private_message', message_data, room=receiver_id)
            emit('message_status_update', {
                "conversation_id": conversation_id,
                "timestamp": timestamp,
                "status": "delivered"
            }, room=session['user_id'])
    
    conn.close()
    return jsonify({"success": True, "url": file_url})

@socketio.on('connect')
def handle_connect():
    if 'user_id' not in session:
        return False
    connected_users[session['user_id']] = session['user_id']
    join_room(session['user_id'])
    socketio.emit('users_update', get_users().get_json(), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session and session['user_id'] in connected_users:
        del connected_users[session['user_id']]
    socketio.emit('users_update', get_users().get_json(), broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    if 'user_id' not in session:
        return
    receiver_id = data.get('receiver_id')
    message = data.get('message')
    image = data.get('image')
    sender = data.get('sender')
    conversation_id = data.get('conversation_id')
    timestamp = data.get('timestamp')
    reply_to = data.get('replyTo', {})
    is_group = data.get('isGroup', False)
    if not message or not timestamp:
        return
    if not is_group and not conversation_id:
        if not receiver_id:
            return
        conversation_id = f"conv_{min(session['user_id'], receiver_id)}_{max(session['user_id'], receiver_id)}"
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO conversations (id, user1_id, user2_id, is_group, created_at) VALUES (?, ?, ?, 0, ?)",
                  (conversation_id, session['user_id'], receiver_id, time.time()))
        conn.commit()
        conn.close()
    conn = get_db_connection()
    c = conn.cursor()
    message_id = f"msg_{uuid.uuid4()}"
    initial_status = 'delivered' if receiver_id in connected_users else 'sent'
    c.execute("""
        INSERT INTO messages (id, conversation_id, sender_id, message, image, timestamp, status, reply_to_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (message_id, conversation_id, session['user_id'], message, image, timestamp, initial_status, 
          reply_to.get('timestamp') if reply_to else None))
    conn.commit()
    message_data = {
        "sender": sender,
        "message": message,
        "image": image,
        "timestamp": timestamp,
        "conversation_id": conversation_id,
        "status": initial_status,
        "replyTo": reply_to if reply_to else None
    }
    emit('private_message', message_data, room=session['user_id'])
    c.execute("SELECT is_group FROM conversations WHERE id = ?", (conversation_id,))
    is_group_result = c.fetchone()
    if is_group_result and is_group_result['is_group']:
        c.execute("SELECT user_id FROM conversation_members WHERE conversation_id = ? AND user_id != ?", 
                  (conversation_id, session['user_id']))
        members = [row['user_id'] for row in c.fetchall()]
        for member_id in members:
            if member_id in connected_users:
                emit('private_message', message_data, room=member_id)
    else:
        if receiver_id and receiver_id in connected_users:
            emit('private_message', message_data, room=receiver_id)
            emit('message_status_update', {
                "conversation_id": conversation_id,
                "timestamp": timestamp,
                "status": "delivered"
            }, room=session['user_id'])
    conn.close()

@socketio.on('message_status')
def handle_message_status(data):
    if 'user_id' not in session:
        return
    conversation_id = data.get('conversation_id')
    status = data.get('status')
    timestamp = data.get('timestamp')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE messages 
        SET status = ? 
        WHERE conversation_id = ? AND sender_id != ? AND timestamp = ? AND status != 'seen'
    """, (status, conversation_id, session['user_id'], timestamp))
    conn.commit()
    c.execute("SELECT timestamp, status FROM messages WHERE conversation_id = ? AND timestamp = ?", 
              (conversation_id, timestamp))
    updated_message = c.fetchone()
    conn.close()
    if updated_message:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT user_id FROM conversation_members WHERE conversation_id = ? 
            UNION SELECT user1_id FROM conversations WHERE id = ? 
            UNION SELECT user2_id FROM conversations WHERE id = ?
        """, (conversation_id, conversation_id, conversation_id))
        members = [row['user_id'] for row in c.fetchall()]
        conn.close()
        for member_id in members:
            if member_id in connected_users and member_id != session['user_id']:
                emit('message_status_update', {
                    "conversation_id": conversation_id,
                    "status": updated_message['status'],
                    "timestamp": updated_message['timestamp']
                }, room=member_id)

@socketio.on('mark_all_as_seen')
def handle_mark_all_as_seen(data):
    if 'user_id' not in session:
        return
    conversation_id = data.get('conversation_id')
    conn = get_db_connection()
    c = co