from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room, send
from flask import request
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'  # ¡Cambiar esto en producción!
socketio = SocketIO(app, cors_allowed_origins="*") # Permitir conexiones desde cualquier origen (¡Cuidado en producción!)

users = {}

@socketio.on('connect')
def handle_connect():
    user_id = str(uuid.uuid4())[:8]
    users[request.sid] = user_id
    emit('userList', list(users.values()), broadcast=True)
    emit('userConnected', user_id, broadcast=True, include_self=False)

@socketio.on('sendMessage')
def handle_send_message(data):
    receiver_socket_id = data['receiverSocketId']
    message = data['message']
    sender_id = users[request.sid]
    emit('receiveMessage', {'senderId': sender_id, 'message': message}, room=receiver_socket_id)

@socketio.on('disconnect')
def handle_disconnect():
    disconnected_user_id = users.get(request.sid)
    if disconnected_user_id:
        del users[request.sid]
        emit('userDisconnected', disconnected_user_id, broadcast=True)

@app.route('/')
def index():
    return render_template('chat.html')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
