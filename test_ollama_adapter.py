import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Import the specific modules we need
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
from penguin.llm.provider_adapters import OllamaAdapter
from penguin.llm.model_config import ModelConfig

class TestOllamaAdapter(unittest.TestCase):
    def setUp(self):
        self.model_config = ModelConfig(
            model="llama3",
            provider="ollama",
            temperature=0.7,
            max_tokens=2000
        )
        self.adapter = OllamaAdapter(self.model_config)

    def test_format_messages_with_system(self):
        """Test that system messages are properly converted to user messages"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"}
        ]
        
        formatted = self.adapter.format_messages(messages)
        
        # Check that we have 3 messages (system->user, simulated assistant, original user)
        self.assertEqual(len(formatted), 3)
        
        # Check that the first message is a user message containing the system content
        self.assertEqual(formatted[0]["role"], "user")
        self.assertIn("[SYSTEM INSTRUCTIONS]", formatted[0]["content"])
        self.assertIn("You are a helpful assistant", formatted[0]["content"])
        
        # Check that the second message is the simulated assistant acknowledgment
        self.assertEqual(formatted[1]["role"], "assistant")
        
        # Check that the original user message is preserved
        self.assertEqual(formatted[2]["role"], "user")
        self.assertEqual(formatted[2]["content"], "Hello, how are you?")

    def test_format_messages_without_system(self):
        """Test that messages without system role are passed through unchanged"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"}
        ]
        
        formatted = self.adapter.format_messages(messages)
        
        # Check that messages are unchanged
        self.assertEqual(formatted, messages)

    def test_process_response_dict(self):
        """Test processing a dictionary response"""
        response = {"message": {"content": "Hello, I'm an AI assistant."}}
        content, _ = self.adapter.process_response(response)
        self.assertEqual(content, "Hello, I'm an AI assistant.")
        
        # Test alternative format
        response = {"response": "Hello, I'm an AI assistant."}
        content, _ = self.adapter.process_response(response)
        self.assertEqual(content, "Hello, I'm an AI assistant.")

    def test_process_response_string(self):
        """Test processing a string response"""
        response = "Hello, I'm an AI assistant."
        content, _ = self.adapter.process_response(response)
        self.assertEqual(content, "Hello, I'm an AI assistant.")

    def test_supports_system_messages(self):
        """Test that the adapter reports not supporting system messages natively"""
        self.assertFalse(self.adapter.supports_system_messages())


if __name__ == "__main__":
    unittest.main()