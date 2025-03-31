import sys
import os
import unittest

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import only the specific classes we need
from penguin.llm.provider_adapters import OllamaAdapter
from penguin.llm.model_config import ModelConfig

# Create a simple test
def test_ollama_adapter():
    # Create a model config
    model_config = ModelConfig(
        model="llama3",
        provider="ollama",
        temperature=0.7,
        max_tokens=2000
    )
    
    # Create the adapter
    adapter = OllamaAdapter(model_config)
    
    # Test with system messages
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"}
    ]
    
    formatted = adapter.format_messages(messages)
    
    # Print the results
    print("Original messages:", messages)
    print("\nFormatted messages:", formatted)
    print("\nNumber of messages:", len(formatted))
    print("First message role:", formatted[0]["role"])
    print("First message contains system instructions:", "[SYSTEM INSTRUCTIONS]" in formatted[0]["content"])
    print("First message contains original system content:", "You are a helpful assistant" in formatted[0]["content"])
    print("Second message role:", formatted[1]["role"])
    print("Third message role:", formatted[2]["role"])
    print("Third message content:", formatted[2]["content"])
    
    # Test without system messages
    messages_no_system = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "How are you?"}
    ]
    
    formatted_no_system = adapter.format_messages(messages_no_system)
    
    print("\n\nMessages without system role:")
    print("Original:", messages_no_system)
    print("Formatted:", formatted_no_system)
    print("Are they the same?", formatted_no_system == messages_no_system)
    
    # Test response processing
    response = {"message": {"content": "Hello, I'm an AI assistant."}}
    content, _ = adapter.process_response(response)
    print("\n\nResponse processing:")
    print("Original response:", response)
    print("Processed content:", content)
    
    # Test system message support
    print("\nSupports system messages natively?", adapter.supports_system_messages())
    
    print("\nAll tests passed!")

if __name__ == "__main__":
    test_ollama_adapter()