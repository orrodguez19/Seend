const token = localStorage.getItem('token');
const userId = localStorage.getItem('user_id');
let currentChat = null;
let currentPost = null;
let socket = null;

/* ========== FUNCIONES GENERALES ========== */
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => {
        s.classList.remove('active');
        s.style.transform = 'translateX(100%)';
    });
    const target = document.getElementById(screenId);
    target.classList.add('active');
    target.style.transform = 'translateX(0)';
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`.tab-btn[onclick="switchTab('${tab}')"]`).classList.add('active');
    document.getElementById(`${tab}-content`).classList.add('active');
    document.getElementById('main-title').textContent = tab === 'chats' ? 'Chats' : 'Publicaciones';
}

/* ========== WEBSOCKET ========== */
function connectWebSocket() {
    socket = new WebSocket(`wss://${window.location.host}/ws/${userId}?token=${token}`);

    socket.onopen = () => console.log("WebSocket connected");
    socket.onclose = () => setTimeout(connectWebSocket, 5000);
    socket.onmessage = (e) => {
        const data = JSON.parse(e.data);
        switch(data.type) {
            case 'new_message':
                if(data.receiver_id === currentChat || data.sender_id === currentChat) displayMessage(data);
                break;
            case 'presence':
                updateUserStatus(data.user_id, data.online);
                break;
            case 'writing':
                showWritingIndicator(data.user_id, data.status);
                break;
            case 'new_post':
                addPost(data);
                break;
            case 'post_reaction':
                updatePostReaction(data);
                break;
            case 'new_comment':
                addCommentToPost(data);
                break;
        }
    };
}

/* ========== PERFIL DE USUARIO ========== */
async function loadProfile() {
    try {
        const res = await fetch('/api/profile', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        const data = await res.json();

        document.getElementById('profileUsername').textContent = data.username;
        document.getElementById('profileBio').textContent = data.bio || "Sin biografía";
        document.getElementById('profileEmail').textContent = data.email;
        document.getElementById('profileImage').src = data.profile_image;
        
    } catch (e) {
        console.error('Error loading profile:', e);
        showError('Error al cargar el perfil');
    }
}

async function updateProfile(field, value) {
    try {
        const res = await fetch('/api/update-profile', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ field, value })
        });

        if (!res.ok) throw new Error('Error al actualizar');
        return true;
    } catch (e) {
        console.error('Error updating profile:', e);
        showError('Error al actualizar');
        return false;
    }
}

async function updateProfileImage(file) {
    try {
        const formData = new FormData();
        formData.append('image', file);

        const res = await fetch('/api/update-avatar', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            body: formData
        });

        const data = await res.json();
        if (data.success) {
            document.getElementById('profileImage').src = data.new_url;
            return true;
        }
        throw new Error('Error al actualizar imagen');
    } catch (e) {
        console.error('Error updating profile image:', e);
        showError('Error al cambiar la imagen');
        return false;
    }
}

async function deleteAccount() {
    if (!confirm('¿Estás seguro de eliminar tu cuenta? Esta acción no se puede deshacer.')) return;

    try {
        const res = await fetch('/api/delete-account', {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + token }
        });

        if (res.ok) {
            localStorage.clear();
            window.location.href = '/login';
        } else {
            throw new Error('Error al eliminar cuenta');
        }
    } catch (e) {
        console.error('Error deleting account:', e);
        showError('Error al eliminar la cuenta');
    }
}

function setupProfileEditButtons() {
    document.querySelectorAll('.edit-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const field = btn.getAttribute('data-field');
            const currentValue = document.getElementById(`profile${field.charAt(0).toUpperCase() + field.slice(1)}`).textContent;
            const newValue = prompt(`Nuevo ${field}:`, currentValue);

            if (newValue && newValue !== currentValue) {
                const success = await updateProfile(field, newValue);
                if (success) {
                    document.getElementById(`profile${field.charAt(0).toUpperCase() + field.slice(1)}`).textContent = newValue;
                }
            }
        });
    });

    document.getElementById('profileImageInput').addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
            updateProfileImage(e.target.files[0]);
        }
    });
}

/* ========== INICIALIZACIÓN ========== */
document.addEventListener('DOMContentLoaded', () => {
    if (!token || !userId) {
        window.location.href = '/login';
        return;
    }

    connectWebSocket();
    loadProfile();
    setupProfileEditButtons();

    // Resto de inicializaciones...
    document.getElementById('openNewChat').addEventListener('click', () => {
        showScreen('screen-new-chat');
        loadUsers();
    });

    document.getElementById('openNewPost').addEventListener('click', () => {
        showScreen('screen-new-post');
    });

    document.getElementById('postImage').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('imagePreview').innerHTML = `<img src="${e.target.result}">`;
        };
        reader.readAsDataURL(file);
    });
});

/* ========== UTILIDADES ========== */
function showError(message) {
    const errorElement = document.createElement('div');
    errorElement.className = 'error-message';
    errorElement.textContent = message;
    document.body.appendChild(errorElement);
    setTimeout(() => errorElement.remove(), 5000);
        }
