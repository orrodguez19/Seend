// Elementos del DOM
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginTab = document.querySelector('.auth-tab.active');
const registerTab = document.querySelector('.auth-tab:not(.active)');
const authMessage = document.getElementById('auth-message');

// Socket.IO
let socket = null;

// Inicialización
function init() {
    setupEventListeners();
}

// Mostrar mensaje de autenticación
function showMessage(text, type) {
    authMessage.textContent = text;
    authMessage.className = `auth-message ${type}`;
    authMessage.style.display = 'block';
    
    setTimeout(() => {
        authMessage.style.display = 'none';
    }, 5000);
}

// Conectar con Socket.IO
function connectSocket() {
    const socketUrl = window.location.hostname === 'localhost' 
        ? 'http://localhost:5000' 
        : window.location.origin;
    
    socket = io(socketUrl);

    socket.on('connect', () => {
        console.log('Conectado al servidor');
    });

    socket.on('disconnect', () => {
        console.log('Desconectado del servidor');
    });

    socket.on('register_response', handleRegisterResponse);
    socket.on('login_response', handleLoginResponse);
}

// Manejadores de eventos de autenticación
function handleRegisterResponse(data) {
    if (data.success) {
        showMessage('¡Registro exitoso! Redirigiendo...', 'success');
        setTimeout(() => {
            window.location.href = '/chat.html';
        }, 1500);
    } else {
        showMessage(data.message, 'error');
    }
}

function handleLoginResponse(data) {
    if (data.success) {
        localStorage.setItem('user_id', data.user_id);
        localStorage.setItem('session_token', data.session_token);
        localStorage.setItem('username', data.username);
        localStorage.setItem('avatar_initials', data.avatar_initials);
        window.location.href = '/chat.html';
    } else {
        showMessage(data.message, 'error');
    }
}

// Configuración de event listeners
function setupEventListeners() {
    // Tabs de autenticación
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
    
    // Login
    document.getElementById('login-button').addEventListener('click', (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        
        if (!username || !password) {
            showMessage('Por favor completa todos los campos', 'error');
            return;
        }
        
        if (!socket) connectSocket();
        socket.emit('login', { username, password });
    });
    
    // Registro
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
            showMessage('La contraseña debe tener al menos 6 caracteres', 'error');
            return;
        }
        
        if (!socket) connectSocket();
        socket.emit('register', { username, password });
    });
}

// Iniciar la aplicación
document.addEventListener('DOMContentLoaded', init);