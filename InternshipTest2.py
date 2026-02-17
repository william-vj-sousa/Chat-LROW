
import requests
import sqlite3
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

gbt_URL = "http://localhost:4891/v1/chat/completions"

#Making stuff for sqlite database. Cursor lets you move around the database.
connections = sqlite3.connect('prototype db.db')
cursor = connections.cursor()
########################################################################
### Reminder to myself >> SQL datatypes  INTEGER, REAL, TEXT, BLOB, NULL
########################################################################



prompt = (
    "Pretend you are a French teacher. "
    "You are teaching a class of beginner students. "
    "You are answering questions they have about grammar. "
    "After every response, correct them on their grammar, spelling, "
    "and make suggestions about tone."
)

# The mem
messages = [
    {"role": "system", "content": prompt}
]

@app.route('/')
def home():
    """Serve the HTML file"""
    return send_file('frenchbot2.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Receives a message from the HTML page and sends it to gbt4all"""
    global messages
    
    # Get the message from the HTML request
    data = request.json
    user_input = data.get('message', '')
    
    if not user_input:
        return jsonify({"error": "No message provided"}), 400
    
    # Add the user's message to the conversation history
    messages.append({"role": "user", "content": user_input})
    
    try:
        # Send the entire conversation to gbt4all
        response = requests.post(
            gbt_URL,
            json={
                "model": "Phi-3 Mini Instruct",  # MUST match /v1/models <======= VERY VERY IMPORTANT
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0.7
            },
            timeout=120
        )

        if response.status_code != 200:
            return jsonify({"error": response.text}), 500

        # Extract the response from gbt4all
        data = response.json()
        reply = data["choices"][0]["message"]["content"]

        # Add the response to our conversation history
        messages.append({"role": "assistant", "content": reply})
        
        # Send the response back to the HTML
        return jsonify({"response": reply})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/reset', methods=['POST'])
def reset():
    """Clear conversation history"""
    global messages
    messages = [
        {"role": "system", "content": prompt}
    ]
    return jsonify({"status": "Conversation cleared"})

if __name__ == '__main__':
    print("Starting French Teacher Bot server on http://localhost:5000")
    app.run(debug=True, port=5000)
