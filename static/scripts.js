// Elementos del DOM
const authContainer = document.getElementById('auth-container');
const chatContainer = document.getElementById('chat-container');
const authMessage = document.getElementById('auth-message');

// Estado de la aplicación
let currentUser = null;
let currentChat = 'public';
let socket = null;

// Inicialización
function init() {
    // Verificar si ya está autenticado
    const userId = localStorage.getItem('user_id');
    const sessionToken = localStorage.getItem('session_token');
    
    if (userId && sessionToken) {
        connectSocket(userId, sessionToken);
    } else {
        showAuth();
    }
    
    setupEventListeners();
}

// Mostrar pantalla de autenticación
function showAuth() {
    authContainer.style.display = 'flex';
    chatContainer.style.display = 'none';
}

// Mostrar chat
function showChat() {
    authContainer.style.display = 'none';
    chatContainer.style.display = 'flex';
}

// Conectar con Socket.IO
function connectSocket(userId, sessionToken) {
    const socketUrl = window.location.origin;
    
    socket = io(socketUrl, {
        reconnectionAttempts: 3,
        timeout: 2000
    });

    socket.on('connect', () => {
        console.log('Conectado al servidor');
        socket.emit('authenticate', { 
            user_id: userId, 
            session_token: sessionToken 
        });
    });

    socket.on('connect_error', (error) => {
        console.error('Error de conexión:', error);
        showMessage('No se pudo conectar al servidor', 'error');
    });

    socket.on('auth_failed', () => {
        localStorage.removeItem('user_id');
        localStorage.removeItem('session_token');
        showAuth();
        showMessage('La sesión ha expirado. Por favor inicia sesión nuevamente.', 'error');
    });

    socket.on('register_response', handleRegisterResponse);
    socket.on('login_response', handleLoginResponse);
    socket.on('user_list', renderUserList);
    socket.on('user_status', updateUserStatus);
    socket.on('public_message', handlePublicMessage);
    socket.on('private_message', handlePrivateMessage);
}

// Manejadores de eventos de autenticación
function handleRegisterResponse(data) {
    if (data.success) {
        showMessage('¡Registro exitoso! Redirigiendo...', 'success');
        saveUserData(data);
        setTimeout(() => {
            showChat();
            socket.emit('authenticate', { 
                user_id: data.user_id, 
                session_token: data.session_token 
            });
        }, 1500);
    } else {
        showMessage(data.message, 'error');
    }
}

function handleLoginResponse(data) {
    if (data.success) {
        saveUserData(data);
        showChat();
    } else {
        showMessage(data.message, 'error');
    }
}

function saveUserData(data) {
    localStorage.setItem('user_id', data.user_id);
    localStorage.setItem('session_token', data.session_token);
    localStorage.setItem('username', data.username);
    localStorage.setItem('avatar_initials', data.avatar_initials);
    
    currentUser = {
        id: data.user_id,
        username: data.username,
        avatar: data.avatar_initials
    };
    
    // Actualizar UI
    document.getElementById('current-username').textContent = data.username;
    document.getElementById('user-avatar').textContent = data.avatar_initials;
}

// Funciones de utilidad
function showMessage(text, type) {
    authMessage.textContent = text;
    authMessage.className = `auth-message ${type}`;
    authMessage.style.display = 'block';
    
    setTimeout(() => {
        authMessage.style.display = 'none';
    }, 5000);
}

// Configuración de event listeners
function setupEventListeners() {
    // Login y registro
    document.getElementById('login-button').addEventListener('click', (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        
        if (!username || !password) {
            showMessage('Por favor completa todos los campos', 'error');
            return;
        }
        
        socket.emit('login', { username, password });
    });
    
    document.getElementById('register-button').addEventListener('click', (e) => {
        e.preventDefault();
        const username = document.getElementById('register-username').value;
        const password = document.getElementById('register-password').value;
        const confirm = document.getElementById('register-confirm').value;
        
        if (!username || !password || !confirm) {
            showMessage('Por favor completa todos los campos', 'error');
            return;
        }
        
        if (password !== confirm) {
            showMessage('Las contraseñas no coinciden', 'error');
            return;
        }
        
        socket.emit('register', { username, password });
    });
    
    // Logout
    document.getElementById('logout-button').addEventListener('click', () => {
        localStorage.clear();
        if (socket) socket.disconnect();
        showAuth();
    });
}

// Iniciar la aplicación
document.addEventListener('DOMContentLoaded', init);