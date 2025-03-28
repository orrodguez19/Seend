import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Configuración inicial
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('JWT_SECRET', 'default-secret-key')
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='None',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

# Socket.IO configurado para Render
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   async_mode='eventlet',
                   logger=True,
                   engineio_logger=True)

# Conexión a MongoDB Atlas
mongo_uri = os.environ.get('MONGO_URI')
client = MongoClient(mongo_uri, connectTimeoutMS=30000, socketTimeoutMS=None)
db = client.get_database('seend')

# Colecciones
users_collection = db.users
messages_collection = db.messages
groups_collection = db.groups

# Crear índices (solo una vez al inicio)
if 'users' not in db.list_collection_names():
    users_collection.create_index('username', unique=True)
    users_collection.create_index('email', unique=True)
    messages_collection.create_index([('sender_id', 1), ('receiver_id', 1)])
    groups_collection.create_index('members')

# Helpers
def get_current_user():
    if 'user_id' not in session:
        return None
    return users_collection.find_one({'_id': ObjectId(session['user_id'])})

# Rutas principales
@app.route('/')
def index():
    if not get_current_user():
        return redirect(url_for('login'))
    return render_template('chat.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if action == 'login':
            user = users_collection.find_one({'username': username})
            if user and check_password_hash(user['password'], password):
                session['user_id'] = str(user['_id'])
                session['username'] = user['username']
                return redirect(url_for('index'))
            return render_template('login.html', error="Credenciales inválidas")

        elif action == 'register':
            email = request.form.get('email', '').strip()
            if not email:
                return render_template('login.html', error="Email es requerido")

            existing_user = users_collection.find_one({'$or': [
                {'username': username},
                {'email': email}
            ]})
            if existing_user:
                return render_template('login.html', error="Usuario o email ya existen")

            new_user = {
                'username': username,
                'password': generate_password_hash(password),
                'email': email,
                'profile_image': 'https://www.svgrepo.com/show/452030/avatar-default.svg',
                'last_online': datetime.utcnow(),
                'created_at': datetime.utcnow(),
                'is_online': True
            }
            result = users_collection.insert_one(new_user)
            session['user_id'] = str(result.inserted_id)
            return redirect(url_for('index'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        users_collection.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {'is_online': False}}
        )
    session.clear()
    return redirect(url_for('login'))

# API Endpoints
@app.route('/api/users', methods=['GET'])
def api_users():
    if not get_current_user():
        return jsonify({'error': 'No autenticado'}), 401

    users = list(users_collection.find(
        {'_id': {'$ne': ObjectId(session['user_id'])}},
        {'username': 1, 'profile_image': 1, 'is_online': 1, 'last_online': 1}
    ))

    formatted_users = []
    for user in users:
        formatted_users.append({
            'id': str(user['_id']),
            'name': user['username'],
            'profile_image': user.get('profile_image'),
            'isOnline': user.get('is_online', False),
            'lastSeen': user.get('last_online', datetime.utcnow()).strftime('%H:%M')
        })

    return jsonify(formatted_users)

@app.route('/api/messages/<receiver_id>', methods=['GET'])
def api_messages(receiver_id):
    if not get_current_user():
        return jsonify({'error': 'No autenticado'}), 401

    messages = list(messages_collection.find({
        '$or': [
            {'sender_id': ObjectId(session['user_id']), 'receiver_id': ObjectId(receiver_id)},
            {'sender_id': ObjectId(receiver_id), 'receiver_id': ObjectId(session['user_id'])}
        ]
    }).sort('timestamp', 1))

    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            'id': str(msg['_id']),
            'sender_id': str(msg['sender_id']),
            'receiver_id': str(msg['receiver_id']),
            'text': msg['text'],
            'timestamp': msg['timestamp'].isoformat(),
            'status': msg.get('status', 'sent')
        })

    return jsonify(formatted_messages)

@app.route('/api/update_profile', methods=['POST'])
def api_update_profile():
    if not get_current_user():
        return jsonify({'error': 'No autenticado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400

    updates = {}
    for field in ['username', 'email', 'bio', 'phone', 'dob']:
        if field in data:
            updates[field] = data[field]

    if updates:
        users_collection.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': updates}
        )

    return jsonify({'success': True})

@app.route('/api/upload_profile_image', methods=['POST'])
def api_upload_profile_image():
    if not get_current_user():
        return jsonify({'error': 'No autenticado'}), 401

    if 'image' not in request.files:
        return jsonify({'error': 'No se subió archivo'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'Archivo no válido'}), 400

    # Guardar archivo localmente (en producción usa S3/Cloudinary)
    os.makedirs('static/uploads', exist_ok=True)
    filename = f"user_{session['user_id']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"
    filepath = os.path.join('static', 'uploads', filename)
    file.save(filepath)

    image_url = f'/static/uploads/{filename}'
    users_collection.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$set': {'profile_image': image_url}}
    )

    return jsonify({
        'success': True,
        'imageUrl': image_url
    })

# WebSocket Handlers
@socketio.on('connect')
def handle_connect():
    user = get_current_user()
    if user:
        join_room(str(user['_id']))
        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'is_online': True, 'last_online': datetime.utcnow()}}
        )
        emit('user_status', {
            'userId': str(user['_id']),
            'isOnline': True,
            'lastSeen': datetime.utcnow().strftime('%H:%M')
        }, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user = get_current_user()
    if user:
        leave_room(str(user['_id']))
        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'is_online': False}}
        )
        emit('user_status', {
            'userId': str(user['_id']),
            'isOnline': False,
            'lastSeen': datetime.utcnow().strftime('%H:%M')
        }, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    user = get_current_user()
    if not user:
        return

    message = {
        'sender_id': user['_id'],
        'receiver_id': ObjectId(data['receiver_id']),
        'text': data['text'],
        'timestamp': datetime.utcnow(),
        'status': 'sent'
    }

    result = messages_collection.insert_one(message)
    message['_id'] = str(result.inserted_id)
    message['sender_id'] = str(user['_id'])
    message['receiver_id'] = data['receiver_id']

    emit('new_message', message, room=message['receiver_id'])
    emit('new_message', message, room=str(user['_id']))

@socketio.on('create_group')
def handle_create_group(data):
    user = get_current_user()
    if not user:
        return

    group_data = {
        'name': data['name'],
        'creator_id': user['_id'],
        'members': [ObjectId(m) for m in data['members']] + [user['_id']],
        'created_at': datetime.utcnow()
    }

    result = groups_collection.insert_one(group_data)
    group_id = str(result.inserted_id)

    for member_id in group_data['members']:
        emit('new_chat', {
            'id': group_id,
            'name': group_data['name'],
            'isGroup': True,
            'lastMessage': 'Grupo creado'
        }, room=str(member_id))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if os.environ.get('RENDER'):
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        socketio.run(app, debug=True, port=port)
