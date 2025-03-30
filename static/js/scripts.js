// static/js/scripts.js
const socket = io(`ws://${window.location.host}:5000`, { transports: ['websocket'] });
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

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(screen => screen.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
    if (screenId === 'screen-chat') {
        const chatTitle = document.getElementById('chat-title');
        if (chatTitle && currentChat) {
            chatTitle.textContent = currentChat.name;
        }
        loadChatMessages(currentChat ? currentChat.username : null);
    } else if (screenId === 'screen-feed') {
        loadPosts();
    }
}

function handleAuthSuccess(data) {
    localStorage.setItem('token', data.token);
    localStorage.setItem('user_id', data.userId);
    userId = data.userId;
    token = data.token;
    window.location.href = '/chat';
}

function connectSocketIO() {
    socket.on('connect', () => console.log('Connected to Socket.IO'));
    socket.on('disconnect', () => setTimeout(connectSocketIO, 5000));

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
        if (window.location.pathname === '/chat' && document.getElementById('feed')) {
            const feed = document.getElementById('feed');
            const postDiv = document.createElement('div');
            postDiv.className = 'post';
            postDiv.innerHTML = `<strong>${data.username}:</strong> <p>${data.text}</p>${data.image ? `<img src="${data.image}" style="max-width: 100%;">` : ''}`;
            feed.prepend(postDiv);
        }
    });
    socket.on('posts_list', (data) => {
        const feed = document.getElementById('feed');
        if (feed) {
            feed.innerHTML = '';
            data.posts.forEach(post => {
                const postDiv = document.createElement('div');
                postDiv.className = 'post';
                postDiv.innerHTML = `<strong>${post.username}:</strong> <p>${post.text}</p>${post.image ? `<img src="${post.image}" style="max-width: 100%;">` : ''}`;
                feed.appendChild(postDiv);
            });
        }
    });
    socket.on('users_list', (data) => {
        const usersListDiv = document.getElementById('usersList');
        if (usersListDiv) {
            usersListDiv.innerHTML = '';
            allUsers = data.users;
            allUsers.forEach(user => {
                const userDiv = document.createElement('div');
                userDiv.className = 'user-item';
                userDiv.innerHTML = `<span class="username">${user.username}</span> <span class="status ${user.online ? 'online' : 'offline'}"></span>`;
                userDiv.addEventListener('click', () => startChat(user));
                usersListDiv.appendChild(userDiv);
            });
        }
    });
    socket.on('chat_messages', (data) => {
        const messagesDiv = document.getElementById('messages');
        if (messagesDiv && data.username === currentChat.username) {
            messagesDiv.innerHTML = '';
            data.messages.forEach(msg => {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                messageDiv.textContent = `${msg.sender}: ${msg.text}`;
                messagesDiv.appendChild(messageDiv);
            });
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
    });
    socket.on('message_received', (data) => {
        if (currentChat && data.sender === currentChat.username) {
            const messagesDiv = document.getElementById('messages');
            if (messagesDiv) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                messageDiv.textContent = `${data.sender}: ${data.text}`;
                messagesDiv.appendChild(messageDiv);
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }
        } else if (window.location.pathname === '/chat' && data.sender !== localStorage.getItem('username')) {
            loadChats(); // Reload chats to show new message
        }
    });
    socket.on('profile_data', (data) => {
        document.getElementById('profileName').textContent = data.name;
        document.getElementById('profileUsername').textContent = data.username;
        const profileImg = document.getElementById('profileImg');
        if (profileImg) profileImg.src = data.profile_image || '/static/images/default_avatar.png';
    });
    socket.on('profile_updated', (data) => {
        document.getElementById('profileName').textContent = data.name;
        setupProfileEditButtons(); // Hide input after saving
    });
    socket.on('profile_image_updated', (data) => {
        const profileImg = document.getElementById('profileImg');
        if (profileImg) profileImg.src = data.profile_image;
    });
    socket.on('upload_error', (data) => showError(data.message, document.getElementById('screen-profile')));
    socket.on('account_deleted', () => {
        localStorage.clear();
        window.location.href = '/login';
    });
    socket.on('delete_error', (data) => showError(data.message, document.getElementById('screen-profile')));
    socket.on('auth_error', (data) => {
        showError(data.message);
        localStorage.clear();
        window.location.href = '/login';
    });
    socket.on('error', (error) => console.error('Socket.IO Error:', error));
}

