from flask import Flask, render_template, request, redirect, url_for, jsonify
from pusher import Pusher
import firebase_admin
from firebase_admin import credentials, firestore
import os
from datetime import datetime
import jwt
from functools import wraps

app = Flask(__name__)
app.secret_key = 'grgifHFQhEjiHjeJf849JFAJhfHF4VJS'

# Configuración de Pusher
pusher_client = Pusher(
    app_id='1966597',
    key='10ace857b488cb959660',
    secret='1291c3c2b2bbd0063278',
    cluster='us3',
    ssl=True
)

# Configuración de Firebase
firebase_credentials = {
    "type": "service_account",
    "project_id": "seend-bfb1f",
    "private_key_id": "d2cc4c9e6abf22c312e6f50eba5c8ae547f09718",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDD34y9tbSV5myW\nzWg7RBHkRZymrt4arho3ilTwHNtOG8WrZVm+x+iYUJ+gNEKcvopUyUO537iq3P/2\nOeCyJc53oJNocR6YgRkd6uS/Lo/ogUHOBC6W+9+jy+Ijmm8W7yDfvxMhpagiU5m7\ng4HN+BbKMWdENsTwl+tOE9TgLydbuUHgWIRlU3wobH/zi6tAcPSIXZXclZdWqP0f\nJnIdcJ6qkO+lhKJSOUw90HMdI8lbJTQCruDT6Ad4woEKFZX40weNKQudmAMfvorq\nSWHe78NnPHUkvOM497ymjAdbz5nZVd5LIQTZ1gin34x97efgVZlF4lBzr4iWFITs\nhoJaiutJAgMBAAECggEAAjLvic6xKxCl7fB659VtDP7CEjX63NpRBYgaSYLNbHxP\n1QuDfSqR4CnhjOMhT1CtTWPgDIVoNZTbE8jVDrLxdTLajMzeTtB+N3GEZWgQqgfP\ndRBjdIL54QUgMg2hCyUenZxvyswpDc+Z9Xq1uZn8KYNx+RhTUC8ob102IdktrDAs\ncWUD7LxFlaglXr1PJXS2It/R1/tHZ5OJPZnufLhRegWhaYjqDEZv10Mx4qTdm2XB\nErfp4SlgPfiJEQgyJ2nIlnya7rxiXMhJQxOhzLNnSzay+ZoWPTmpuhgWT7soLQJR\nGSOo2WTBPJdT/vzbzf7eF1IKBxD7BeaPxV9w5sGhDQKBgQD3VWAr61MVYOJdjl4L\nliVEj1cmyQhtsZZw7OT38se1QA+9B7AgXTeRAgPlxulKmKbHryQGKRyn1F4QV31x\nu88zZUxS7m845KFJ5ViJeQrNJRFDr7fSCWlt4xdy1YtkwhuQCag2TA8iBEwXmZfR\nT0B8fgq6+alEMgwO/EMdBRfZQKBgQDKvJERq22hsaA4Ln0U6s1Du3RO9e75gUE8\nYd09DLehiL0RKAY8INpfkWGB/2qC1/DR74NW22rwhvtC1R+Z5HwhTifnzImSPawR\n1WVzHg9pvDZvjCL1amR76CQmoygkrfoo3fUG5v0MRUK0BVrFSRXHNTmriM8sgsvy\nFyJVmm04FQKBgG1rDrW/UK03hE1BS2eyz9/pzfNxolHs65IfqxfqBuGvaocE3K0k\nsA1tp83CVrjSmY3jdHtpOq0grVBrdCqZnIuvN7nEk93Gf3gShz2iF94zlNSt6xN3\naHXdriT2RcmYedsZ+pmywksZPZR/NYO6nNu2YwbepjxuK5mBkQQa4lxlAoGBAIgq\nSEEW44ZTV+oEB0yyO3U/hOm3sm7vylH05PQpA3jB70KDoFRoOGMxsMzwMKh6wqst\n9Ae1TUkJT97eZ+Ajnt97r7+3F7saIuTDb+T2jqGUoPcgpyYv9Bdonkc5FDA2jas/\nEGA3akQAjMF+Sy3wXWkz rW0xcPxTSQLrUksucibVAoGADPTVE2cROX/fVQohYfMO\n1OPB0PZBwAcL+eH8U1uWKBI+1fzsSwGDjGMHQbUZ5idWrFl7wY+WlrXseOq87Ze8\nYxuDrJ6aJtBB9EYdmXxYyb22nFBRI6OZZ7llGMj4EJNZjEgN5tnrV9fJ/QNYnsTN\nuEM4GafHbRjiqSuGGQ5MZYg=\n-----END PRIVATE KEY-----\n",
    "client_email": "firebase-adminsdk-fbsvc@seend-bfb1f.iam.gserviceaccount.com",
    "client_id": "100943113266247396761",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40seend-bfb1f.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}
