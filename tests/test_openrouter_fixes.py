#!/usr/bin/env python3
"""
Test script for OpenRouter gateway fixes.

This script tests:
1. Reasoning token configuration formatting
2. Conversation reformatting for OpenAI SDK compatibility
3. Penguin action tag detection
4. Tool call compatibility fixes

Run with: python test_openrouter_fixes.py
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the penguin directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.model_config import ModelConfig

def test_reasoning_config():
    """Test that reasoning configuration is properly formatted."""
    print("=== Testing Reasoning Configuration ===")
    
    # Test with effort-based reasoning
    config_effort = ModelConfig(
        model="openai/gpt-5",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort="medium"
    )
    
    reasoning_config = config_effort.get_reasoning_config()
    print(f"Effort-based config: {reasoning_config}")
    assert reasoning_config == {"effort": "medium"}, f"Expected effort config, got {reasoning_config}"
    
    # Test with max_tokens reasoning
    config_tokens = ModelConfig(
        model="anthropic/claude-4-sonnet",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=2000
    )
    
    reasoning_config = config_tokens.get_reasoning_config()
    print(f"Max tokens config: {reasoning_config}")
    assert reasoning_config == {"max_tokens": 2000}, f"Expected max_tokens config, got {reasoning_config}"
    
    # Test with no reasoning
    config_none = ModelConfig(
        model="openai/gpt-4",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=False
    )
    
    reasoning_config = config_none.get_reasoning_config()
    print(f"No reasoning config: {reasoning_config}")
    assert reasoning_config is None, f"Expected None, got {reasoning_config}"
    
    print("✅ Reasoning configuration tests passed!\n")

def test_penguin_action_tag_detection():
    """Test that Penguin action tags are properly detected."""
    print("=== Testing Penguin Action Tag Detection ===")
    
    # Create a mock gateway to test the helper method
    config = ModelConfig(
        model="openai/gpt-5",
        provider="openrouter",
        client_preference="openrouter"
    )
    
    # Don't actually initialize the full gateway, just create the object
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    
    # Test cases
    test_cases = [
        ("<execute>ls -la</execute>", True),
        ("<search>function definition</search>", True),
        ("<memory_search>project planning</memory_search>", True),
        ("<task_create>New task:Description</task_create>", True),
        ("<browser_navigate>https://example.com</browser_navigate>", True),
        ("<project_list></project_list>", True),
        ("Regular text without any tags", False),
        ("<not_a_real_tag>content</not_a_real_tag>", False),
        ("<div>HTML tag</div>", False),
        ("Text with <execute> partial tag", True),  # Should detect opening tag
        ("Mixed content <search>query</search> with text", True),
    ]
    
    for content, expected in test_cases:
        result = gateway._contains_penguin_action_tags(content)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{content[:50]}...' -> {result} (expected {expected})")
        if result != expected:
            print(f"  FAILED: Expected {expected}, got {result}")
    
    print("\n✅ Penguin action tag detection tests completed!\n")

def test_conversation_reformatting():
    """Test conversation message reformatting for SDK compatibility."""
    print("=== Testing Conversation Reformatting ===")
    
    # Create a mock gateway
    config = ModelConfig(
        model="openai/gpt-5",
        provider="openrouter", 
        client_preference="openrouter"
    )
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    gateway.logger = config  # Mock logger for the method
    
    # Test messages with various problematic formats
    test_messages = [
        # Normal message - should pass through unchanged
        {
            "role": "user",
            "content": "Hello, how are you?"
        },
        
        # Message with Penguin action tags - should be preserved
        {
            "role": "assistant", 
            "content": "I'll search for that. <search>python async</search>"
        },
        
        # Tool message without tool_call_id - should be converted to assistant
        {
            "role": "tool",
            "content": "Command executed successfully"
        },
        
        # Tool message with proper tool_call_id - should be preserved
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "Function result: 42"
        },
        
        # Message with orphaned call_id reference - should be cleaned
        {
            "role": "user",
            "content": "Please execute the function call_abcd123 again"
        },
        
        # Assistant message with tool_calls - should be preserved
        {
            "role": "assistant",
            "content": "I'll help you with that.",
            "tool_calls": [{"id": "call_456", "type": "function", "function": {"name": "test"}}]
        }
    ]
    
    print("Original messages:")
    for i, msg in enumerate(test_messages):
        print(f"  {i+1}. {msg}")
    
    # Test the reformatting
    try:
        reformed = gateway._clean_conversation_format(test_messages)
        print("\nReformatted messages:")
        for i, msg in enumerate(reformed):
            print(f"  {i+1}. {msg}")
        
        # Verify specific transformations
        assert len(reformed) == len(test_messages), "Should preserve all messages"
        
        # Check that tool message without tool_call_id was converted
        tool_msg_reformed = reformed[2]  # Third message
        assert tool_msg_reformed["role"] == "assistant", "Tool message should be converted to assistant"
        assert "[Tool Result]" in tool_msg_reformed["content"], "Tool result should be prefixed"
        
        # Check that proper tool message was preserved
        proper_tool_msg = reformed[3]  # Fourth message  
        assert proper_tool_msg["role"] == "tool", "Proper tool message should be preserved"
        assert "tool_call_id" in proper_tool_msg, "tool_call_id should be preserved"
        
        # Check that call_id was cleaned
        cleaned_msg = reformed[4]  # Fifth message
        assert "call_abcd123" not in cleaned_msg["content"], "call_id should be replaced"
        assert "[tool-call-reference]" in cleaned_msg["content"], "Should contain placeholder"
        
        print("✅ Conversation reformatting tests passed!")
        
    except Exception as e:
        print(f"❌ Conversation reformatting test failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()

def test_integration_mock():
    """Test integration with mocked OpenAI calls."""
    print("=== Testing Integration (Mocked) ===")
    
    try:
        # Create a real gateway instance but don't make actual API calls
        config = ModelConfig(
            model="openai/gpt-5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
            max_tokens=1000,
            temperature=0.7
        )
        
        # Mock the API key to avoid initialization errors
        os.environ["OPENROUTER_API_KEY"] = "mock-key-for-testing"
        
        gateway = OpenRouterGateway(config)
        
        # Test that gateway initializes properly
        assert gateway.model_config.model == "openai/gpt-5"
        assert gateway.model_config.reasoning_enabled == True
        
        # Test reasoning config generation
        reasoning_config = gateway.model_config.get_reasoning_config()
        assert reasoning_config == {"effort": "medium"}
        
        print("✅ Gateway initialization successful")
        print(f"   Model: {gateway.model_config.model}")
        print(f"   Reasoning: {reasoning_config}")
        print(f"   Max tokens: {gateway.model_config.max_tokens}")
        
        # Test message processing pipeline (without actual API call)
        test_messages = [
            {"role": "user", "content": "Test message"},
            {"role": "assistant", "content": "I'll help. <execute>print('hello')</execute>"},
            {"role": "tool", "content": "hello"}  # Missing tool_call_id
        ]
        
        # Test vision processing (should pass through unchanged)
        processed = asyncio.run(gateway._process_messages_for_vision(test_messages))
        assert len(processed) == 3, "Should preserve all messages"
        
        # Test conversation cleaning
        cleaned = gateway._clean_conversation_format(processed)
        assert len(cleaned) == 3, "Should preserve all messages"
        assert cleaned[2]["role"] == "assistant", "Tool message should be converted"
        
        print("✅ Message processing pipeline works correctly")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()

if __name__ == "__main__":
    print("🧪 Running OpenRouter Gateway Fix Tests\n")
    
    try:
        test_reasoning_config()
        test_penguin_action_tag_detection()
        test_conversation_reformatting()
        test_integration_mock()
        
        print("🎉 All tests completed! Check output above for any failures.")
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()