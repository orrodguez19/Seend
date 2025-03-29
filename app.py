from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from firebase_admin import credentials, firestore, initialize_app
from pusher import Pusher
from datetime import datetime, timedelta
import os
import jwt
import json
from typing import Optional

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Firebase Initialization with error handling
try:
    firebase_config = json.loads(os.getenv("FIREBASE_CREDENTIALS", "{}"))
    cred = credentials.Certificate(firebase_config)
    firebase_app = initialize_app(cred)
    db = firestore.client()
    users_collection = db.collection('users')
    messages_collection = db.collection('messages')
except ValueError as e:
    raise Exception(f"Failed to initialize Firebase: Invalid credentials - {str(e)}")
except Exception as e:
    raise Exception(f"Failed to initialize Firebase: {str(e)}")

# Pusher Configuration
pusher_client = Pusher(
    app_id=os.getenv("PUSHER_APP_ID"),
    key=os.getenv("PUSHER_KEY"),
    secret=os.getenv("PUSHER_SECRET"),
    cluster=os.getenv("PUSHER_CLUSTER"),
    ssl=True
)

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key")  # Fallback for local dev
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
            raise HTTPException(status_code=401, detail="Invalid token: No user_id found")
        return {"user_id": user_id}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Routes remain largely the same; only showing key changes for brevity
@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_page():
    return FileResponse("templates/login.html")

@app.get("/chat")
async def chat_interface(current_user: dict = Depends(get_current_user)):
    return FileResponse("templates/chat.html")

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
                return JSONResponse({"error": "Incorrect credentials", "success": False}, status_code=401)
            
            user = user_ref[0].to_dict()
            token = jwt.encode({
                'user_id': user_ref[0].id,
                'exp': datetime.utcnow() + timedelta(hours=1)
            }, SECRET_KEY, algorithm=ALGORITHM)
            
            return JSONResponse({"token": token, "user_id": user_ref[0].id, "success": True})

        elif action == "register":
            if not email:
                return JSONResponse({"error": "Email required", "success": False}, status_code=400)
            
            if list(users_collection.where('username', '==', username).stream()):
                return JSONResponse({"error": "User already exists", "success": False}, status_code=400)
            
            user_data = {
                "username": username,
                "password": password,  # Note: In production, hash this!
                "email": email,
                "bio": "New user",
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

        return JSONResponse({"error": "Invalid action", "success": False}, status_code=400)
    
    except Exception as e:
        return JSONResponse({"error": f"Server error: {str(e)}", "success": False}, status_code=500)

# Other endpoints remain unchanged for this example...

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