function loadProfile() {
    socket.emit('get_profile');
}

function setupProfileEditButtons() {
    const editNameBtn = document.getElementById('editNameBtn');
    const editNameInput = document.getElementById('editNameInput');
    const profileNameSpan = document.getElementById('profileName');

    if (editNameBtn && editNameInput && profileNameSpan) {
        editNameBtn.onclick = () => {
            profileNameSpan.style.display = 'none';
            editNameBtn.style.display = 'none';
            editNameInput.style.display = 'block';
            document.getElementById('newName').value = profileNameSpan.textContent;
        };
        const cancelBtn = editNameInput.querySelector('button:last-child');
        if (cancelBtn) {
            cancelBtn.onclick = () => {
                profileNameSpan.style.display = 'inline';
                editNameBtn.style.display = 'inline';
                editNameInput.style.display = 'none';
            };
        }
    }

    const uploadBtn = document.getElementById('uploadProfileImageBtn');
    const fileInput = document.getElementById('profileImageFile');
    if (uploadBtn && fileInput) {
        uploadBtn.onclick = () => fileInput.click();
        fileInput.onchange = (event) => {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    socket.emit('upload_profile_image', { image_data: e.target.result.split(',')[1] });
                };
                reader.readAsDataURL(file);
            }
        };
    }
}

function saveProfileName() {
    const newName = document.getElementById('newName').value.trim();
    if (newName) {
        socket.emit('update_profile', { name: newName });
    }
}

function deleteAccount() {
    if (confirm('¿Estás seguro de que deseas eliminar tu cuenta? Esta acción es irreversible.')) {
        socket.emit('delete_account');
    }
}

function loadUsers(query = '') {
    const filteredUsers = allUsers.filter(user => user.username.toLowerCase().includes(query.toLowerCase()));
    const usersListDiv = document.getElementById('usersList');
    if (usersListDiv) {
        usersListDiv.innerHTML = '';
        filteredUsers.forEach(user => {
            const userDiv = document.createElement('div');
            userDiv.className = 'user-item';
            userDiv.innerHTML = `<span class="username">${user.username}</span> <span class="status ${user.online ? 'online' : 'offline'}"></span>`;
            userDiv.addEventListener('click', () => startChat(user));
            usersListDiv.appendChild(userDiv);
        });
    }
}

function startChat(user) {
    currentChat = user;
    showScreen('screen-chat');
}

function sendMessage() {
    const messageInput = document.getElementById('messageInput');
    if (messageInput.value.trim() && currentChat) {
        socket.emit('send_message', { recipient: currentChat.username, text: messageInput.value });
        messageInput.value = '';
    }
}

function loadChatMessages(username) {
    if (username) {
        socket.emit('get_chat_messages', { username: username });
    }
}

function loadChats() {
    // Implement logic to load the list of active chats if needed
    socket.emit('get_users'); // For simplicity, reusing get_users to show online status
}

function loadPosts() {
    socket.emit('get_posts');
}

function createPost() {
    const postText = document.getElementById('postText').value.trim();
    const imageInput = document.getElementById('postImage');
    const file = imageInput.files[0];
    let base64Image = null;

    if (file) {
        const reader = new FileReader();
        reader.onloadend = () => {
            base64Image = reader.result.split(',')[1];
            socket.emit('create_post', { text: postText, image: base64Image });
            document.getElementById('postText').value = '';
            document.getElementById('postImage').value = '';
            document.getElementById('imagePreview').innerHTML = '';
            showScreen('screen-feed');
        };
        reader.readAsDataURL(file);
    } else {
        socket.emit('create_post', { text: postText, image: null });
        document.getElementById('postText').value = '';
        showScreen('screen-feed');
    }
}

function logout() {
    localStorage.clear();
    socket.disconnect();
    window.location.href = '/login';
}

function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    if (!localStorage.getItem('token') || !localStorage.getItem('user_id')) {
        window.location.href = '/login';
        return;
    }

    connectSocketIO();
    loadProfile();
    setupProfileEditButtons();
    loadChats(); // Load initial list of chats or users for new chat

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
});
