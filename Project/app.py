from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import inspect, text
import os
import random
import string
from datetime import datetime
import requests

try:
    from pyngrok import ngrok
except ImportError:
    ngrok = None

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

GBT_URL = "http://localhost:4891/v1/chat/completions"
SYSTEM_PROMPT = (
    "Pretend you are a French teacher. "
    "You are teaching a class of beginner students. "
    "You are answering questions they have about grammar. "
    "After every response, correct them on their grammar, spelling, "
    "and make suggestions about tone."
)

NGROK_ENABLED = os.environ.get('ENABLE_NGROK', 'false').lower() == 'true'
NGROK_AUTHTOKEN = os.environ.get('NGROK_AUTHTOKEN')
NGROK_DOMAIN = os.environ.get('NGROK_DOMAIN')
PUBLIC_URL = None


# ── Models ──

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    messages = db.relationship('ChatHistory', backref='conversation', lazy=True)


class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500))
    join_code = db.Column(db.String(8), unique=True, nullable=False)
    active_prompt = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    memberships = db.relationship('ClassroomMembership', backref='classroom', lazy=True)


class ClassroomMembership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    # role: 'student' or 'teacher'
    role = db.Column(db.String(20), nullable=False, default='student')
    chats = db.relationship('ChatHistory', backref='user', lazy=True)
    conversations = db.relationship('Conversation', backref='user', lazy=True)
    classrooms_taught = db.relationship('Classroom', backref='teacher', lazy=True)
    classroom_memberships = db.relationship('ClassroomMembership', backref='student', lazy=True)


# ── Helpers ──

