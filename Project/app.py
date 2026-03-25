from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy import inspect, text
import os
from datetime import datetime
import requests

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



# -- Chat History -- 
class ChatHistory(db.Model): 
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
# -- Conversation Model --
class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# ── User Model ──
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    chats = db.relationship('ChatHistory', backref='user', lazy=True)


def ensure_chat_history_schema():
    inspector = inspect(db.engine)
    if 'chat_history' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('chat_history')}
    if 'created_at' in columns:
        return

    db.session.execute(text("ALTER TABLE chat_history ADD COLUMN created_at DATETIME"))

    if 'create_at' in columns:
        db.session.execute(text("UPDATE chat_history SET created_at = create_at WHERE create_at IS NOT NULL"))

    db.session.execute(text("UPDATE chat_history SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    db.session.commit()

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
    return render_template('dashboard.html', username=current_user.username)

# ── Logout ──
@app.route('/chat/history', methods=['GET'])
@login_required
def chat_history():
    saved_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    print(f"[chat_history] user_id={current_user.id} email={current_user.email} messages={len(saved_messages)}")

    return jsonify({
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

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    user_chat = ChatHistory(
        user_id=current_user.id,
        role="user",
        message=user_message
    )
    db.session.add(user_chat)
    db.session.commit()

    prior_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    print(f"[chat] user_id={current_user.id} email={current_user.email} loaded_messages={len(prior_messages)}")

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
            role="assistant",
            message=reply
        )
        db.session.add(assistant_chat)
        db.session.commit()

        return jsonify({"response": reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/reset', methods=['POST'])
@login_required
def reset():
    ChatHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"status": "Conversation cleared"})


@app.route('/chat/debug', methods=['GET'])
@login_required
def chat_debug():
    saved_messages = (
        ChatHistory.query
        .filter_by(user_id=current_user.id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
        .all()
    )

    return jsonify({
        "user_id": current_user.id,
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
    app.run(debug=True)
