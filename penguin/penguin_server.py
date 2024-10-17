from flask import Flask, request, jsonify
from flask_cors import CORS
from main import init
import logging

app = Flask(__name__)
CORS(app)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize PenguinCore and ChatManager
chat_manager = init()

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_input = data.get('message')
        response, _ = chat_manager.chat_with_penguin(user_input, 1)  # Using 1 as a placeholder for message_count
        return jsonify({"response": response})
    except Exception as e:
        app.logger.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/task', methods=['POST'])
def handle_task():
    try:
        data = request.json
        action = data.get('action')
        task_name = data.get('taskName')
        task_description = data.get('taskDescription')

        if action == 'create':
            chat_manager.handle_task_command(f"task create {task_name} {task_description}", 1)
            result = {"status": "success", "message": "Task created"}
        elif action == 'run':
            chat_manager.handle_task_command(f"task run {task_name}", 1)
            result = {"status": "success", "message": "Task running"}
        elif action == 'list':
            task_board = chat_manager.task_manager.get_task_board()
            result = {"status": "success", "tasks": task_board}
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400

        # Always include the updated task list in the response
        task_board = chat_manager.task_manager.get_task_board()
        result["tasks"] = task_board
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in task endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
