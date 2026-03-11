/* ─────────────────────────────────────────
   AUP FrançaisBot — Dashboard JavaScript
   ───────────────────────────────────────── */

let activePrompt = "";

/* ── Role Toggle ── */
function toggleRole(role) {
    const studentView = document.getElementById('studentView');
    const teacherView = document.getElementById('teacherView');
    const chatArea    = document.getElementById('chatArea');

    document.getElementById('roleStudent').classList.toggle('active', role === 'student');
    document.getElementById('roleTeacher').classList.toggle('active', role === 'teacher');

    // Hide chat when switching roles
    if (chatArea) chatArea.classList.add('hidden');

    if (role === 'student') {
        studentView.classList.remove('hidden');
        teacherView.classList.add('hidden');
    } else {
        teacherView.classList.remove('hidden');
        studentView.classList.add('hidden');
    }
}

/* ── Teacher: Assign Prompt ── */
function assignPrompt() {
    const val = document.getElementById('promptInput').value.trim();
    if (!val) return;
    activePrompt = val;
    alert('Sujet assigné avec succès !');
    const activePromptText = document.getElementById('activePromptText');
    if (activePromptText) activePromptText.innerText = val;
    document.getElementById('promptInput').value = "";
}

/* ── Student: Show Chat ── */
function showChat(mode) {
    document.getElementById('studentView').classList.add('hidden');
    document.getElementById('chatArea').classList.remove('hidden');

    const msgs = document.getElementById('chatMessages');
    const label = document.getElementById('currentAssignmentLabel');

    if (mode === 'assignment' && activePrompt) {
        label.innerText = "Sujet : " + activePrompt;
        msgs.innerHTML = `<div class="message bot">Bonjour ! Pour ce devoir, vous devez : <i>${activePrompt}</i>. Je suis prêt à vous corriger.</div>`;
    } else {
        label.innerText = "";
        msgs.innerHTML = `<div class="message bot">Bonjour ! Comment puis-je vous aider aujourd'hui ?</div>`;
    }
}

/* ── Back to Dashboard ── */
function backToDashboard() {
    document.getElementById('chatArea').classList.add('hidden');
    document.getElementById('studentView').classList.remove('hidden');
}

/* ── Send Message ── */
function handleSend() {
    const input = document.getElementById('userInput');
    const msg = input.value.trim();
    if (!msg) return;
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.innerHTML += `<div class="message user">${msg}</div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;
    input.value = '';
}

/* ── Enter key sends message ── */
document.addEventListener('DOMContentLoaded', () => {
    const userInput = document.getElementById('userInput');
    if (userInput) {
        userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleSend();
        });
    }
});