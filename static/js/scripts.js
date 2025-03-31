let users = [];
let chats = [];
let selectedUsers = [];
let currentChat = null;
let currentUserId = null;
let socket;

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
    profileArea: document.getElementById("profileArea"),
    profileTitle: document.getElementById("profileTitle")
};

function sanitizeInput(input) {
    const div = document.createElement('div');
    div.textContent = input;
    return div.innerHTML;
}

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(screen => screen.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
    if (screenId === 'screen-new-chat') loadUsers();
    if (screenId === 'screen-group-create') loadGroupUsers();
}

function loadUsers() {
    fetch('/api/users')
        .then(response => response.json())
        .then(data => {
            users = data;
            DOM.usersList.innerHTML = "";
            users.forEach(user => {
                if (user.id !== currentUserId) {  // Excluir al usuario actual
                    const div = document.createElement("div");
                    div.classList.add("list-item");
                    div.innerHTML = `<img src="https://i.pravatar.cc/150?img=${user.id}" alt="${user.name}"><div class="details"><strong>${user.name}</strong><p>${user.lastSeen}</p></div>`;
                    div.onclick = () => startChat(user.id);
                    DOM.usersList.appendChild(div);
                }
            });
        })
        .catch(error => console.error('Error loading users:', error));
}

function loadGroupUsers() {
    DOM.groupUsersList.innerHTML = "";
    users.forEach(user => {
        if (user.id !== currentUserId) {
            const div = document.createElement("div");
            div.classList.add("list-item");
            div.innerHTML = `<img src="https://i.pravatar.cc/150?img=${user.id}" alt="${user.name}"><div class="details"><strong>${user.name}</strong><p>${user.lastSeen}</p></div><input type="checkbox" id="user-${user.id}" onchange="updateSelectedUsers(${user.id})">`;
            DOM.groupUsersList.appendChild(div);
        }
    });
    updateSelectedCount();
}

function updateSelectedUsers(userId) {
    const checkbox = document.getElementById(`user-${userId}`);
    if (checkbox.checked) {
        if (!selectedUsers.includes(userId)) selectedUsers.push(userId);
    } else {
        selectedUsers = selectedUsers.filter(id => id !== userId);
    }
    updateSelectedCount();
}

function updateSelectedCount() {
    DOM.selectedCount.textContent = `${selectedUsers.length} usuario${selectedUsers.length !== 1 ? 's' : ''} seleccionado${selectedUsers.length !== 1 ? 's' : ''}`;
}

function createGroup() {
    const groupName = sanitizeInput(document.getElementById('groupName').value.trim());
    if (!groupName) return alert("Por favor ingresa un nombre para el grupo");
    if (selectedUsers.length < 2) return alert("Selecciona al menos 2 usuarios para crear un grupo");
    const newGroup = {id: Date.now(), name: groupName, creatorId: currentUserId, members: selectedUsers.concat(currentUserId), isGroup: true, messages: []};
    chats.push(newGroup);
    updateChatList();
    document.getElementById('groupName').value = '';
    selectedUsers = [];
    updateSelectedCount();
    showScreen('screen-chats');
    openConversation(newGroup);
}

function startChat(userId) {
    const existingChat = chats.find(chat => !chat.isGroup && chat.memberId === userId);
    if (existingChat) return openConversation(existingChat);
    const user = users.find(u => u.id === userId);
    const newChat = {id: Date.now(), name: user.name, memberId: userId, isGroup: false, messages: []};
    chats.push(newChat);
    updateChatList();
    openConversation(newChat);
}

