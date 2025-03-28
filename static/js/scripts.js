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
    profileImage: document.getElementById("profileImage"),
    profileUsername: document.getElementById("profileUsername"),
    profileBio: document.getElementById("profileBio"),
    profileEmail: document.getElementById("profileEmail"),
    profilePhone: document.getElementById("profilePhone"),
    profileDob: document.getElementById("profileDob")
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
    if (screenId === 'screen-profile') loadProfile();
    if (screenId === 'screen-conversation' && currentChat) {
        // Marcar mensajes como leídos al abrir la conversación
        fetch(`/api/messages/${currentChat.isGroup ? currentChat.id : currentChat.memberId}`)
            .then(response => response.json())
            .then(messages => {
                messages.forEach(msg => {
                    if (msg.receiver_id === currentUserId && !msg.is_read) {
                        socket.emit('message_read', { messageId: msg.id, receiver_id: msg.sender_id });
                    }
                });
            });
    }
}

function loadUsers() {
    fetch('/api/users')
        .then(response => response.json())
        .then(data => {
            users = data;
            DOM.usersList.innerHTML = "";
            users.forEach(user => {
                if (user.id !== currentUserId) {
                    const div = document.createElement("div");
                    div.classList.add("list-item");
                    div.innerHTML = `<img src="${user.profile_image}" alt="${user.name}"><div class="details"><strong>${user.name}</strong><p>${user.lastSeen}</p></div>`;
                    div.onclick = () => startChat(user.id);
                    DOM.usersList.appendChild(div);
                }
            });
        });
}