def generate_join_code(length=6):
    """Generate a random uppercase alphanumeric classroom join code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not Classroom.query.filter_by(join_code=code).first():
            return code


def ensure_chat_history_schema():
    inspector = inspect(db.engine)
    if 'chat_history' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('chat_history')}
    if 'created_at' not in columns:
        db.session.execute(text("ALTER TABLE chat_history ADD COLUMN created_at DATETIME"))
        if 'create_at' in columns:
            db.session.execute(text("UPDATE chat_history SET created_at = create_at WHERE create_at IS NOT NULL"))
        db.session.execute(text("UPDATE chat_history SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))

    if 'conversation_id' not in columns:
        db.session.execute(text("ALTER TABLE chat_history ADD COLUMN conversation_id INTEGER"))

    users_with_missing_conversations = db.session.execute(
        text("SELECT DISTINCT user_id FROM chat_history WHERE conversation_id IS NULL")
    ).fetchall()

    for row in users_with_missing_conversations:
        conversation = (
            Conversation.query
            .filter_by(user_id=row.user_id)
            .order_by(Conversation.created_at.asc(), Conversation.id.asc())
            .first()
        )
        if conversation is None:
            conversation = Conversation(user_id=row.user_id, title="Recovered conversation")
            db.session.add(conversation)
            db.session.flush()

        db.session.execute(
            text("UPDATE chat_history SET conversation_id = :conversation_id WHERE user_id = :user_id AND conversation_id IS NULL"),
            {"conversation_id": conversation.id, "user_id": row.user_id}
        )

    db.session.commit()


def ensure_user_role_column():
    """Add role column to existing user tables if missing."""
    inspector = inspect(db.engine)
    if 'user' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('user')}
    if 'role' not in columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'student'"))
        db.session.commit()


def get_or_create_active_conversation(user):
    conversation = (
        Conversation.query
        .filter_by(user_id=user.id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .first()
    )
    if conversation is None:
        conversation = Conversation(user_id=user.id, title=f"{user.username} main conversation")
        db.session.add(conversation)
        db.session.commit()
    return conversation


def resolve_conversation_for_user(user, conversation_id=None):
    if conversation_id is not None:
        conversation = Conversation.query.filter_by(id=conversation_id, user_id=user.id).first()
        if conversation is not None:
            return conversation
    return get_or_create_active_conversation(user)


def start_ngrok_tunnel(port):
    global PUBLIC_URL
    if not NGROK_ENABLED:
        return None
    if ngrok is None:
        print("[ngrok] pyngrok is not installed.")
        return None
    if NGROK_AUTHTOKEN:
        ngrok.set_auth_token(NGROK_AUTHTOKEN)
    tunnel_options = {"addr": port, "proto": "http"}
    if NGROK_DOMAIN:
        tunnel_options["domain"] = NGROK_DOMAIN
    tunnel = ngrok.connect(**tunnel_options)
    PUBLIC_URL = tunnel.public_url
    print(f"[ngrok] Public URL: {PUBLIC_URL}")
    return PUBLIC_URL


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ── Routes ──

@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Email ou mot de passe incorrect.')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirm_password']
        role = request.form.get('role', 'student')

        if role not in ('student', 'teacher'):
            flash('Rôle invalide.')
            return render_template('register.html')

        if password != confirm:
            flash('Les mots de passe ne correspondent pas.')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Un compte avec cet email existe déjà.')
            return render_template('register.html')

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, password=hashed_pw, role=role)
        db.session.add(new_user)
        db.session.commit()
        flash('Compte créé avec succès ! Connectez-vous.')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'teacher':
        classrooms = Classroom.query.filter_by(teacher_id=current_user.id).all()
        return render_template('dashboard_teacher.html', username=current_user.username, classrooms=classrooms)
    else:
        active_conversation = get_or_create_active_conversation(current_user)
        memberships = ClassroomMembership.query.filter_by(student_id=current_user.id).all()
        classrooms = [m.classroom for m in memberships]
        return render_template(
            'dashboard_student.html',
            username=current_user.username,
            active_conversation_id=active_conversation.id,
            classrooms=classrooms
        )


# ── Classroom Routes ──

@app.route('/classroom/create', methods=['POST'])
@login_required
def create_classroom():
    if current_user.role != 'teacher':
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()

    if not name:
        return jsonify({"error": "Le nom de la classe est requis."}), 400

    classroom = Classroom(
        teacher_id=current_user.id,
        name=name,
        description=description,
        join_code=generate_join_code()
    )
    db.session.add(classroom)
    db.session.commit()

    return jsonify({
        "id": classroom.id,
        "name": classroom.name,
        "description": classroom.description,
        "join_code": classroom.join_code,
        "student_count": 0
    })


@app.route('/classroom/join', methods=['POST'])
@login_required
def join_classroom():
    if current_user.role != 'student':
        return jsonify({"error": "Seuls les étudiants peuvent rejoindre une classe."}), 403

    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip().upper()

    if not code:
        return jsonify({"error": "Code requis."}), 400

    classroom = Classroom.query.filter_by(join_code=code).first()
    if not classroom:
        return jsonify({"error": "Code invalide. Vérifiez le code et réessayez."}), 404

    existing = ClassroomMembership.query.filter_by(
        student_id=current_user.id, classroom_id=classroom.id
    ).first()
    if existing:
        return jsonify({"error": "Vous êtes déjà inscrit dans cette classe."}), 409

    membership = ClassroomMembership(student_id=current_user.id, classroom_id=classroom.id)
    db.session.add(membership)
    db.session.commit()

    return jsonify({
        "id": classroom.id,
        "name": classroom.name,
        "description": classroom.description,
        "join_code": classroom.join_code,
        "teacher": classroom.teacher.username
    })


@app.route('/classroom/<int:classroom_id>', methods=['GET'])
@login_required
def classroom_detail(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)

    if current_user.role == 'teacher':
        if classroom.teacher_id != current_user.id:
            flash("Accès refusé.")
            return redirect(url_for('dashboard'))
        students = [m.student for m in classroom.memberships]
        return render_template('classroom_teacher.html', classroom=classroom, students=students)
    else:
        membership = ClassroomMembership.query.filter_by(
            student_id=current_user.id, classroom_id=classroom_id
        ).first()
        if not membership:
            flash("Vous n'êtes pas inscrit dans cette classe.")
            return redirect(url_for('dashboard'))
        active_conversation = get_or_create_active_conversation(current_user)
        return render_template(
            'classroom_student.html',
            classroom=classroom,
            active_conversation_id=active_conversation.id
        )


@app.route('/classroom/<int:classroom_id>/assign', methods=['POST'])
@login_required
def assign_prompt(classroom_id):
    if current_user.role != 'teacher':
        return jsonify({"error": "Unauthorized"}), 403

    classroom = Classroom.query.get_or_404(classroom_id)
    if classroom.teacher_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()

    if not prompt:
        return jsonify({"error": "Le sujet ne peut pas être vide."}), 400

    classroom.active_prompt = prompt
    db.session.commit()
    return jsonify({"status": "ok", "prompt": prompt})


@app.route('/classroom/<int:classroom_id>/prompt', methods=['GET'])
@login_required
def get_classroom_prompt(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    return jsonify({"prompt": classroom.active_prompt or ""})


# ── Chat Routes ──

@app.route('/chat/history', methods=['GET'])
@login_required
def chat_history():
    requested_conversation_id = request.args.get('conversation_id', type=int)
    conversation = resolve_conversation_for_user(current_user, requested_conversation_id)

    saved_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id, conversation_id=conversation.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    return jsonify({
        "conversation_id": conversation.id,
        "messages": [
            {"role": m.role, "message": m.message, "created_at": m.created_at.isoformat()}
            for m in saved_messages
        ]
    })


@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get('message') or '').strip()
    requested_conversation_id = data.get('conversation_id')
    conversation = resolve_conversation_for_user(current_user, requested_conversation_id)

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    user_chat = ChatHistory(
        user_id=current_user.id,
        conversation_id=conversation.id,
        role="user",
        message=user_message
    )
    db.session.add(user_chat)
    db.session.commit()

    prior_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id, conversation_id=conversation.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for chat_message in prior_messages:
        messages.append({"role": chat_message.role, "content": chat_message.message})

    try:
        response = requests.post(
            GBT_URL,
            json={"model": "Phi-3 Mini Instruct", "messages": messages, "max_tokens": 300, "temperature": 0.7},
            timeout=120
        )

        if response.status_code != 200:
            return jsonify({"error": response.text}), 500

        reply = response.json()["choices"][0]["message"]["content"]

        assistant_chat = ChatHistory(
            user_id=current_user.id,
            conversation_id=conversation.id,
            role="assistant",
            message=reply
        )
        db.session.add(assistant_chat)
        db.session.commit()

        return jsonify({"response": reply, "conversation_id": conversation.id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/reset', methods=['POST'])
@login_required
def reset():
    data = request.get_json(silent=True) or {}
    requested_conversation_id = data.get('conversation_id')
    conversation = resolve_conversation_for_user(current_user, requested_conversation_id)

    ChatHistory.query.filter_by(user_id=current_user.id, conversation_id=conversation.id).delete()
    db.session.commit()
    return jsonify({"status": "Conversation cleared", "conversation_id": conversation.id})


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))


# ── Init DB ──
with app.app_context():
    db.create_all()
    ensure_chat_history_schema()
    ensure_user_role_column()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    start_ngrok_tunnel(port)
    app.run(host='0.0.0.0', port=port, debug=True)
