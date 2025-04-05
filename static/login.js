// Elementos del DOM
const authContainer = document.getElementById('auth-container');
const chatContainer = document.getElementById('chat-container');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginTab = document.querySelector('.auth-tab.active');
const registerTab = document.querySelector('.auth-tab:not(.active)');
const authMessage = document.getElementById('auth-message');

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
    // Cambia esta URL por la de tu servidor en producción
    const socketUrl = window.location.hostname === 'localhost' 
        ?
'http://localhost:5000';
    
    socket = io(socketUrl);

    socket.on('connect', () => {
        console.log('Conectado al servidor');
        socket.emit('authenticate', { user_id: userId, session_token: sessionToken });
    });
    socket.on('disconnect', () => {
        console.log('Desconectado del servidor');
    });
    socket.on('auth_failed', () => {
        localStorage.removeItem('user_id');
        localStorage.removeItem('session_token');
        showAuth();
        showMessage('La sesión ha expirado. Por favor inicia sesión nuevamente.', 'error');
    });
    socket.on('register_response', handleRegisterResponse);
    socket.on('login_response', handleLoginResponse);
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
    // Autenticación
    loginTab.addEventListener('click', () => {
        loginTab.classList.add('active');
        registerTab.classList.remove('active');
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
    });
    registerTab.addEventListener('click', () => {
        registerTab.classList.add('active');
        loginTab.classList.remove('active');
        registerForm.style.display = 'block';
        loginForm.style.display = 'none';
    });
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
        
        if (password.length < 6) {
            showMessage('La contraseña debe tener al menos 6 caracteres', 
'error');
            return;
        }
        
        socket.emit('register', { username, password });
    });
}

// Iniciar la aplicación
document.addEventListener('DOMContentLoaded', init);
