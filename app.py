from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from pymongo import MongoClient
import os
from datetime import datetime
from werkzeug.utils import secure_filename
import jwt
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('JWT_SECRET', 'grgifHFQhEjiHjeJf849JFAJhfHF4VJS')
socketio = SocketIO(app)

# Configuración de MongoDB
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://orrodguez19:qnVW5zyeQuHO98CG@cluster.p6wa3.mongodb.net/?retryWrites=true&w=majority&appName=Cluster')
client = MongoClient(MONGO_URI)
db = client['seend_db']  # Nombre de la base de datos
users_collection = db['users']
messages_collection = db['messages']

# Configuración para subir imágenes
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Middleware para verificar token JWT
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return jsonify({'error': 'Token requerido'}), 401
        try:
            token = token.split(" ")[1]
            payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            request.user_id = payload['user_id']
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return render_template('chat.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form['action']
        username = request.form['username']
        password = request.form['password']
        
        if action == 'login':
            user = users_collection.find_one({"username": username, "password": password})
            if user:
                token = jwt.encode({'user_id': str(user['_id']), 'exp': datetime.utcnow().timestamp() + 3600}, app.secret_key, algorithm="HS256")
                return jsonify({'token': token, 'user_id': str(user['_id'])})
            return render_template('login.html', error="Usuario o contraseña incorrectos")
        elif action == 'register':
            email = request.form['email']
            if users_collection.find_one({"username": username}):
                return render_template('login.html', error="El usuario ya existe")
            user = {
                "username": username,
                "password": password,  # En producción, usa hashing
                "email": email,
                "bio": "Usuario nuevo",
                "phone": None,
                "dob": None,
                "profile_image": "https://www.svgrepo.com/show/452030/avatar-default.svg"
            }
            result = users_collection.insert_one(user)
            token = jwt.encode({'user_id': str(result.inserted_id), 'exp': datetime.utcnow().timestamp() + 3600}, app.secret_key, algorithm="HS256")
            return jsonify({'token': token, 'user_id': str(result.inserted_id)})
    return render_template('login.html')

@app.route('/logout')
def logout():
    return redirect(url_for('login'))

@app.route('/api/users', methods=['GET'])
@token_required
def get_users():
    users = list(users_collection.find())
    return jsonify([{
        'id': str(user['_id']),
        'name': user['username'],
        'email': user['email'],
        'bio': user.get('bio', 'Usuario nuevo'),
        'phone': user.get('phone'),
        'dob': user.get('dob'),
        'profile_image': user.get('profile_image', 'https://www.svgrepo.com/show/452030/avatar-default.svg'),
        'lastSeen': 'En línea',
        'isOnline': True
    } for user in users])

@app.route('/api/messages/<receiver_id>', methods=['GET'])
@token_required
def get_messages(receiver_id):
    messages = list(messages_collection.find({
        "$or": [
            {"sender_id": request.user_id, "receiver_id": receiver_id},
            {"sender_id": receiver_id, "receiver_id": request.user_id}
        ]
    }).sort("timestamp", 1))
    return jsonify([{
        'id': str(msg['_id']),
        'sender_id': msg['sender_id'],
        'receiver_id': msg['receiver_id'],
        'text': msg['text'],
        'timestamp': msg['timestamp'],
        'status': msg.get('status', 'sent'),
        'is_read': msg.get('is_read', 0)
    } for msg in messages])

@app.route('/api/update_profile', methods=['POST'])
@token_required
def update_profile():
    data = request.get_json()
    users_collection.update_one({"_id": ObjectId(request.user_id)}, {"$set": data})
    return jsonify({'success': True})

@app.route('/api/update_profile_image', methods=['POST'])
@token_required
def update_profile_image():
    if 'profile_image' not in request.files:
        return jsonify({'error': 'No se proporcionó ninguna imagen'}), 400
    
    file = request.files['profile_image']
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{request.user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        image_url = url_for('static', filename=f'uploads/{unique_filename}', _external=True)
        
        users_collection.update_one({"_id": ObjectId(request.user_id)}, {"$set": {"profile_image": image_url}})
        return jsonify({'success': True, 'image_url': image_url})
    
    return jsonify({'error': 'Formato de archivo no permitido'}), 400

@app.route('/api/delete_chat/<chat_id>', methods=['DELETE'])
@token_required
def delete_chat(chat_id):
    messages_collection.delete_many({
        "$or": [
            {"sender_id": request.user_id, "receiver_id": chat_id},
            {"sender_id": chat_id, "receiver_id": request.user_id}
        ]
    })
    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    if 'Authorization' in request.headers:
        token = request.headers['Authorization'].split(" ")[1]
        try:
            payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            join_room(payload['user_id'])
            emit('user_status', {'userId': payload['user_id'], 'isOnline': True, 'lastSeen': datetime.now().strftime('%H:%M')}, broadcast=True)
        except jwt.InvalidTokenError:
            pass

@socketio.on('disconnect')
def handle_disconnect():
    if 'Authorization' in request.headers:
        token = request.headers['Authorization'].split(" ")[1]
        try:
            payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            leave_room(payload['user_id'])
            emit('user_status', {'userId': payload['user_id'], 'isOnline': False, 'lastSeen': datetime.now().strftime('%H:%M')}, broadcast=True)
        except jwt.InvalidTokenError:
            pass

@socketio.on('send_message')
def handle_message(data):
    if 'Authorization' not in request.headers:
        return
    token = request.headers['Authorization'].split(" ")[1]
    payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
    sender_id = payload['user_id']
    
    message = {
        "sender_id": sender_id,
        "receiver_id": data['receiver_id'],
        "text": data['text'],
        "timestamp": data['timestamp'],
        "status": "sent",
        "is_read": 0
    }
    result = messages_collection.insert_one(message)
    message['_id'] = str(result.inserted_id)
    message['id'] = message['_id']
    
    emit('new_message', message, room=data['receiver_id'])
    emit('new_message', message, room=sender_id)

@socketio.on('create_group')
def handle_group_creation(data):
    if 'Authorization' not in request.headers:
        return
    token = request.headers['Authorization'].split(" ")[1]
    payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
    creator_id = payload['user_id']
    
    group_data = {
        'id': data['id'],
        'name': data['name'],
        'creatorId': creator_id,
        'members': data['members'],
        'isGroup': True,
        'lastMessage': 'Grupo creado',
        'unreadCount': 0
    }
    
    for member_id in data['members']:
        emit('new_chat', group_data, room=str(member_id))

@socketio.on('message_delivered')
def handle_delivered(data):
    messages_collection.update_one({"_id": ObjectId(data['messageId'])}, {"$set": {"status": "delivered"}})
    emit('message_delivered', data, room=data['receiver_id'])

@socketio.on('message_read')
def handle_read(data):
    messages_collection.update_one({"_id": ObjectId(data['messageId'])}, {"$set": {"status": "read", "is_read": 1}})
    emit('message_read', data, room=data['receiver_id'])

@socketio.on('typing')
def handle_typing(data):
    emit('typing', data, room=str(data['chatId']))

@socketio.on('profile_update')
def handle_profile_update(data):
    emit('profile_update', data, broadcast=True)

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, depuración=False, allow_unsafe_werkzeug=True)
