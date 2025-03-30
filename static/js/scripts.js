const socket = io(`wss://${window.location.host}`, { transports: ['websocket'] });
let currentChat = null;
let allUsers = [];
let isRegisterMode = false;
let userId = localStorage.getItem('user_id');
let token = localStorage.getItem('token');

// Funciones compartidas
function showError(message, container = document.body) {
    const errorElement = document.createElement('div');
    errorElement.className = 'error-message';
    errorElement.textContent = message;
    container.appendChild(errorElement);
    setTimeout(() => errorElement.remove(), 5000);
}

// Configuración de Socket.IO
function setupSocketIO() {
    socket.on('connect', () => console.log('Connected to Socket.IO'));
    socket.on('disconnect', () => setTimeout(setupSocketIO, 5000));
    
    // Eventos de login.html
    socket.on('username_status', (data) => {
        if (!data.available && isRegisterMode) showError(data.message);
    });
    socket.on('registered', handleAuthSuccess);
    socket.on('logged_in', handleAuthSuccess);
    socket.on('register_error', (data) => showError(data.message));
    socket.on('login_error', (data) => showError(data.message));
    
    // Eventos de chat.html
    socket.on('presence_update', (data) => {
        if (window.location.pathname === '/chat') updateUserStatus(data.user_id, data.online);
    });
    socket.on('new_post', (data) => {
        if (window.location.pathname === '/chat') addPost(data);
    });
    socket.on('new_message', (data) => {
        if (window.location.pathname === '/chat') displayMessage(data);
    });
    socket.on('avatar_updated', (data) => {
        if (window.location.pathname === '/chat' && data.user_id === userId) {
            const profileImage = document.getElementById('profileImage');
            if (profileImage) profileImage.src = data.profile_image;
        }
    });
    socket.on('profile_updated', (data) => {
        if (window.location.pathname === '/chat' && data.user_id === userId) {
            const field = data.field.charAt(0).toUpperCase() + data.field.slice(1);
            const fieldElement = document.getElementById(`profile${field}`);
            if (fieldElement) fieldElement.textContent = data[data.field];
            const user = JSON.parse(localStorage.getItem('user_data'));
            user[data.field] = data[data.field];
            localStorage.setItem('user_data', JSON.stringify(user));
        }
    });
    socket.on('account_deleted', () => {
        if (window.location.pathname === '/chat') {
            localStorage.clear();
            socket.disconnect();
            window.location.href = '/login';
        }
    });
    socket.on('delete_error', (data) => {
        if (window.location.pathname === '/chat') showError(data.message);
    });
    socket.on('user_count_update', (data) => {
        const userCount = document.getElementById('userCount');
        if (userCount) userCount.textContent = data.total_users;
    });
    socket.on('users_list', (data) => {
        if (window.location.pathname === '/chat') {
            allUsers = data.users;
            loadUsers('');
        }
    });
}

function handleAuthSuccess(data) {
    localStorage.setItem('token', data.session_id);
    localStorage.setItem('user_id', data.user_id);
    localStorage.setItem('user_data', JSON.stringify(data));
    userId = data.user_id;
    token = data.session_id;
    window.location.href = '/chat';
}

// Funciones de login.html
function setupLogin() {
    const nameField = document.getElementById('name');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    if (!loginBtn || !registerBtn || !nameField) return;

    registerBtn.addEventListener('click', (e) => {
        if (!isRegisterMode) {
            e.preventDefault();
            nameField.classList.remove('hidden');
            loginBtn.classList.add('hidden');
            registerBtn.textContent = 'Crear Cuenta';
            registerBtn.classList.replace('btn-secondary', 'btn-primary');
            isRegisterMode = true;
        }
    });

    const usernameInput = document.getElementById('username');
    if (usernameInput) {
        usernameInput.addEventListener('input', () => {
            if (isRegisterMode) {
                const username = usernameInput.value.trim();
                if (username) socket.emit('check_username', { username });
            }
        });
    }

    const handleAuth = () => {
        const username = document.getElementById('username')?.value.trim();
        const password = document.getElementById('password')?.value.trim();
        const name = isRegisterMode ? nameField.value.trim() : '';

        if (!username || !password || (isRegisterMode && !name)) {
            showError('Todos los campos son requeridos');
            return;
        }
        if (!username.startsWith('@')) {
            showError('El usuario debe comenzar con @');
            return;
        }

        const authData = { username, password };
        if (isRegisterMode) {
            authData.name = name;
            socket.emit('register', authData);
        } else {
            socket.emit('login', authData);
        }
    };

    loginBtn.addEventListener('click', handleAuth);
    registerBtn.addEventListener('click', (e) => {
        if (isRegisterMode) handleAuth();
    });
}

