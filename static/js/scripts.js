// scripts.js - Versión para Render con MongoDB
let users = [];
let chats = [];
let selectedUsers = [];
let currentChat = null;
let currentUserId = null;
let socket;
let isOnline = false;

const DOM = {
    chatList: document.getElementById("chatList"),
    usersList: document.getElementById("usersList"),
    groupUsersList: document.getElementById("groupUsersList"),
    conversationArea: document.getElementById("conversationArea"),
    messageInput: document.getElementById("messageInput"),
    chatTitle: document.getElementById("chatTitle"),
    chatUserImage: document.getElementById("chatUserImage"),
    chatStatus: document.getElementById("chatStatus"),
    selectedCount: document.getElementById("selectedCount"),
    profileImage: document.getElementById("profileImage"),
    profileUsername: document.getElementById("profileUsername"),
    profileBio: document.getElementById("profileBio"),
    profileEmail: document.getElementById("profileEmail"),
    profilePhone: document.getElementById("profilePhone"),
    profileDob: document.getElementById("profileDob")
};

// Función para verificar conexión
function checkConnection() {
    if (!navigator.onLine) {
        alert("Sin conexión a internet. Algunas funciones pueden no estar disponibles.");
        return false;
    }
    return true;
}

function sanitizeInput(input) {
    const div = document.createElement('div');
    div.textContent = input;
    return div.innerHTML;
}

function showScreen(screenId) {
    if (!checkConnection()) return;
    
    document.querySelectorAll('.screen').forEach(screen => screen.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
    
    if (screenId === 'screen-new-chat') loadUsers();
    if (screenId === 'screen-group-create') loadGroupUsers();
    if (screenId === 'screen-profile') loadProfile();
    if (screenId === 'screen-conversation' && currentChat) {
        markMessagesAsRead();
    }
}

function markMessagesAsRead() {
    if (!currentChat || !currentUserId) return;
    
    const receiverId = currentChat.isGroup ? currentChat.id : currentChat.memberId;
    
    fetch(`/api/messages/${receiverId}`)
        .then(response => response.json())
        .then(messages => {
            messages.forEach(msg => {
                if (msg.receiver_id === currentUserId && !msg.is_read) {
                    socket.emit('message_read', { 
                        messageId: msg.id, 
                        receiver_id: msg.sender_id 
                    });
                }
            });
        });
}

async function loadUsers() {
    if (!checkConnection()) return;
    
    try {
        const response = await fetch('/api/users');
        const data = await response.json();
        
        users = data.map(user => ({
            ...user,
            isOnline: user.isOnline || false,
            lastSeen: user.lastSeen || 'Desconocido'
        }));
        
        DOM.usersList.innerHTML = "";
        users.forEach(user => {
            if (user.id !== currentUserId) {
                const div = document.createElement("div");
                div.classList.add("list-item");
                div.innerHTML = `
                    <img src="${user.profile_image}" alt="${user.name}" 
                         onerror="this.src='https://www.svgrepo.com/show/452030/avatar-default.svg'">
                    <div class="details">
                        <strong>${user.name}</strong>
                        <p>${user.isOnline ? 'En línea' : user.lastSeen}</p>
                    </div>
                `;
                div.onclick = () => startChat(user.id);
                DOM.usersList.appendChild(div);
            }
        });
    } catch (error) {
        console.error("Error loading users:", error);
    }
}

// ... (las funciones loadGroupUsers, updateSelectedUsers, createGroup se mantienen igual)

async function startChat(userId) {
    if (!checkConnection()) return;
    
    try {
        const existingChat = chats.find(chat => !chat.isGroup && chat.memberId === userId);
        if (existingChat) return openConversation(existingChat);
        
        const user = users.find(u => u.id === userId);
        if (!user) return;
        
        const newChat = {
            id: Date.now().toString(),
            name: user.name,
            memberId: userId,
            isGroup: false,
            messages: [],
            lastMessage: '',
            unreadCount: 0
        };
        
        chats.push(newChat);
        updateChatList();
        openConversation(newChat);
        
    } catch (error) {
        console.error("Error starting chat:", error);
    }
}

function updateChatList() {
    DOM.chatList.innerHTML = chats.length === 0 
        ? `<p class="empty-message">Inicie una nueva conversación</p>` 
        : chats.map(chat => `
            <div class="list-item" onclick="openConversation(chats[${chats.indexOf(chat)}])">
                ${chat.isGroup 
                    ? `<svg viewBox="0 0 24 24" width="50" height="50" fill="#0D47A1" style="margin-right:12px;">
                          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM9 12c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm7 0c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3z"/>
                       </svg>` 
                    : `<img src="${users.find(u => u.id === chat.memberId)?.profile_image || 
                        'https://www.svgrepo.com/show/452030/avatar-default.svg'}" 
                        alt="${chat.name}"
                        onerror="this.src='https://www.svgrepo.com/show/452030/avatar-default.svg'">`
                }
                <div class="details">
                    <strong>${chat.name}</strong>
                    <p>${chat.lastMessage || 'Sin mensajes'}</p>
                </div>
                ${chat.unreadCount > 0 ? `<span class="unread-count">${chat.unreadCount}</span>` : ''}
            </div>`
        ).join('');
}

// ... (las funciones openConversation, formatTime, getStatusIcon se mantienen igual)

