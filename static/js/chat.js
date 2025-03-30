document.addEventListener('DOMContentLoaded', () => {
    const socket = io();
    const username = sessionStorage.getItem('username');
    
    // Elementos del DOM
    const chatScreen = document.getElementById('chat-screen');
    const chatsScreen = document.getElementById('chats-screen');
    const profileScreen = document.getElementById('profile-screen');
    const backButton = document.getElementById('back-button');
    const backProfileButton = document.getElementById('back-profile-button');
    const profileButton = document.getElementById('profile-button');
    const userList = document.getElementById('user-list');
    const messageContainer = document.getElementById('message-container');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const saveButton = document.getElementById('save-button');
    const editButtons = document.querySelectorAll('.edit-button');
    const chatTitle = document.getElementById('chat-title');
    
    // Variables de estado
    let currentChat = null;
    
    // Inicializar la aplicación
    if (!username) {
        window.location.href = '/';
    } else {
        // Configurar el perfil con el nombre de usuario
        document.getElementById('profile-name').value = username;
        document.getElementById('profile-username').value = `@${username.toLowerCase()}`;
        document.getElementById('profile-fullname').value = username;
        
        // Generar avatar
        const avatarUrl = `https://ui-avatars.com/api/?name=${username}&background=random`;
        document.getElementById('profile-avatar').style.backgroundImage = `url('${avatarUrl}')`;
        
        // Emitir evento de login al servidor
        socket.emit('login', { username }, (response) => {
            if (response.status !== 'success') {
                alert(response.message);
                window.location.href = '/';
            }
        });
    }
    
    // Navegación entre pantallas
    profileButton.addEventListener('click', () => {
        chatsScreen.classList.remove('active');
        profileScreen.classList.add('active');
    });
    
    backButton.addEventListener('click', () => {
        chatScreen.classList.remove('active');
        chatsScreen.classList.add('active');
        currentChat = null;
    });
    
    backProfileButton.addEventListener('click', () => {
        profileScreen.classList.remove('active');
        chatsScreen.classList.add('active');
    });
    
    // Función para enviar mensajes
    function sendMessage() {
        const messageText = messageInput.value.trim();
        if (messageText) {
            socket.emit('send_message', { 
                message: messageText,
                recipient: currentChat
            });
            
            // Agregar mensaje localmente
            const messageElement = createMessageElement({
                sender: username,
                message: messageText,
                timestamp: new Date().toISOString(),
                avatar: `https://ui-avatars.com/api/?name=${username}&background=random`
            }, true);
            
            messageContainer.appendChild(messageElement);
            messageInput.value = "";
            messageContainer.scrollTop = messageContainer.scrollHeight;
        }
    }
    
    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {
        if (e.key === "Enter") {
            sendMessage();
        }
    });
    
    // Función para crear elementos de mensaje
    function createMessageElement(message, isSent = false) {
        const messageElement = document.createElement('div');
        messageElement.className = `message ${isSent ? 'sent' : 'received'}`;
        
        const time = new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        messageElement.innerHTML = `
            <div class="message-bubble">${message.message}</div>
            <div class="message-status">
                <div class="message-time">${time}</div>
                ${isSent ? '<div class="status-icon status-sent"><svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg></div>' : ''}
            </div>
        `;
        
        return messageElement;
    }
    
    // Función para crear elementos de usuario
    function createUserElement(user) {
        const userElement = document.createElement('div');
        userElement.className = 'chat-item';
        userElement.dataset.username = user.username;
        
        userElement.innerHTML = `
            <div class="chat-avatar" style="background-image: url('${user.avatar}')">${user.username.charAt(0)}</div>
            <div class="chat-info">
                <div class="chat-name">${user.username}</div>
                <div class="chat-preview">${user.status || 'En línea'}</div>
            </div>
        `;
        
        userElement.addEventListener('click', () => {
            currentChat = user.username;
            chatTitle.textContent = user.username;
            chatsScreen.classList.remove('active');
            chatScreen.classList.add('active');
            
            // Limpiar mensajes anteriores
            messageContainer.innerHTML = '';
        });
        
        return userElement;
    }
    
    // Funcionalidad de edición de perfil
    editButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const inputField = document.getElementById(targetId);
            
            if (inputField.readOnly) {
                // Cambiar a modo edición
                inputField.readOnly = false;
                inputField.focus();
                this.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/>
                    </svg>
                `;
                this.style.color = "var(--primary)";
            } else {
                // Guardar cambios
                inputField.readOnly = true;
                this.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                    </svg>
                `;
                this.style.color = "var(--text-secondary)";
                
                // Actualizar perfil en el servidor
                const profileData = {
                    name: document.getElementById('profile-name').value,
                    username: document.getElementById('profile-username').value,
                    fullname: document.getElementById('profile-fullname').value,
                    phone: document.getElementById('profile-phone').value
                };
                
                socket.emit('update_profile', profileData);
            }
        });
    });
    
    saveButton.addEventListener('click', () => {
        const profileData = {
            name: document.getElementById('profile-name').value,
            username: document.getElementById('profile-username').value,
            fullname: document.getElementById('profile-fullname').value,
            phone: document.getElementById('profile-phone').value
        };
        
        socket.emit('update_profile', profileData, (response) => {
            if (response.status === 'success') {
                alert('Perfil actualizado correctamente');
            } else {
                alert('Error al actualizar el perfil');
            }
        });
    });
    
    // Eventos Socket.IO
    socket.on('user_connected', (data) => {
        // Actualizar lista de usuarios
        userList.innerHTML = '';
        data.users.forEach(user => {
            userList.appendChild(createUserElement(user));
        });
    });
    
    socket.on('user_disconnected', (data) => {
        // Eliminar usuario de la lista
        const userElement = userList.querySelector(`[data-username="${data.username}"]`);
        if (userElement) {
            userElement.remove();
        }
    });
    
    socket.on('new_message', (message) => {
        // Solo mostrar mensajes del chat actual
        if (currentChat === message.sender || message.recipient === username) {
            const isSent = message.sender === username;
            const messageElement = createMessageElement(message, isSent);
            messageContainer.appendChild(messageElement);
            messageContainer.scrollTop = messageContainer.scrollHeight;
        }
    });
    
    socket.on('profile_updated', (data) => {
        // Actualizar perfil si es el usuario actual
        if (data.username === username) {
            document.getElementById('profile-name').value = data.profile.name;
            document.getElementById('profile-username').value = data.profile.username;
            document.getElementById('profile-fullname').value = data.profile.fullname;
            document.getElementById('profile-phone').value = data.profile.phone;
            
            // Actualizar avatar
            document.getElementById('profile-avatar').style.backgroundImage = 
                `url('https://ui-avatars.com/api/?name=${data.profile.name}&background=random')`;
        }
    });
});