cred = credentials.Certificate(firebase_credentials)
firebase_admin.initialize_app(cred)
db = firestore.client()
users_collection = db.collection('users')
messages_collection = db.collection('messages')

# Configuración para subir imágenes
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función personalizada para reemplazar secure_filename
def sanitize_filename(filename):
    """Sanitiza un nombre de archivo para hacerlo seguro."""
    keepcharacters = ('-', '_', '.')
    sanitized = ''.join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()
    return os.path.basename(sanitized)

# Middleware para verificar token JWT
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith('Bearer '):
            return redirect(url_for('login'))
        try:
            token = token.split(" ")[1]
            payload = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            request.user_id = payload['user_id']
        except jwt.InvalidTokenError:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
@token_required
def index():
    return render_template('chat.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            if 'action' not in request.form or 'username' not in request.form or 'password' not in request.form:
                return jsonify({'error': 'Faltan campos requeridos: action, username o password', 'success': False}), 400
            
            action = request.form['action']
            username = request.form['username']
            password = request.form['password']
            
            if action == 'login':
                user_ref = users_collection.where('username', '==', username).where('password', '==', password).get()
                if user_ref:
                    user = user_ref[0].to_dict()
                    user_id = user_ref[0].id
                    token = jwt.encode({'user_id': user_id, 'exp': int(datetime.utcnow().timestamp() + 3600)}, app.secret_key, algorithm="HS256")
                    return jsonify({'token': token, 'user_id': user_id, 'success': True})
                return jsonify({'error': 'Usuario o contraseña incorrectos', 'success': False}), 401
            elif action == 'register':
                if 'email' not in request.form:
                    return jsonify({'error': 'El campo email es requerido para registro', 'success': False}), 400
                email = request.form['email']
                if users_collection.where('username', '==', username).get():
                    return jsonify({'error': 'El usuario ya existe', 'success': False}), 400
                user = {
                    "username": username,
                    "password": password,
                    "email": email,
                    "bio": "Usuario nuevo",
                    "phone": None,
                    "dob": None,
                    "profile_image": "https://www.svgrepo.com/show/452030/avatar-default.svg"
                }
                user_ref = users_collection.document()
                user_ref.set(user)
                user_id = user_ref.id
                token = jwt.encode({'user_id': user_id, 'exp': int(datetime.utcnow().timestamp() + 3600)}, app.secret_key, algorithm="HS256")
                return jsonify({'token': token, 'user_id': user_id, 'success': True})
            else:
                return jsonify({'error': 'Acción inválida', 'success': False}), 400
        except Exception as e:
            return jsonify({'error': f'Error del servidor: {str(e)}', 'success': False}), 500
    return render_template('login.html')

@app.route('/logout')
def logout():
    return redirect(url_for('login'))

@app.route('/pusher-auth', methods=['POST'])
@token_required
def pusher_auth():
    channel_name = request.form['channel_name']
    socket_id = request.form['socket_id']
    auth = pusher_client.authenticate(channel_name, socket_id)
    return jsonify(auth)

@app.route('/api/users', methods=['GET'])
@token_required
def get_users():
    users = users_collection.get()
    return jsonify([{
        'id': user.id,
        'name': user.to_dict()['username'],
        'email': user.to_dict()['email'],
        'bio': user.to_dict().get('bio', 'Usuario nuevo'),
        'phone': user.to_dict().get('phone'),
        'dob': user.to_dict().get('dob'),
        'profile_image': user.to_dict().get('profile_image', 'https://www.svgrepo.com/show/452030/avatar-default.svg'),
        'lastSeen': 'En línea',  # Simplificado
        'isOnline': True         # Simplificado
    } for user in users])

@app.route('/api/messages/<receiver_id>', methods=['GET'])
@token_required
def get_messages(receiver_id):
    messages = messages_collection.where('sender_id', '==', request.user_id).where('receiver_id', '==', receiver_id).get() + \
               messages_collection.where('sender_id', '==', receiver_id).where('receiver_id', '==', request.user_id).get()
    messages = sorted(messages, key=lambda x: x.to_dict()['timestamp'])
    return jsonify([{
        'id': msg.id,
        'sender_id': msg.to_dict()['sender_id'],
        'receiver_id': msg.to_dict()['receiver_id'],
        'text': msg.to_dict()['text'],
        'timestamp': msg.to_dict()['timestamp'],
        'status': msg.to_dict().get('status', 'sent'),
        'is_read': msg.to_dict().get('is_read', 0)
    } for msg in messages])

@app.route('/api/send_message', methods=['POST'])
@token_required
def send_message():
    data = request.get_json()
    sender_id = request.user_id
    message = {
        "sender_id": sender_id,
        "receiver_id": data['receiver_id'],
        "text": data['text'],
        "timestamp": datetime.utcnow().isoformat(),
        "status": "sent",
        "is_read": 0
    }
    doc_ref = messages_collection.document()
    doc_ref.set(message)
    message['id'] = doc_ref.id

    # Enviar mensaje a través de Pusher
    pusher_client.trigger(f'private-{data["receiver_id"]}', 'new_message', message)
    pusher_client.trigger(f'private-{sender_id}', 'new_message', message)
    return jsonify({'success': True, 'message': message})

@app.route('/api/update_profile', methods=['POST'])
@token_required
def update_profile():
    data = request.get_json()
    users_collection.document(request.user_id).update(data)
    pusher_client.trigger(f'private-{request.user_id}', 'profile_update', data)
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
        # Usar sanitize_filename en lugar de secure_filename
        filename = sanitize_filename(file.filename)
        unique_filename = f"{request.user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        image_url = url_for('static', filename=f'uploads/{unique_filename}', _external=True)
        
        users_collection.document(request.user_id).update({"profile_image": image_url})
        pusher_client.trigger(f'private-{request.user_id}', 'profile_update', {'profile_image': image_url})
        return jsonify({'success': True, 'image_url': image_url})
    
    return jsonify({'error': 'Formato de archivo no permitido'}), 400

@app.route('/api/delete_chat/<chat_id>', methods=['DELETE'])
@token_required
def delete_chat(chat_id):
    messages = messages_collection.where('sender_id', '==', request.user_id).where('receiver_id', '==', chat_id).get() + \
               messages_collection.where('sender_id', '==', chat_id).where('receiver_id', '==', request.user_id).get()
    for msg in messages:
        messages_collection.document(msg.id).delete()
    return jsonify({'success': True})

@app.route('/api/user_status', methods=['POST'])
@token_required
def update_user_status():
    data = request.get_json()
    status_data = {
        'userId': request.user_id,
        'isOnline': data.get('isOnline', True),
        'lastSeen': datetime.now().strftime('%H:%M')
    }
    pusher_client.trigger('presence-users', 'user_status', status_data)
    return jsonify({'success': True})

@app.route('/api/delete_account', methods=['DELETE'])
@token_required
def delete_account():
    try:
        # Eliminar mensajes del usuario
        sent_messages = messages_collection.where('sender_id', '==', request.user_id).get()
        received_messages = messages_collection.where('receiver_id', '==', request.user_id).get()
        for msg in sent_messages + received_messages:
            messages_collection.document(msg.id).delete()
        
        # Eliminar usuario
        users_collection.document(request.user_id).delete()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