function loadGroupUsers() {
    DOM.groupUsersList.innerHTML = "";
    users.forEach(user => {
        if (user.id !== currentUserId) {
            const div = document.createElement("div");
            div.classList.add("list-item");
            div.innerHTML = `<img src="${user.profile_image}" alt="${user.name}"><div class="details"><strong>${user.name}</strong><p>${user.lastSeen}</p></div><input type="checkbox" id="user-${user.id}" onchange="updateSelectedUsers(${user.id})">`;
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
    const newGroup = {id: Date.now(), name: groupName, creatorId: currentUserId, members: selectedUsers.concat(currentUserId), isGroup: true, messages: [], lastMessage: 'Grupo creado', unreadCount: 0};
    chats.push(newGroup);
    updateChatList();
    socket.emit('create_group', newGroup);
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
    const newChat = {id: Date.now(), name: user.name, memberId: userId, isGroup: false, messages: [], lastMessage: '', unreadCount: 0};
    chats.push(newChat);
    updateChatList();
    openConversation(newChat);
}

function updateChatList() {
    DOM.chatList.innerHTML = chats.length === 0 ? `<p class="empty-message">Inicie una nueva conversación</p>` : chats.map(chat => `
        <div class="list-item" onclick="openConversation(chats[${chats.indexOf(chat)}])">
            ${chat.isGroup ? `<svg viewBox="0 0 24 24" width="50" height="50" fill="#0D47A1" style="margin-right:12px;"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM9 12c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm7 0c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3z"/></svg>` : `<img src="${chat.isGroup ? 'https://www.svgrepo.com/show/452030/avatar-default.svg' : users.find(u => u.id === chat.memberId)?.profile_image}" alt="${chat.name}">`}
            <div class="details">
                <strong>${chat.name}</strong>
                <p>${chat.lastMessage || 'Sin mensajes'}</p>
            </div>
            ${chat.unreadCount > 0 ? `<span class="unread-count">${chat.unreadCount}</span>` : ''}
        </div>`).join('');
}

function openConversation(chat) {
    currentChat = chat;
    DOM.chatTitle.textContent = chat.name;
    if (!chat.isGroup) {
        const user = users.find(u => u.id === chat.memberId);
        DOM.chatUserImage.src = user.profile_image;
        DOM.chatStatus.textContent = user.isOnline ? "En línea" : user.lastSeen;
        fetch(`/api/messages/${chat.memberId}`)
            .then(response => response.json())
            .then(messages => {
                DOM.conversationArea.innerHTML = messages.length > 0 ? messages.map(msg => `
                    <div class="message ${msg.sender_id === currentUserId ? 'sent' : 'received'}" data-id="${msg.id}">${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div></div>`).join('') : `<div class="message received">¡Hola! Este es el inicio de tu conversación.</div>`;
                DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
                chat.unreadCount = 0;  // Resetear contador al abrir
                updateChatList();
            });
    } else {
        DOM.chatUserImage.src = "https://www.svgrepo.com/show/452030/avatar-default.svg";
        DOM.chatStatus.textContent = `${chat.members.length} miembros`;
        DOM.conversationArea.innerHTML = chat.messages.length > 0 ? chat.messages.map(msg => `
            <div class="message ${msg.sender_id === currentUserId ? 'sent' : 'received'}" data-id="${msg.id}">${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div></div>`).join('') : `<div class="message received">¡Este es el inicio del grupo!</div>`;
        DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
        chat.unreadCount = 0;  // Resetear contador al abrir
        updateChatList();
    }
    showScreen("screen-conversation");
}

function formatTime(date) {
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
}

function getStatusIcon(status) {
    if (!status || status === 'sent') return '<svg viewBox="0 0 24 24"><path fill="#1976D2" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    if (status === 'delivered') return '<svg viewBox="0 0 24 24"><path fill="#1976D2" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    if (status === 'read') return '<svg viewBox="0 0 24 24"><path fill="#4CAF50" d="M18 8l-8 8-4-4-1.5 1.5L10 19l9.5-9.5z"/></svg>';
    return '';
}

function sendMessage() {
    const input = DOM.messageInput;
    const text = sanitizeInput(input.value.trim());
    if (!text || !currentChat) return;

    const timestamp = new Date().toISOString();
    const message = {
        receiver_id: currentChat.isGroup ? currentChat.id : currentChat.memberId,
        text: text,
        timestamp: timestamp,
        status: 'sent'
    };
    
    socket.emit('send_message', message);
    input.value = '';
    currentChat.lastMessage = text;
    updateChatList();
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

function loadProfile() {
    const user = users.find(u => u.id === currentUserId);
    DOM.profileImage.src = user.profile_image;
    DOM.profileUsername.textContent = user.name;
    DOM.profileBio.textContent = user.bio || "Usuario nuevo";
    DOM.profileEmail.textContent = user.email;
    DOM.profilePhone.textContent = user.phone || "No especificado";
    DOM.profileDob.textContent = user.dob || "No especificado";

    document.querySelectorAll('.edit-btn').forEach(btn => {
        btn.onclick = () => {
            if (btn.dataset.field === 'profile_image') {
                alert("En desarrollo");
            } else {
                toggleEdit(btn, user);
            }
        };
    });
}

function toggleEdit(btn, user) {
    const field = btn.dataset.field;
    const element = DOM[`profile${field.charAt(0).toUpperCase() + field.slice(1)}`];
    if (btn.classList.contains('save')) {
        const newValue = sanitizeInput(element.querySelector('input').value);
        updateProfile(field, newValue);
        element.innerHTML = newValue;
        btn.classList.remove('save');
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>';
    } else {
        const currentValue = element.textContent;
        element.innerHTML = `<input type="text" value="${currentValue}">`;
        btn.classList.add('save');
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M19 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h4l3 3 3-3h4c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-7 17l-3-3h6l-3 3zm5-3H7V6h10v10z"/></svg>';
    }
}

function updateProfile(field, value) {
    fetch('/api/update_profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: value })
    })
    .then(response => response.json())
    .then(data => {
        users.find(u => u.id === currentUserId)[field] = value;
        socket.emit('profile_update', { userId: currentUserId, field, value });
    });
}

function showChatInfo() {
    if (!currentChat.isGroup) {
        const user = users.find(u => u.id === currentChat.memberId);
        showScreen('screen-profile');
        loadProfile(user);
        document.querySelectorAll('.edit-btn').forEach(btn => btn.style.display = 'none');
    } else if (currentChat.creatorId === currentUserId) {
        showScreen('screen-profile');
        DOM.profileImage.src = "https://www.svgrepo.com/show/452030/avatar-default.svg";
        DOM.profileUsername.textContent = currentChat.name;
        DOM.profileBio.textContent = currentChat.bio || "Grupo nuevo";
        DOM.profileEmail.textContent = `${currentChat.members.length} miembros`;
        DOM.profilePhone.style.display = 'none';
        DOM.profileDob.style.display = 'none';
    } else {
        // Info de grupo solo lectura pendiente
    }
}

function sendTypingStatus() {
    socket.emit('typing', { chatId: currentChat.id || currentChat.memberId });
}

document.addEventListener('DOMContentLoaded', () => {
    socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
    
    if (localStorage.getItem('userId')) {
        currentUserId = localStorage.getItem('userId');
    }

    fetch('/api/users')
        .then(response => response.json())
        .then(data => {
            users = data;
            if (!currentUserId) {
                currentUserId = users.find(u => u.name === document.querySelector('meta[name="username"]').content).id;
                localStorage.setItem('userId', currentUserId);
            }
            updateChatList();
            document.getElementById("openNewChat").addEventListener("click", () => showScreen("screen-new-chat"));
        });

    socket.on('new_message', (msg) => {
        const isCurrentChat = currentChat && ((currentChat.isGroup && msg.receiver_id === currentChat.id) || (!currentChat.isGroup && (msg.sender_id === currentChat.memberId || msg.receiver_id === currentChat.memberId)));
        let chat = chats.find(c => (c.isGroup && c.id === msg.receiver_id) || (!c.isGroup && (c.memberId === msg.sender_id || c.memberId === msg.receiver_id)));
        
        if (!chat) {
            chat = {id: msg.id, name: users.find(u => u.id === (msg.sender_id === currentUserId ? msg.receiver_id : msg.sender_id))?.name, 
                    memberId: msg.sender_id === currentUserId ? msg.receiver_id : msg.sender_id, isGroup: false, messages: [], lastMessage: msg.text, unreadCount: 0};
            chats.push(chat);
        }
        
        chat.lastMessage = msg.text;
        if (!isCurrentChat && msg.receiver_id === currentUserId) {
            chat.unreadCount = (chat.unreadCount || 0) + 1;
        }
        
        updateChatList();
        
        if (isCurrentChat) {
            const messageDiv = document.createElement("div");
            messageDiv.className = `message ${msg.sender_id === currentUserId ? 'sent' : 'received'}`;
            messageDiv.dataset.id = msg.id;
            messageDiv.innerHTML = `${msg.text}<div class="message-status">${formatTime(new Date(msg.timestamp))}${msg.sender_id === currentUserId ? getStatusIcon(msg.status) : ''}</div>`;
            DOM.conversationArea.appendChild(messageDiv);
            DOM.conversationArea.scrollTop = DOM.conversationArea.scrollHeight;
            socket.emit('message_delivered', { messageId: msg.id, receiver_id: msg.receiver_id });
        }
    });

    socket.on('new_chat', (chatData) => {
        if (!chats.find(c => c.id === chatData.id)) {
            chats.push(chatData);
            updateChatList();
        }
    });

    socket.on('message_delivered', (data) => {
        const msg = document.querySelector(`.message[data-id="${data.messageId}"]`);
        if (msg) msg.querySelector('.message-status').innerHTML = `${formatTime(new Date())} ${getStatusIcon('delivered')}`;
    });

    socket.on('message_read', (data) => {
        const msg = document.querySelector(`.message[data-id="${data.messageId}"]`);
        if (msg) msg.querySelector('.message-status').innerHTML = `${formatTime(new Date())} ${getStatusIcon('read')}`;
    });

    socket.on('typing', (data) => {
        if (currentChat && data.chatId === (currentChat.isGroup ? currentChat.id : currentChat.memberId)) {
            DOM.chatStatus.textContent = 'Escribiendo...';
            setTimeout(() => DOM.chatStatus.textContent = users.find(u => u.id === currentChat.memberId)?.isOnline ? "En línea" : "Última vez: " + users.find(u => u.id === currentChat.memberId)?.lastSeen, 2000);
        }
    });

    socket.on('profile_update', (data) => {
        const user = users.find(u => u.id === data.userId);
        if (user) user[data.field] = data.value;
        if (currentChat && currentChat.memberId === data.userId) {
            DOM.chatTitle.textContent = user.name;
        }
    });

    socket.on('user_status', (data) => {
        const user = users.find(u => u.id === data.userId);
        if (user) {
            user.isOnline = data.isOnline;
            user.lastSeen = data.lastSeen;
            if (currentChat && currentChat.memberId === data.userId) {
                DOM.chatStatus.textContent = user.isOnline ? "En línea" : `Última vez: ${user.lastSeen}`;
            }
            updateChatList();
        }
    });
});
