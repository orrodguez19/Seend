from flask import Flask, render_template, request, redirect, session, url_for
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secreto_seend'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///seend.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# MODELOS
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(64), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.String(64), nullable=False)

# CREAR BASE DE DATOS AL INICIAR
@app.before_first_request
def crear_tablas():
    db.create_all()

# RUTAS
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('auth'))

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        if request.path == '/login' or request.form.get('action') == 'login':
            user = User.query.filter_by(username=username, password=password).first()
            if user:
                session['username'] = username
                return redirect(url_for('chat'))
            error = "Credenciales inválidas"
        else:
            if User.query.filter_by(username=username).first():
                error = "El usuario ya existe"
            else:
                user = User(username=username, password=password)
                db.session.add(user)
                db.session.commit()
                session['username'] = username
                return redirect(url_for('chat'))

    return render_template('auth.html', error=error)

@app.route('/login', methods=['POST'])
def login_redirect():
    return auth()

@app.route('/register', methods=['POST'])
def register_redirect():
    return auth()

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('auth'))
    return render_template('chat.html', username=session['username'])

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('auth'))

# SOCKETS
@socketio.on('connect')
def handle_connect():
    messages = Message.query.order_by(Message.id).limit(50).all()
    formatted = [
        {'username': m.username, 'message': m.message, 'timestamp': m.timestamp}
        for m in messages
    ]
    emit('load_messages', formatted)

@socketio.on('send_message')
def handle_message(data):
    username = data.get('username')
    message = data.get('message')
    timestamp = datetime.now().strftime('%H:%M')
    msg = Message(username=username, message=message, timestamp=timestamp)
    db.session.add(msg)
    db.session.commit()

    emit('receive_message', {
        'username': username,
        'message': message,
        'timestamp': timestamp
    }, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', data, broadcast=True, include_self=False)

# MAIN
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000)