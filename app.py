import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, disconnect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "seend-secret")
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///seend.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    online = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.String(10), nullable=False)

# Create tables if not exist
with app.app_context():
    db.create_all()

# Routes
@app.route("/")
def index():
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.password == request.form["password"]:
            session["username"] = user.username
            return redirect("/chat")
    return render_template("auth.html", mode="login")

@app.route("/register", methods=["POST"])
def register():
    username = request.form["username"]
    password = request.form["password"]
    if not User.query.filter_by(username=username).first():
        db.session.add(User(username=username, password=password))
        db.session.commit()
        session["username"] = username
        return redirect("/chat")
    return "Usuario ya existe"

@app.route("/chat")
def chat():
    if "username" not in session:
        return redirect("/login")
    return render_template("chat.html", username=session["username"])

@app.route("/logout")
def logout():
    if "username" in session:
        user = User.query.filter_by(username=session["username"]).first()
        if user:
            user.online = False
            db.session.commit()
        session.pop("username")
    return redirect("/login")

# Socket.IO Events
connected_users = {}

@socketio.on("connect")
def handle_connect():
    if "username" in session:
        username = session["username"]
        connected_users[request.sid] = username
        user = User.query.filter_by(username=username).first()
        if user:
            user.online = True
            db.session.commit()
        emit_user_list()
        messages = Message.query.all()
        emit("load_messages", [
            {"username": m.username, "message": m.message, "timestamp": m.timestamp}
            for m in messages
        ])

@socketio.on("disconnect")
def handle_disconnect():
    username = connected_users.pop(request.sid, None)
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            user.online = False
            db.session.commit()
        emit_user_list()

@socketio.on("user_connected")
def user_connected(username):
    session["username"] = username
    join_room("global")
    emit_user_list()

@socketio.on("send_message")
def handle_send(data):
    msg = Message(username=data["username"], message=data["message"], timestamp=data["timestamp"])
    db.session.add(msg)
    db.session.commit()
    emit("receive_message", data, broadcast=True)

@socketio.on("typing")
def handle_typing(data):
    emit("user_typing", data, broadcast=True)

def emit_user_list():
    users = User.query.with_entities(User.username, User.online).all()
    emit("update_user_list", [{"username": u.username, "online": u.online} for u in users], broadcast=True)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)