async function sendMessage() {
    if (!checkConnection() || !currentChat || !currentUserId) return;
    
    const input = DOM.messageInput;
    const text = sanitizeInput(input.value.trim());
    if (!text) return;

    const timestamp = new Date().toISOString();
    const message = {
        receiver_id: currentChat.isGroup ? currentChat.id : currentChat.memberId,
        text: text,
        timestamp: timestamp,
        status: 'sent'
    };
    
    try {
        socket.emit('send_message', message);
        input.value = '';
        currentChat.lastMessage = text;
        updateChatList();
    } catch (error) {
        console.error("Error sending message:", error);
        alert("Error al enviar el mensaje. Intenta nuevamente.");
    }
}

// ... (las funciones handleKeyPress, loadProfile, toggleEdit se mantienen igual)

async function updateProfile(field, value) {
    if (!checkConnection()) return;
    
    try {
        const response = await fetch('/api/update_profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: value })
        });
        
        const data = await response.json();
        if (data.success) {
            const user = users.find(u => u.id === currentUserId);
            if (user) user[field] = value;
            socket.emit('profile_update', { 
                userId: currentUserId, 
                field, 
                value 
            });
        }
    } catch (error) {
        console.error("Error updating profile:", error);
    }
}

async function uploadProfileImage(file) {
    if (!checkConnection()) return;
    
    try {
        const formData = new FormData();
        formData.append('image', file);
        
        const response = await fetch('/api/upload_profile_image', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (data.success) {
            DOM.profileImage.src = data.imageUrl;
            
            // Actualizar en todos los chats
            chats.forEach(chat => {
                if (!chat.isGroup && chat.memberId === currentUserId) {
                    chat.name = users.find(u => u.id === currentUserId)?.name;
                }
            });
            
            updateChatList();
        }
    } catch (error) {
        console.error("Error uploading image:", error);
    }
}

// Eventos de Socket.IO
function setupSocketEvents() {
    socket.on('connect', () => {
        isOnline = true;
        console.log("Conectado al servidor WebSocket");
    });

    socket.on('disconnect', () => {
        isOnline = false;
        console.log("Desconectado del servidor WebSocket");
    });

    socket.on('new_message', (msg) => {
        handleNewMessage(msg);
    });

    // ... (otros eventos de socket se mantienen igual)
}

function handleNewMessage(msg) {
    const isCurrentChat = currentChat && (
        (currentChat.isGroup && msg.receiver_id === currentChat.id) || 
        (!currentChat.isGroup && (msg.sender_id === currentChat.memberId || msg.receiver_id === currentChat.memberId))
    );
    
    let chat = chats.find(c => 
        (c.isGroup && c.id === msg.receiver_id) || 
        (!c.isGroup && (c.memberId === msg.sender_id || c.memberId === msg.receiver_id))
    );
    
    if (!chat) {
        chat = {
            id: msg.id,
            name: users.find(u => u.id === (msg.sender_id === currentUserId ? msg.receiver_id : msg.sender_id))?.name,
            memberId: msg.sender_id === currentUserId ? msg.receiver_id : msg.sender_id,
            isGroup: false,
            messages: [msg],
            lastMessage: msg.text,
            unreadCount: 0
        };
        chats.push(chat);
    } else {
        if (!chat.messages.some(m => m.id === msg.id)) {
            chat.messages.push(msg);
        }
        chat.lastMessage = msg.text;
    }
    
    if (!isCurrentChat && msg.receiver_id === currentUserId) {
        chat.unreadCount = (chat.unreadCount || 0) + 1;
    }
    
    updateChatList();
    
    if (isCurrentChat) {
        renderMessages(chat.messages);
        socket.emit('message_delivered', { 
            messageId: msg.id, 
            receiver_id: msg.receiver_id 
        });
    }
}

function renderMessages(messages) {
    DOM.conversationArea.innerHTML = messages
        .map(msg => `
            <div class="message ${msg.sender_id === currentUserId ? 'sent' : 'received'}" data-id="${msg.id}">
                ${msg.text}
                <div class="message-status">
                    ${formatTime(new Date(msg.timestamp))}
                    ${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}
                </div>
            </div>
        `)
        .join('');
    
    DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    // Configurar Socket.IO
    socket = io({
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        timeout: 20000
    });

    setupSocketEvents();

    // Recuperar usuario actual
    currentUserId = localStorage.getItem('userId');
    if (!currentUserId) {
        const metaUser = document.querySelector('meta[name="username"]');
        if (metaUser) {
            const username = metaUser.content;
            const user = users.find(u => u.name === username);
            if (user) {
                currentUserId = user.id;
                localStorage.setItem('userId', currentUserId);
            }
        }
    }

    // Cargar datos iniciales
    if (currentUserId) {
        fetch('/api/users')
            .then(response => response.json())
            .then(data => {
                users = data;
                updateChatList();
            })
            .catch(error => console.error("Error loading initial data:", error));
    }

    // Event listeners
    document.getElementById("openNewChat").addEventListener("click", () => showScreen("screen-new-chat"));
    
    // Verificar conexión periódicamente
    setInterval(() => {
        if (!isOnline && navigator.onLine) {
            console.log("Reconectando...");
            socket.connect();
        }
    }, 5000);
});

// Manejo de conexión/desconexión
window.addEventListener('online', () => {
    console.log("Conexión a internet restablecida");
    socket.connect();
});

window.addEventListener('offline', () => {
    console.log("Sin conexión a internet");
});
