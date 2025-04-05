// Elementos del DOM
const authContainer = document.getElementById('auth-container');
const chatContainer = document.getElementById('chat-container');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const loginTab = document.querySelector('.auth-tab.active');
const registerTab = document.querySelector('.auth-tab:not(.active)');
const authMessage = document.getElementById('auth-message');
const menuButton = document.getElementById('menuButton');
const closePanel = document.getElementById('closePanel');
const usersPanel = document.getElementById('usersPanel');
const userList = document.getElementById('userList');
const chatTitle = document.getElementById('chatTitle');
const chatStatus = document.getElementById('chatStatus');
const messagesContainer = document.getElementById('messagesContainer');
const chatInput = document.getElementById('chatInput');
const sendButton = document.getElementById('sendButton');
const replyIndicator = document.getElementById('replyIndicator');
const replyPreview = document.getElementById('replyPreview');
const replyingTo = document.getElementById('replyingTo');
const cancelReply = document.getElementById('cancelReply');
const logoutButton = document.getElementById('logout-button');

// Estado de la aplicación
let currentUser = null;
let currentChat = 'public';
let currentReply = null;
let socket = null;
let typingTimeout = null;

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
        ? 'http://localhost:5000';
    
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
    socket.on('user_list', renderUserList);
    socket.on('user_status', updateUserStatus);
    socket.on('user_typing', showTypingIndicator);
    socket.on('public_message', handlePublicMessage);
    socket.on('private_message', handlePrivateMessage);
    socket.on('unread_count', updateUnreadCount);
    socket.on('message_read', handleMessageRead);
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

// Manejadores de mensajes
function handlePublicMessage(message) {
    if (currentChat === 'public') {
        addMessage(
            message.sender_name,
            message.content,
            formatTime(message.timestamp),
            message.sender_id === currentUser.id ? 'sent' : 'received',
            false,
            message.reply_to
        );
    }
}

function handlePrivateMessage(message) {
    const isCurrent = (message.recipient_id === currentChat && message.sender_id === currentUser.id) || 
                     (message.sender_id === currentChat && message.recipient_id === currentUser.id);
    
    if (isCurrent) {
        addMessage(
            message.sender_name,
            message.content,
            formatTime(message.timestamp),
            message.sender_id === currentUser.id ? 'sent' : 'received',
            true,
            message.reply_to
        );

        if (message.sender_id !== currentUser.id && !message.is_read) {
            socket.emit('mark_as_read', { message_id: message.message_id });
        }
    } else if (message.sender_id !== currentUser.id) {
        updateUnreadCount({ recipient_id: message.sender_id, count: 1 });
    }
}

function handleMessageRead(data) {
    // Puedes implementar lógica para marcar mensajes como leídos en la UI si es necesario
    console.log(`Mensaje ${data.message_id} leído por ${data.reader_id}`);
}

// Renderizado de UI
function renderUserList(users) {
    userList.innerHTML = '';
    
    // Chat público fijo
    const publicChat = document.createElement('li');
    publicChat.className = `user-item ${currentChat === 'public' ? 'active' : ''}`;
    publicChat.dataset.user = 'public';
    publicChat.innerHTML = `
        <div class="user-avatar">GP</div>
        <div class="user-info">
            <div class="user-name">Chat Público</div>
            <div class="user-status-text">Todos los usuarios</div>
        </div>
    `;
    publicChat.addEventListener('click', () => switchChat('public'));
    userList.appendChild(publicChat);
    
    // Usuarios
    users.filter(user => user.id !== 'public').forEach(user => {
        const isOnline = user.online_status === 'online';
        const isTyping = user.online_status === 'typing';
        
        const userItem = document.createElement('li');
        userItem.className = `user-item ${currentChat === user.id ? 'active' : ''}`;
        userItem.dataset.user = user.id;
        userItem.innerHTML = `
            <div class="user-avatar">${user.avatar_initials}
                <div class="user-status status-${isTyping ? 'typing' : isOnline ? 'online' : 'offline'}"></div>
            </div>
            <div class="user-info">
                <div class="user-name">${user.username}</div>
                ${isTyping ? 
                    '<div class="typing-indicator">Escribiendo<div class="typing-dots"><span></span><span></span><span></span></div></div>' : 
                    `<div class="user-status-text">${isOnline ? 'En línea' : 'Desconectado'}</div>`
                }
            </div>
            <div class="notification-badge" style="display:none">0</div>
        `;
        userItem.addEventListener('click', () => switchChat(user.id));
        userList.appendChild(userItem);
    });
}

function updateUserStatus(data) {
    const userItems = document.querySelectorAll(`.user-item[data-user="${data.user_id}"]`);
    
    userItems.forEach(item => {
        const statusElement = item.querySelector('.user-status');
        const statusText = item.querySelector('.user-status-text');
        const typingIndicator = item.querySelector('.typing-indicator');
        
        if (statusElement) {
            statusElement.className = `user-status status-${data.status === 'typing' ? 'typing' : data.status === 'online' ? 'online' : 'offline'}`;
        }
        
        if (statusText && typingIndicator) {
            if (data.status === 'typing') {
                statusText.style.display = 'none';
                typingIndicator.style.display = 'flex';
            } else {
                statusText.style.display = 'block';
                typingIndicator.style.display = 'none';
                statusText.textContent = data.status === 'online' ? 'En línea' : 'Desconectado';
            }
        }
        
        if (data.user_id === currentChat) {
            chatStatus.textContent = data.status === 'online' ? 'En línea' : 
                                   data.status === 'typing' ? 'Escribiendo...' : 
                                   'Desconectado';
        }
    });
}

