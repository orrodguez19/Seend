from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from firebase_admin import credentials, firestore, initialize_app  # Importaciones corregidas
from pusher import Pusher
from datetime import datetime, timedelta
import os
import jwt
import json
from typing import Optional

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración desde variables de entorno
firebase_config = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
cred = credentials.Certificate(firebase_config)
firebase_app = initialize_app(cred)  # Inicialización simplificada
db = firestore.client()
users_collection = db.collection('users')
messages_collection = db.collection('messages')

pusher_client = Pusher(
    app_id=os.getenv("PUSHER_APP_ID"),
    key=os.getenv("PUSHER_KEY"),
    secret=os.getenv("PUSHER_SECRET"),
    cluster=os.getenv("PUSHER_CLUSTER"),
    ssl=True
)

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Helper functions
def sanitize_filename(filename: str) -> str:
    keepcharacters = ('-', '_', '.')
    return "".join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")
        return {"user_id": user_id}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")

# Rutas principales
@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_page():
    return FileResponse("templates/login.html")

@app.get("/chat")
async def chat_interface(current_user: dict = Depends(get_current_user)):
    return FileResponse("templates/chat.html")

# Sistema de autenticación
@app.post("/login")
async def auth_handler(
    action: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    email: Optional[str] = Form(None)
):
    try:
        if action == "login":
            query = users_collection.where('username', '==', username).where('password', '==', password)
            user_ref = list(query.stream())
            
            if not user_ref:
                return JSONResponse({"error": "Credenciales incorrectas", "success": False}, status_code=401)
            
            user = user_ref[0].to_dict()
            token = jwt.encode({
                'user_id': user_ref[0].id,
                'exp': datetime.utcnow() + timedelta(hours=1)
            }, SECRET_KEY, algorithm=ALGORITHM)
            
            return JSONResponse({"token": token, "user_id": user_ref[0].id, "success": True})

        elif action == "register":
            if not email:
                return JSONResponse({"error": "Email requerido", "success": False}, status_code=400)
            
            if list(users_collection.where('username', '==', username).stream()):
                return JSONResponse({"error": "Usuario ya existe", "success": False}, status_code=400)
            
            user_data = {
                "username": username,
                "password": password,
                "email": email,
                "bio": "Usuario nuevo",
                "phone": None,
                "dob": None,
                "profile_image": "https://www.svgrepo.com/show/452030/avatar-default.svg"
            }
            
            user_ref = users_collection.document()
            user_ref.set(user_data)
            token = jwt.encode({
                'user_id': user_ref.id,
                'exp': datetime.utcnow() + timedelta(hours=1)
            }, SECRET_KEY, algorithm=ALGORITHM)
            
            return JSONResponse({"token": token, "user_id": user_ref.id, "success": True})

        return JSONResponse({"error": "Acción inválida", "success": False}, status_code=400)
    
    except Exception as e:
        return JSONResponse({"error": f"Error del servidor: {str(e)}", "success": False}, status_code=500)

# Endpoints API
@app.get("/api/users")
async def get_users(current_user: dict = Depends(get_current_user)):
    users = users_collection.stream()
    return JSONResponse([{
        'id': user.id,
        'name': user.to_dict()['username'],
        'email': user.to_dict()['email'],
        'bio': user.to_dict().get('bio', 'Usuario nuevo'),
        'phone': user.to_dict().get('phone'),
        'dob': user.to_dict().get('dob'),
        'profile_image': user.to_dict().get('profile_image', 'https://www.svgrepo.com/show/452030/avatar-default.svg'),
        'lastSeen': 'En línea',
        'isOnline': True
    } for user in users])

@app.get("/api/messages/{receiver_id}")
async def get_messages(
    receiver_id: str,
    current_user: dict = Depends(get_current_user)
):
    messages = messages_collection.where(
        "sender_id", "in", [current_user["user_id"], receiver_id]
    ).where(
        "receiver_id", "in", [current_user["user_id"], receiver_id]
    ).order_by("timestamp").stream()
    
    return JSONResponse([{
        "id": msg.id,
        "sender_id": msg.to_dict().get("sender_id"),
        "receiver_id": msg.to_dict().get("receiver_id"),
        "text": msg.to_dict().get("text"),
        "timestamp": msg.to_dict().get("timestamp"),
    } for msg in messages])

@app.post("/api/send_message")
async def send_message(
    receiver_id: str = Form(...),
    text: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    message = {
        "sender_id": current_user["user_id"],
        "receiver_id": receiver_id,
        "text": text,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "sent",
        "is_read": 0
    }
    doc_ref = messages_collection.document()
    doc_ref.set(message)
    message['id'] = doc_ref.id

    pusher_client.trigger(f'private-{receiver_id}', 'new_message', message)
    pusher_client.trigger(f'private-{current_user["user_id"]}', 'new_message', message)
    return JSONResponse({"success": True, "message": message})

@app.delete("/api/delete_chat/{receiver_id}")
async def delete_chat(
    receiver_id: str,
    current_user: dict = Depends(get_current_user)
):
    messages = messages_collection.where(
        "sender_id", "in", [current_user["user_id"], receiver_id]
    ).where(
        "receiver_id", "in", [current_user["user_id"], receiver_id]
    ).stream()
    
    for msg in messages:
        messages_collection.document(msg.id).delete()
    
    return JSONResponse({"success": True})

@app.post("/api/update_profile_image")
async def update_profile_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    if not file.filename.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
        return JSONResponse({"error": "Formato no permitido"}, status_code=400)
    
    filename = sanitize_filename(file.filename)
    unique_filename = f"{current_user['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    
    os.makedirs("static/uploads", exist_ok=True)
    file_path = os.path.join("static/uploads", unique_filename)
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    image_url = f"/static/uploads/{unique_filename}"
    users_collection.document(current_user['user_id']).update({"profile_image": image_url})
    pusher_client.trigger(f'private-{current_user["user_id"]}', 'profile_update', {'profile_image': image_url})
    return JSONResponse({"success": True, "image_url": image_url})

@app.post("/api/update_profile")
async def update_profile(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    data = await request.json()
    users_collection.document(current_user['user_id']).update(data)
    return JSONResponse({"success": True})

@app.delete("/api/delete_account")
async def delete_account(current_user: dict = Depends(get_current_user)):
    users_collection.document(current_user['user_id']).delete()
    
    sent_messages = messages_collection.where("sender_id", "==", current_user['user_id']).stream()
    received_messages = messages_collection.where("receiver_id", "==", current_user['user_id']).stream()
    
    for msg in sent_messages:
        messages_collection.document(msg.id).delete()
    
    for msg in received_messages:
        messages_collection.document(msg.id).delete()
    
    return JSONResponse({"success": True})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
