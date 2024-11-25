from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from logging.handlers import RotatingFileHandler
# from main import init
from new import init_penguin
from utils.auth import require_auth
from utils.validation import validate_request

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

# Configure CORS with restrictions
CORS(app, resources={
    r"/api/*": {"origins": ["http://localhost:3000"], "methods": ["POST", "GET"]}
})

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per minute"]
)

# Configure logging
handler = RotatingFileHandler('penguin_server.log', maxBytes=10000, backupCount=3)
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# Initialize managers per session
sessions = {}

@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per minute")
@require_auth
@validate_request
def chat():
    try:
        session_id = request.headers.get('X-Session-ID')
        if session_id not in sessions:
            sessions[session_id] = init()
        
        chat_manager = sessions[session_id]
        data = request.json
        user_input = data.get('message')
        
        response, _ = chat_manager.chat_with_penguin(user_input, 1)
        return jsonify({"response": response})
    except Exception as e:
        app.logger.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Additional endpoints for other Penguin features...