function updateChatList() {
    DOM.chatList.innerHTML = chats.length === 0 ? `<p class="empty-message">Inicie una nueva conversación</p>` : chats.map(chat => `
        <div class="list-item" onclick="openConversation(chats[${chats.indexOf(chat)}])">
            ${chat.isGroup ? `<svg viewBox="0 0 24 24" width="50" height="50" fill="#fff" style="margin-right:12px;"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM9 12c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm7 0c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3z"/></svg>` : `<img src="https://i.pravatar.cc/150?img=${chat.memberId}" alt="${chat.name}">`}
            <div class="details"><strong>${chat.name}</strong><p>${chat.isGroup ? 'Grupo' : 'Chat individual'}</p></div>
        </div>`).join('');
}

function openConversation(chat) {
    currentChat = chat;
    DOM.chatTitle.textContent = chat.name;
    if (!chat.isGroup) {
        const user = users.find(u => u.id === chat.memberId);
        DOM.chatUserImage.src = `https://i.pravatar.cc/150?img=${chat.memberId}`;
        DOM.chatUserImage.alt = chat.name;
        DOM.chatStatus.textContent = user.isOnline ? "En línea" : user.lastSeen;
        fetch(`/api/messages/${chat.memberId}`)
            .then(response => response.json())
            .then(messages => {
                DOM.conversationArea.innerHTML = messages.length > 0 ? messages.map(msg => `
                    <div class="message ${msg.sender_id === currentUserId ? 'sent' : 'received'}">${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div></div>`).join('') : `<div class="message received">¡Hola! Este es el inicio de tu conversación.</div>`;
                DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
            })
            .catch(error => console.error('Error loading messages:', error));
    } else {
        DOM.chatUserImage.src = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyek05IDEyYy0xLjY2IDAtMy0xLjM0LTMtM3MxLjM0LTMgMy0zIDMgMS4zNCAzIDMtMS4zNCAzLTMgM3ptNyAwYy0xLjY2IDAtMy0xLjM0LTMtM3MxLjM0LTMgMy0zIDMgMS4zNCAzIDMtMS4zNCAzLTMgM3oiLz48L3N2Zz4=";
        DOM.chatStatus.textContent = `${chat.members.length} miembros`;
        DOM.conversationArea.innerHTML = chat.messages.length > 0 ? chat.messages.map(msg => `
            <div class="message ${msg.sender_id === currentUserId ? 'sent' : 'received'}">${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div></div>`).join('') : `<div class="message received">¡Este es el inicio del grupo!</div>`;
        DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
    }
    showScreen("screen-conversation");
}

function formatTime(date) {
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
}

function getStatusIcon(status) {
    if (!status || status === 'sent') return '<svg viewBox="0 0 24 24"><path fill="#bbb" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    if (status === 'delivered') return '<svg viewBox="0 0 24 24"><path fill="#bbb" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    if (status === 'read') return '<svg viewBox="0 0 24 24"><path fill="#4CAF50" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    return '';
}

function sendMessage() {
    const input = DOM.messageInput;
    const text = sanitizeInput(input.value.trim());
    if (!text || !currentChat) return;

    const timestamp = new Date().toISOString();
    const message = {
        sender_id: currentUserId,
        receiver_id: currentChat.isGroup ? currentChat.id : currentChat.memberId,
        text: text,
        timestamp: timestamp
    };
    
    socket.send(JSON.stringify(message));
    input.value = '';
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    // Obtener el nombre de usuario del meta tag
    const usernameMeta = document.querySelector('meta[name="username"]');
    if (!usernameMeta) {
        console.error('No se encontró el meta tag con el nombre de usuario');
        return;
    }
    const username = usernameMeta.content;
    
    // Configurar WebSocket (nativo en lugar de Socket.IO)
    socket = new WebSocket(`wss://${window.location.host}/ws/${currentUserId}`);
    
    socket.onopen = function(e) {
        console.log("Conexión WebSocket establecida");
    };
    
    socket.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        if (!currentChat) return;
        const isCurrentChat = (currentChat.isGroup && msg.receiver_id === currentChat.id) || 
                            (!currentChat.isGroup && (msg.sender_id === currentChat.memberId || msg.receiver_id === currentChat.memberId));
        if (isCurrentChat) {
            const messageDiv = document.createElement("div");
            messageDiv.className = `message ${msg.sender_id === currentUserId ? 'sent' : 'received'}`;
            messageDiv.innerHTML = `${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div>`;
            DOM.conversationArea.appendChild(messageDiv);
            DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
        }
    };
    
    socket.onclose = function(event) {
        if (event.wasClean) {
            console.log(`Conexión cerrada limpiamente, código=${event.code} motivo=${event.reason}`);
        } else {
            console.log('La conexión se cayó');
        }
    };
    
    socket.onerror = function(error) {
        console.log(`Error en WebSocket: ${error.message}`);
    };

    // Cargar usuarios y establecer el ID del usuario actual
    fetch('/api/users')
        .then(response => response.json())
        .then(data => {
            users = data;
            const currentUser = users.find(u => u.name === username);
            if (currentUser) {
                currentUserId = currentUser.id;
                updateChatList();
                document.getElementById("openNewChat").addEventListener("click", () => showScreen("screen-new-chat"));
                
                // Reconectar WebSocket con el ID correcto
                if (socket) socket.close();
                socket = new WebSocket(`wss://${window.location.host}/ws/${currentUserId}`);
            } else {
                console.error('Usuario actual no encontrado');
            }
        })
        .catch(error => console.error('Error loading current user:', error));
});