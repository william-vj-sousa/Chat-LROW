/* Dashboard JavaScript */

let activePrompt = "";

function renderMessage(role, message) {
    const cssRole = role === 'assistant' || role === 'system' ? 'bot' : 'user';
    return `<div class="message ${cssRole}">${message}</div>`;
}

function scrollChatToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

function loadChatHistory() {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;

    chatMessages.innerHTML = renderMessage('assistant', 'Chargement de votre conversation...');

    fetch('/chat/history')
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) {
                throw new Error(data.error || 'Unable to load chat history.');
            }

            const messages = data.messages || [];
            if (messages.length === 0) {
                chatMessages.innerHTML = renderMessage('assistant', "Bonjour ! Comment puis-je vous aider aujourd'hui ?");
            } else {
                chatMessages.innerHTML = messages
                    .map(entry => renderMessage(entry.role, entry.message))
                    .join('');
            }

            scrollChatToBottom();
        })
        .catch(error => {
            chatMessages.innerHTML = `<div class="message bot" style="color:red;">${error.message}</div>`;
        });
}

function toggleRole(role) {
    const studentView = document.getElementById('studentView');
    const teacherView = document.getElementById('teacherView');
    const chatArea = document.getElementById('chatArea');

    document.getElementById('roleStudent').classList.toggle('active', role === 'student');
    document.getElementById('roleTeacher').classList.toggle('active', role === 'teacher');

    if (chatArea) chatArea.classList.add('hidden');

    if (role === 'student') {
        studentView.classList.remove('hidden');
        teacherView.classList.add('hidden');
    } else {
        teacherView.classList.remove('hidden');
        studentView.classList.add('hidden');
    }
}

function assignPrompt() {
    const val = document.getElementById('promptInput').value.trim();
    if (!val) return;

    activePrompt = val;
    alert('Sujet assigne avec succes !');

    const activePromptText = document.getElementById('activePromptText');
    if (activePromptText) activePromptText.innerText = val;
    document.getElementById('promptInput').value = "";
}

function showChat(mode) {
    document.getElementById('studentView').classList.add('hidden');
    document.getElementById('chatArea').classList.remove('hidden');

    const msgs = document.getElementById('chatMessages');
    const label = document.getElementById('currentAssignmentLabel');

    if (mode === 'assignment' && activePrompt) {
        label.innerText = "Sujet : " + activePrompt;
        msgs.innerHTML = renderMessage('assistant', `Bonjour ! Pour ce devoir, vous devez : <i>${activePrompt}</i>. Je suis pret a vous corriger.`);
        scrollChatToBottom();
    } else {
        label.innerText = "";
        loadChatHistory();
    }
}

function backToDashboard() {
    document.getElementById('chatArea').classList.add('hidden');
    document.getElementById('studentView').classList.remove('hidden');
}

function handleSend() {
    const input = document.getElementById('userInput');
    const msg = input.value.trim();
    if (!msg) return;

    const chatMessages = document.getElementById('chatMessages');
    chatMessages.innerHTML += renderMessage('user', msg);
    scrollChatToBottom();
    input.value = '';

    fetch('/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: msg })
    })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) {
                throw new Error(data.error || 'Unable to save message.');
            }

            if (data.response) {
                chatMessages.innerHTML += renderMessage('assistant', data.response);
                scrollChatToBottom();
            }
        })
        .catch(error => {
            chatMessages.innerHTML += `<div class="message bot" style="color:red;">${error.message}</div>`;
            scrollChatToBottom();
        });
}

function clearChat() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.innerHTML = renderMessage('assistant', "Conversation effacee. Bonjour ! Comment puis-je vous aider aujourd'hui ?");

    fetch('/reset', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    }).catch(error => {
        chatMessages.innerHTML += `<div class="message bot" style="color:red;">${error.message}</div>`;
        scrollChatToBottom();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const userInput = document.getElementById('userInput');
    if (userInput) {
        userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleSend();
        });
    }
});
