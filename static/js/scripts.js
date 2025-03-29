const token = localStorage.getItem('token');
const userId = localStorage.getItem('user_id');
let currentChat = null;

// Configurar Pusher
const pusher = new Pusher('10ace857b488cb959660', {
    cluster: 'us3',
    encrypted: true,
    authEndpoint: '/pusher-auth',
    auth: { headers: { 'Authorization': 'Bearer ' + token } }
});

const channel = pusher.subscribe('private-' + userId);
channel.bind('new_message', (data) => {
    if (data.receiver_id === currentChat || data.sender_id === currentChat) {
        displayMessage(data);
    }
});
channel.bind('profile_update', updateProfile);

// Mostrar pantallas
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(screen => {
        screen.classList.remove('active');
        screen.style.transform = 'translateX(100%)';
    });
    const targetScreen = document.getElementById(screenId);
    targetScreen.classList.add('active');
    targetScreen.style.transform = 'translateX(0)';
}

// Cargar lista de chats
async function loadChats() {
    try {
        const response = await fetch('/api/users', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const users = await response.json();
        const chatList = document.getElementById('chatList');
        chatList.innerHTML = '';
        
        if (users.length <= 1) {
            document.getElementById('emptyMessage').style.display = 'block';
            return;
        }

        users.forEach(user => {
            if (user.id !== userId) {
                const div = document.createElement('div');
                div.className = 'list-item';
                div.innerHTML = `
                    <img src="${user.profile_image}" alt="${user.name}">
                    <div class="details">
                        <strong>${user.name}</strong>
                        <p>${user.isOnline ? 'En línea' : 'Últ. vez: ' + user.lastSeen}</p>
                    </div>
                `;
                div.onclick = () => startChat(user.id, user.name, user.profile_image, user.isOnline ? 'En línea' : 'Últ. vez: ' + user.lastSeen);
                chatList.appendChild(div);
            }
        });
    } catch (error) {
        console.error('Error loading chats:', error);
    }
}

// Cargar lista de usuarios para nuevo chat
async function loadUsers() {
    try {
        const response = await fetch('/api/users', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const users = await response.json();
        const usersList = document.getElementById('usersList');
        usersList.innerHTML = '';
        
        users.forEach(user => {
            if (user.id !== userId) {
                const div = document.createElement('div');
                div.className = 'list-item';
                div.innerHTML = `
                    <img src="${user.profile_image}" alt="${user.name}">
                    <div class="details">
                        <strong>${user.name}</strong>
                        <p>${user.bio || 'Usuario nuevo'}</p>
                    </div>
                `;
                div.onclick = () => startChat(user.id, user.name, user.profile_image, user.isOnline ? 'En línea' : 'Últ. vez: ' + user.lastSeen);
                usersList.appendChild(div);
            }
        });
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

// Iniciar chat
async function startChat(receiverId, name, image, status) {
    try {
        currentChat = receiverId;
        showScreen('screen-conversation');
        document.getElementById('chatTitle').textContent = name;
        document.getElementById('chatUserImage').src = image;
        document.getElementById('chatStatus').textContent = status;
        
        const response = await fetch(`/api/messages/${receiverId}`, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        
        if (!response.ok) throw new Error('Error fetching messages');
        
        const messages = await response.json();
        const conversationArea = document.getElementById('conversationArea');
        conversationArea.innerHTML = '';
        
        messages.forEach(msg => displayMessage(msg));
        conversationArea.scrollTop = conversationArea.scrollHeight;
    } catch (error) {
        console.error('Error starting chat:', error);
    }
}

// Mostrar mensaje
function displayMessage(msg) {
    const conversationArea = document.getElementById('conversationArea');
    const div = document.createElement('div');
    div.className = `message ${msg.sender_id === userId ? 'sent' : 'received'}`;
    div.innerHTML = `${msg.text} <div class="message-status">${new Date(msg.timestamp).toLocaleTimeString()}</div>`;
    conversationArea.appendChild(div);
    conversationArea.scrollTop = conversationArea.scrollHeight;
}

// Enviar mensaje
async function sendMessage() {
    const text = document.getElementById('messageInput').value.trim();
    if (!text || !currentChat) return;
    
    try {
        const formData = new FormData();
        formData.append('receiver_id', currentChat);
        formData.append('text', text);
        
        const response = await fetch('/api/send_message', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });
        
        if (response.ok) {
            document.getElementById('messageInput').value = '';
        } else {
            throw new Error('Error sending message');
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

// Eliminar conversación
async function deleteConversation() {
    if (!currentChat || !confirm('¿Seguro que deseas eliminar esta conversación?')) return;
    
    try {
        const response = await fetch(`/api/delete_chat/${currentChat}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        
        if (response.ok) {
            showScreen('screen-chats');
            loadChats();
        } else {
            throw new Error('Error deleting chat');
        }
    } catch (error) {
        console.error('Error:', error);
    }
}

// Cargar perfil propio
async function loadProfile() {
    try {
        const response = await fetch('/api/users', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const users = await response.json();
        const user = users.find(u => u.id === userId);
        
        if (user) {
            document.getElementById('profileImage').src = user.profile_image;
            document.getElementById('profileUsername').textContent = user.name;
            document.getElementById('profileBio').textContent = user.bio || 'Usuario nuevo';
            document.getElementById('profileEmail').textContent = user.email;
            document.getElementById('profilePhone').textContent = user.phone || 'No especificado';
            document.getElementById('profileDob').textContent = user.dob || 'No especificado';
        }
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

// Mostrar perfil de usuario
async function showUserProfile() {
    try {
        const response = await fetch('/api/users', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const users = await response.json();
        const user = users.find(u => u.id === currentChat);
        
        if (user) {
            document.getElementById('userProfileImage').src = user.profile_image;
            document.getElementById('userProfileUsername').textContent = user.name;
            document.getElementById('userProfileBio').textContent = user.bio || 'Usuario nuevo';
            document.getElementById('userProfileEmail').textContent = user.email;
            document.getElementById('userProfilePhone').textContent = user.phone || 'No especificado';
            document.getElementById('userProfileDob').textContent = user.dob || 'No especificado';
            showScreen('screen-user-profile');
        }
    } catch (error) {
        console.error('Error showing user profile:', error);
    }
}

// Subir imagen de perfil
async function uploadProfileImage() {
    const fileInput = document.getElementById('profileImageInput');
    if (!fileInput.files.length) return;
    
    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        
        const response = await fetch('/api/update_profile_image', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                loadProfile();
            }
        }
    } catch (error) {
        console.error('Error uploading profile image:', error);
    }
}

// Editar campos del perfil
document.querySelectorAll('.edit-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const field = btn.dataset.field;
        if (!field) return;
        
        const currentValue = document.getElementById(`profile${field.charAt(0).toUpperCase() + field.slice(1)}`).textContent;
        const newValue = prompt(`Editar ${field}`, currentValue);
        
        if (newValue && newValue !== currentValue) {
            try {
                const response = await fetch('/api/update_profile', {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ [field]: newValue })
                });
                
                if (response.ok) {
                    loadProfile();
                }
            } catch (error) {
                console.error('Error updating profile:', error);
            }
        }
    });
});

// Actualizar perfil
function updateProfile(data) {
    if (data.profile_image) {
        document.getElementById('profileImage').src = data.profile_image;
    }
    loadChats();
    if (currentChat) {
        startChat(currentChat, 
                document.getElementById('chatTitle').textContent, 
                document.getElementById('chatUserImage').src, 
                document.getElementById('chatStatus').textContent);
    }
}

// Eliminar cuenta
async function deleteAccount() {
    if (confirm('¿Estás seguro de que deseas eliminar tu cuenta? Esta acción es irreversible.')) {
        try {
            const response = await fetch('/api/delete_account', {
                method: 'DELETE',
                headers: { 'Authorization': 'Bearer ' + token }
            });
            
            if (response.ok) {
                localStorage.clear();
                window.location.href = '/logout';
            }
        } catch (error) {
            console.error('Error deleting account:', error);
            alert('Error al eliminar la cuenta');
        }
    }
}

// Crear grupo
function createGroup() {
    alert('Funcionalidad de grupos no implementada aún');
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    if (!token || !userId) {
        window.location.href = '/login';
        return;
    }

    loadChats();
    loadProfile();

    document.getElementById('openNewChat').addEventListener('click', () => {
        showScreen('screen-new-chat');
        loadUsers();
    });
});