function showTypingIndicator(data) {
    if (data.recipient_id === currentChat || (currentChat === 'public' && data.recipient_id === 'public')) {
        const userItems = document.querySelectorAll(`.user-item[data-user="${data.user_id}"]`);
        
        userItems.forEach(item => {
            const statusText = item.querySelector('.user-status-text');
            const typingIndicator = item.querySelector('.typing-indicator');
            
            if (statusText && typingIndicator) {
                if (data.is_typing) {
                    statusText.style.display = 'none';
                    typingIndicator.style.display = 'flex';
                } else {
                    statusText.style.display = 'block';
                    typingIndicator.style.display = 'none';
                    statusText.textContent = 'En línea';
                }
            }
            
            if (data.user_id === currentChat) {
                chatStatus.textContent = data.is_typing ? 'Escribiendo...' : 'En línea';
            }
        });
    }
}

function updateUnreadCount(data) {
    const badge = document.querySelector(`.user-item[data-user="${data.recipient_id}"] .notification-badge`);
    if (badge) {
        const currentCount = parseInt(badge.textContent) || 0;
        const newCount = currentCount + data.count;
        badge.textContent = newCount;
        badge.style.display = newCount > 0 ? 'flex' : 'none';
    }
}

function switchChat(userId) {
    document.querySelectorAll('.user-item').forEach(item => item.classList.remove('active'));
    document.querySelector(`.user-item[data-user="${userId}"]`).classList.add('active');
    
    currentChat = userId;
    messagesContainer.innerHTML = '<div class="current-time">Hoy</div>';
    
    const userItem = document.querySelector(`.user-item[data-user="${userId}"]`);
    const userName = userItem.querySelector('.user-name').textContent;
    const userStatus = userItem.querySelector('.user-status-text')?.textContent || 'Todos los usuarios';
    
    chatTitle.textContent = userName;
    chatStatus.textContent = userStatus;
    
    // Resetear notificaciones
    const badge = userItem.querySelector('.notification-badge');
    if (badge) {
        badge.style.display = 'none';
        badge.textContent = '0';
    }
    
    // Mensaje del sistema
    addSystemMessage(
        userId === 'public' 
            ? 'Este es el chat público. Todos verán tus mensajes.' 
            : `Conversación privada con ${userName}`
    );
}

function addSystemMessage(text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message-wrapper';
    messageDiv.innerHTML = `
        <div class="message received">
            <div class="message-content">
                <div class="message-sender">Sistema</div>
                <div class="message-text">${text}</div>
                <div class="message-time">${getCurrentTime()}</div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(messageDiv);
    scrollToBottom();
}

function addMessage(sender, text, time, type, isPrivate, replyTo) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message-wrapper';
    
    let replyContent = '';
    if (currentReply) {
        replyContent = `
            <div class="reply-container">
                <span class="reply-sender">Respondiendo a ${currentReply.sender}</span>
                <div class="reply-text">${currentReply.text}</div>
            </div>
        `;
    } else if (replyTo) {
        replyContent = `
            <div class="reply-container">
                <span class="reply-sender">Respondiendo a ${sender}</span>
                <div class="reply-text">${text.substring(0, 50)}${text.length > 50 ? '...' : ''}</div>
            </div>
        `;
    }
    
    messageDiv.innerHTML = `
        <div class="message ${type}">
            <div class="message-content">
                <div class="message-sender">${sender}</div>
                ${replyContent}
                <div class="message-text">${text}</div>
                <div class="message-time">${time}
                    ${type === 'sent' ? `
                        <svg class="status-icon" width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M2 6L4.66667 8.66667L10 3.33333" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                            <path d="M6 6L8.66667 8.66667L14 3.33333" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" transform="translate(-4 0)"/>
                        </svg>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    scrollToBottom();
}

// Funciones de utilidad
function scrollToBottom() {
    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 50);
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    let hours = date.getHours();
    let minutes = date.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    minutes = minutes < 10 ? '0' + minutes : minutes;
    return `${hours}:${minutes} ${ampm}`;
}

function getCurrentTime() {
    const now = new Date();
    let hours = now.getHours();
    let minutes = now.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    minutes = minutes < 10 ? '0' + minutes : minutes;
    return `${hours}:${minutes} ${ampm}`;
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
            showMessage('La contraseña debe tener al menos 6 caracteres', 'error');
            return;
        }
        
        socket.emit('register', { username, password });
    });
    
    // Chat
    menuButton.addEventListener('click', () => {
        usersPanel.classList.add('active');
    });
    
    closePanel.addEventListener('click', () => {
        usersPanel.classList.remove('active');
    });
    
    logoutButton.addEventListener('click', () => {
        localStorage.clear();
        if (socket) socket.disconnect();
        showAuth();
    });
    
    sendButton.addEventListener('click', sendMessage);
    
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
        
        // Indicador de "escribiendo"
        if (socket) {
            socket.emit('typing_status', {
                is_typing: true,
                recipient_id: currentChat === 'public' ? null : currentChat
            });
            
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => {
                socket.emit('typing_status', {
                    is_typing: false,
                    recipient_id: currentChat === 'public' ? null : currentChat
                });
            }, 3000);
        }
    });
    
    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });
    
    cancelReply.addEventListener('click', () => {
        replyIndicator.style.display = 'none';
        currentReply = null;
    });
}

function sendMessage() {
    const messageText = chatInput.value.trim();
    if (!messageText || !socket) return;
    
    socket.emit('send_message', {
        content: messageText,
        recipient_id: currentChat === 'public' ? null : currentChat,
        reply_to: currentReply?.messageId
    });
    
    chatInput.value = '';
    chatInput.style.height = 'auto';
    
    if (currentReply) {
        replyIndicator.style.display = 'none';
        currentReply = null;
    }
}

// Iniciar la aplicación
document.addEventListener('DOMContentLoaded', init);