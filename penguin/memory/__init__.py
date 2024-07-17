class ConversationMemory:
    def __init__(self, max_history=100):
        self.conversation_history = []
        self.max_history = max_history

    def add_message(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    def get_history(self):
        return self.conversation_history

    def clear_history(self):
        self.conversation_history = []

    def get_last_message(self):
        return self.conversation_history[-1] if self.conversation_history else None

    def add_system_message(self, content):
        self.add_message("system", content)

    def add_user_message(self, content, image_data=None):
        if image_data:
            message_content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": content
                }
            ]
        else:
            message_content = content
        self.add_message("user", message_content)

    def add_assistant_message(self, content):
        self.add_message("assistant", content)

    def add_tool_message(self, tool_name, tool_input, tool_output):
        tool_message = {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "tool_name": tool_name,
                "tool_input": tool_input,
            }]
        }
        self.add_message("assistant", tool_message)
        
        tool_result_message = {
            "role": "tool",
            "content": [{
                "type": "tool_result",
                "tool_name": tool_name,
                "tool_output": tool_output,
            }]
        }
        self.add_message("tool", tool_result_message)

# Example usage:
# memory = ConversationMemory()
# memory.add_system_message("You are a helpful AI assistant.")
# memory.add_user_message("Hello, how are you?")
# memory.add_assistant_message("I'm doing well, thank you for asking! How can I assist you today?")
# memory.add_tool_message("calculator", {"operation": "add", "numbers": [2, 3]}, "5")
# print(memory.get_history())