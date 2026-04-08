from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import inspect, text
import os
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



# -- Chat History -- 
class ChatHistory(db.Model): 
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
# -- Conversation Model --
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    messages = db.relationship('ChatHistory', backref='conversation', lazy=True)

# ── User Model ──
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    chats = db.relationship('ChatHistory', backref='user', lazy=True)
    conversations = db.relationship('Conversation', backref='user', lazy=True)


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
            conversation = Conversation(
                user_id=row.user_id,
                title="Recovered conversation"
            )
            db.session.add(conversation)
            db.session.flush()

        db.session.execute(
            text("UPDATE chat_history SET conversation_id = :conversation_id WHERE user_id = :user_id AND conversation_id IS NULL"),
            {"conversation_id": conversation.id, "user_id": row.user_id}
        )

    db.session.commit()


def get_or_create_active_conversation(user):
    conversation = (
        Conversation.query
        .filter_by(user_id=user.id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .first()
    )
    if conversation is None:
        conversation = Conversation(
            user_id=user.id,
            title=f"{user.username} main conversation"
        )
        db.session.add(conversation)
        db.session.commit()
    return conversation


def resolve_conversation_for_user(user, conversation_id=None):
    if conversation_id is not None:
        conversation = Conversation.query.filter_by(
            id=conversation_id,
            user_id=user.id
        ).first()
        if conversation is not None:
            return conversation
    return get_or_create_active_conversation(user)


def start_ngrok_tunnel(port):
    global PUBLIC_URL

    if not NGROK_ENABLED:
        return None

    if ngrok is None:
        print("[ngrok] pyngrok is not installed. Run `pip install -r requirements.txt` in Project.")
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

# ── Landing Page ──
@app.route('/')
def landing():
    return render_template('landing.html')

# ── Login ──
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

# ── Register ──
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm = request.form['confirm_password']

        if password != confirm:
            flash('Les mots de passe ne correspondent pas.')
            return render_template('register.html')

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Un compte avec cet email existe déjà.')
            return render_template('register.html')

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        flash('Compte créé avec succès ! Connectez-vous.')
        return redirect(url_for('login'))

    return render_template('register.html')

# ── Dashboard (protected) ──
@app.route('/dashboard')
@login_required
def dashboard():
    active_conversation = get_or_create_active_conversation(current_user)
    return render_template(
        'dashboard.html',
        username=current_user.username,
        active_conversation_id=active_conversation.id
    )

# ── Logout ──
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

    print(
        f"[chat_history] user_id={current_user.id} "
        f"conversation_id={conversation.id} email={current_user.email} messages={len(saved_messages)}"
    )

    return jsonify({
        "conversation_id": conversation.id,
        "messages": [
            {
                "role": message.role,
                "message": message.message,
                "created_at": message.created_at.isoformat()
            }
            for message in saved_messages
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

    print(
        f"[chat] user_id={current_user.id} conversation_id={conversation.id} "
        f"email={current_user.email} loaded_messages={len(prior_messages)}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for chat_message in prior_messages:
        messages.append({
            "role": chat_message.role,
            "content": chat_message.message
        })

    try:
        response = requests.post(
            GBT_URL,
            json={
                "model": "Phi-3 Mini Instruct",
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=120
        )

        if response.status_code != 200:
            return jsonify({"error": response.text}), 500

        response_data = response.json()
        reply = response_data["choices"][0]["message"]["content"]

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

    ChatHistory.query.filter_by(
        user_id=current_user.id,
        conversation_id=conversation.id
    ).delete()
    db.session.commit()
    return jsonify({"status": "Conversation cleared", "conversation_id": conversation.id})


@app.route('/chat/debug', methods=['GET'])
@login_required
def chat_debug():
    requested_conversation_id = request.args.get('conversation_id', type=int)
    conversation = resolve_conversation_for_user(current_user, requested_conversation_id)

    saved_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id, conversation_id=conversation.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    return jsonify({
        "user_id": current_user.id,
        "conversation_id": conversation.id,
        "email": current_user.email,
        "username": current_user.username,
        "message_count": len(saved_messages),
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "message": message.message,
                "created_at": message.created_at.isoformat()
            }
            for message in saved_messages
        ]
    })

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('landing'))

# ── Create DB ──
with app.app_context():
    db.create_all()
    ensure_chat_history_schema()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    start_ngrok_tunnel(port)
    app.run(host='0.0.0.0', port=port, debug=True)
