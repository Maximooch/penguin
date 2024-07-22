# The ConversationMemory class is used to store and manage the conversation history between the user and the AI assistant.
class ConversationMemory:
    # The __init__ method initializes a new instance of the ConversationMemory class.
    # It takes an optional max_history parameter that specifies the maximum number of messages to keep in the conversation history.
    # If max_history is not provided, it defaults to 100.
    def __init__(self, max_history=10000):
        # Initialize an empty list to store the conversation history.
        self.conversation_history = []
        # Store the maximum number of messages to keep in the conversation history.
        self.max_history = max_history

    # The add_message method adds a new message to the conversation history.
    # It takes two parameters: role (either "user" or "assistant") and content (the message content).
    def add_message(self, role, content):
        # Create a dictionary representing the message with the role and content.
        message = {"role": role, "content": content}
        # Append the message to the conversation history list.
        self.conversation_history.append(message)
        # If the length of the conversation history exceeds the max_history limit, remove the oldest message.
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    # The get_history method returns the entire conversation history as a list of dictionaries.
    def get_history(self):
        return self.conversation_history

    # The clear_history method clears the conversation history by setting it to an empty list.
    def clear_history(self):
        self.conversation_history = []

    # The get_last_message method returns the last message in the conversation history, or None if the history is empty.
    def get_last_message(self):
        return self.conversation_history[-1] if self.conversation_history else None

    # The add_system_message method adds a system message to the conversation history.
    # It takes the content of the system message as a parameter.
    def add_system_message(self, content):
        # Create a dictionary representing the system message with the role "system" and the provided content.
        # The content is wrapped in a list with a dictionary containing the message type ("text") and the actual text.
        self.add_message("system", [{"type": "text", "text": content}])

    # The add_user_message method adds a user message to the conversation history.
    # It takes the content of the user message as a parameter.
    def add_user_message(self, content):
        # If the content is a list, add it directly to the conversation history as a user message.
        if isinstance(content, list):
            self.add_message("user", content)
        # If the content is not a list, wrap it in a list before adding it to the conversation history as a user message.
        else:
            self.add_message("user", [content])

    # The add_assistant_message method adds an assistant message to the conversation history.
    # It takes the content of the assistant message as a parameter.
    def add_assistant_message(self, content):
        # If the content is a list, add it directly to the conversation history as an assistant message.
        if isinstance(content, list):
            self.add_message("assistant", content)
        # If the content is not a list, wrap it in a list before adding it to the conversation history as an assistant message.
        else:
            self.add_message("assistant", [content])

    # The add_tool_message method adds a tool message to the conversation history.
    # It takes three parameters: tool_name (the name of the tool), tool_input (the input to the tool), and tool_output (the output of the tool).
    def add_tool_message(self, tool_name, tool_input, tool_output):
        # Create a dictionary representing the tool use with the type "tool_use", the tool name, and the tool input.
        tool_message = {
            "type": "tool_use",
            "name": tool_name,
            "input": tool_input,
        }
        # Add the tool message to the conversation history as an assistant message.
        self.add_assistant_message([tool_message])
        
        # Create a dictionary representing the tool result with the type "tool_result", the tool name, and the tool output.
        tool_result_message = {
            "type": "tool_result",
            "name": tool_name,
            "content": tool_output,
        }
        # Add the tool result message to the conversation history as a user message.
        self.add_user_message([tool_result_message])

    def clear_history(self):
        self.conversation_history = [] 

    def clear(self):
        self.clear_history()

# Example usage:
# memory = ConversationMemory()
# memory.add_system_message("You are a helpful AI assistant.")
# memory.add_user_message("Hello, how are you?")
# memory.add_assistant_message("I'm doing well, thank you for asking! How can I assist you today?")
# memory.add_tool_message("calculator", {"operation": "add", "numbers": [2, 3]}, "5")
# print(memory.get_history())