// Funciones de chat.html
function showScreen(screenId) {
    const screens = document.querySelectorAll('.screen');
    if (!screens.length) return;
    screens.forEach(s => {
        s.classList.remove('active');
        s.style.transform = 'translateX(100%)';
    });
    const target = document.getElementById(screenId);
    if (target) {
        target.classList.add('active');
        target.style.transform = 'translateX(0)';
    }
}

function switchTab(tab) {
    const tabButtons = document.querySelectorAll('.tab-btn');
    if (!tabButtons.length) return;
    tabButtons.forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const button = document.querySelector(`.tab-btn[onclick="switchTab('${tab}')"]`);
    if (button) button.classList.add('active');
    const content = document.getElementById(`${tab}-content`);
    if (content) content.classList.add('active');
    const mainTitle = document.getElementById('main-title');
    if (mainTitle) mainTitle.textContent = tab === 'chats' ? 'Chats' : 'Publicaciones';
}

function loadProfile() {
    const user = JSON.parse(localStorage.getItem('user_data'));
    if (!user) return;
    const profileName = document.getElementById('profileName');
    const profileUsername = document.getElementById('profileUsername');
    const profileBio = document.getElementById('profileBio');
    const profileImage = document.getElementById('profileImage');
    if (profileName) profileName.textContent = user.name;
    if (profileUsername) profileUsername.textContent = user.username;
    if (profileBio) profileBio.textContent = user.bio || "Sin biografía";
    if (profileImage) profileImage.src = user.profile_image;
}

async function updateProfile(field, value) {
    try {
        socket.emit('update_profile', { field, value });
        return true;
    } catch (e) {
        showError('Error al actualizar');
        return false;
    }
}

async function updateProfileImage(file) {
    try {
        const reader = new FileReader();
        reader.onload = () => {
            socket.emit('update_avatar', { file: { type: file.type, data: reader.result } });
        };
        reader.readAsDataURL(file);
        return true;
    } catch (e) {
        showError('Error al cambiar la imagen');
        return false;
    }
}

function setupProfileEditButtons() {
    const editButtons = document.querySelectorAll('.edit-btn[data-field]');
    if (!editButtons.length) return;
    editButtons.forEach(btn => {
        btn.addEventListener('click', async () => {
            const field = btn.getAttribute('data-field');
            const fieldElement = document.getElementById(`profile${field.charAt(0).toUpperCase() + field.slice(1)}`);
            if (!fieldElement) return;
            const currentValue = fieldElement.textContent;
            const newValue = prompt(`Nuevo ${field}:`, currentValue);
            if (newValue && newValue !== currentValue) {
                const success = await updateProfile(field, newValue);
                if (success) fieldElement.textContent = newValue;
            }
        });
    });

    const profileImageInput = document.getElementById('profileImageInput');
    if (profileImageInput) {
        profileImageInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files[0]) {
                updateProfileImage(e.target.files[0]);
            }
        });
    }
}

function deleteAccount() {
    if (!confirm('¿Estás seguro de eliminar tu cuenta? Esta acción no se puede deshacer y eliminará todos tus datos del servidor.')) return;
    socket.emit('delete_account');
}

function loadUsers(searchTerm) {
    const usersList = document.getElementById('usersList');
    if (!usersList) return;
    usersList.innerHTML = '';
    const filteredUsers = allUsers.filter(user => 
        user.username.toLowerCase().includes(searchTerm.toLowerCase())
    );
    filteredUsers.forEach(user => {
        const userElement = document.createElement('div');
        userElement.className = 'user-item';
        userElement.innerHTML = `
            <img src="${user.profile_image}" class="user-avatar" alt="Avatar">
            <div>
                <strong>${user.name}</strong> @${user.username}
                <span class="status ${user.online ? 'online' : 'offline'}"></span>
            </div>
        `;
        userElement.onclick = () => startChat(user.id, user.name, user.profile_image);
        usersList.appendChild(userElement);
    });
}

function startChat(userId, name, avatar) {
    currentChat = userId;
    const chatTitle = document.getElementById('chatTitle');
    const chatUserImage = document.getElementById('chatUserImage');
    const conversationArea = document.getElementById('conversationArea');
    if (chatTitle) chatTitle.textContent = name;
    if (chatUserImage) chatUserImage.src = avatar;
    if (conversationArea) conversationArea.innerHTML = '';
    showScreen('screen-conversation');
}

function displayMessage(message) {
    const conversationArea = document.getElementById('conversationArea');
    if (!conversationArea) return;
    if ((message.sender_id === currentChat && message.receiver_id === userId) || 
        (message.sender_id === userId && message.receiver_id === currentChat)) {
        const msgElement = document.createElement('div');
        msgElement.className = `message ${message.sender_id === userId ? 'sent' : 'received'}`;
        msgElement.innerHTML = `
            <p>${message.text}</p>
            <small>${new Date(message.created_at).toLocaleTimeString()}</small>
        `;
        conversationArea.appendChild(msgElement);
        conversationArea.scrollTop = conversationArea.scrollHeight;
    }
    updateChatList(message);
}

