from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import uvicorn

app = FastAPI()

# Base de datos SQLite
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT)''')
    conn.commit()
    conn.close()

init_db()

class User(BaseModel):
    username: str
    password: str

# Conexiones WebSocket activas
clients = {}

@app.get("/", response_class=HTMLResponse)
async def get():
    with open("index.html") as f:
        return f.read()

@app.post("/register")
async def register(user: User):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", 
                 (user.username, user.password))
        conn.commit()
        # Notificar a todos los clientes sobre el nuevo usuario
        for client in clients.values():
            await client.send_text(f'{{"type": "new_user", "username": "{user.username}"}}')
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    finally:
        conn.close()
    return {"message": "Usuario registrado"}

@app.post("/login")
async def login(user: User):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", 
             (user.username, user.password))
    result = c.fetchone()
    conn.close()
    if not result:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    return {"message": "Login exitoso"}

@app.get("/users")
async def get_users():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users")
    users = [{"username": row[0]} for row in c.fetchall()]
    conn.close()
    return users

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    clients[username] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            message = eval(data)  # Convertir string a dict
            if message['type'] == 'message' and message['to'] in clients:
                await clients[message['to']].send_text(data)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        del clients[username]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)