function updateChatList(message) {
    const chatList = document.getElementById('chatList');
    if (!chatList) return;
    const existingChat = document.querySelector(`.chat-item[data-user-id="${message.sender_id}"]`);
    if (!existingChat && message.sender_id !== userId) {
        const sender = allUsers.find(u => u.id === message.sender_id) || { name: 'Usuario', profile_image: '/static/default-avatar.png' };
        const chatItem = document.createElement('div');
        chatItem.className = 'chat-item';
        chatItem.dataset.userId = message.sender_id;
        chatItem.innerHTML = `
            <img src="${sender.profile_image}" class="chat-avatar" alt="Avatar">
            <div>
                <strong>${sender.name}</strong>
                <p>${message.text.slice(0, 20)}...</p>
            </div>
        `;
        chatItem.onclick = () => startChat(message.sender_id, sender.name, sender.profile_image);
        chatList.appendChild(chatItem);
    }
}

function sendMessage() {
    const messageInput = document.getElementById('messageInput');
    if (!messageInput) return;
    const text = messageInput.value.trim();
    if (text && currentChat) {
        socket.emit('send_message', { receiver_id: currentChat, text });
        messageInput.value = '';
    }
}

function handleKeyPress(event) {
    if (event.key === 'Enter') sendMessage();
}

function updateUserStatus(user_id, online) {
    const status = document.getElementById('chatStatus');
    if (currentChat === user_id && status) {
        status.textContent = online ? 'En línea' : 'Desconectado';
        status.className = `chat-header-status ${online ? 'online' : 'offline'}`;
    }
}

function addPost(post) {
    const postsList = document.getElementById('postsList');
    if (!postsList) return;
    postsList.innerHTML = '';
    const postElement = document.createElement('div');
    postElement.className = 'post-item';
    postElement.innerHTML = `
        <img src="${post.profile_image}" class="post-avatar" alt="Avatar">
        <div>
            <strong>${post.name}</strong> @${post.username}
            <p>${post.text || ''}</p>
            ${post.image_path ? `<img src="${post.image_path}" class="post-image">` : ''}
            <small>${new Date(post.created_at).toLocaleString()}</small>
        </div>
    `;
    postsList.appendChild(postElement);
}

async function createPost() {
    const postText = document.getElementById('postText');
    const postImage = document.getElementById('postImage');
    if (!postText || !postImage) return;
    const text = postText.value.trim();
    const file = postImage.files[0];
    if (!text && !file) {
        showError('Debes incluir texto o una imagen');
        return;
    }

    try {
        if (file) {
            const reader = new FileReader();
            reader.onload = () => {
                socket.emit('create_post', {
                    text,
                    file: { type: file.type, data: reader.result }
                });
            };
            reader.readAsDataURL(file);
        } else {
            socket.emit('create_post', { text });
        }
        postText.value = '';
        postImage.value = '';
        const imagePreview = document.getElementById('imagePreview');
        if (imagePreview) imagePreview.innerHTML = '';
        showScreen('screen-main');
    } catch (e) {
        showError('Error al crear la publicación');
    }
}

function logout() {
    localStorage.clear();
    socket.disconnect();
    window.location.href = '/login';
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    setupSocketIO();
    
    if (window.location.pathname === '/login') {
        setupLogin();
    } else if (window.location.pathname === '/chat') {
        if (!token || !userId) {
            window.location.href = '/login';
            return;
        }
        loadProfile();
        setupProfileEditButtons();

        const openNewChat = document.getElementById('openNewChat');
        if (openNewChat) {
            openNewChat.addEventListener('click', () => {
                showScreen('screen-new-chat');
                socket.emit('get_users');
            });
        }

        const openNewPost = document.getElementById('openNewPost');
        if (openNewPost) {
            openNewPost.addEventListener('click', () => showScreen('screen-new-post'));
        }

        const postImage = document.getElementById('postImage');
        if (postImage) {
            postImage.addEventListener('change', (e) => {
                const file = e.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (e) => {
                    const imagePreview = document.getElementById('imagePreview');
                    if (imagePreview) imagePreview.innerHTML = `<img src="${e.target.result}">`;
                };
                reader.readAsDataURL(file);
            });
        }

        const userSearch = document.getElementById('userSearch');
        if (userSearch) {
            userSearch.addEventListener('input', (e) => loadUsers(e.target.value.trim()));
        }

        const messageInput = document.getElementById('messageInput');
        if (messageInput) {
            messageInput.addEventListener('keypress', handleKeyPress);
        }
    }
});