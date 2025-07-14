#!/usr/bin/env python3
"""
Test script for reasoning tokens functionality in Penguin.

This script demonstrates:
1. Auto-detection of reasoning-capable models
2. Configuration of reasoning parameters
3. Streaming reasoning tokens
4. Non-streaming reasoning tokens

SETUP REQUIREMENTS:
1. Set OPENROUTER_API_KEY environment variable
2. Ensure you have OpenAI SDK >= 1.12.0: pip install "openai>=1.12.0"
3. Ensure you have httpx: pip install httpx

If you get "unexpected keyword argument 'reasoning'" errors, run:
    pip install --upgrade "openai>=1.12.0"
"""

import asyncio
import os
import sys
from pathlib import Path

# Add penguin to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


def check_dependencies():
    """Check if required dependencies are available."""
    print("🔍 Checking Dependencies")
    print("=" * 50)
    
    # Check OpenAI SDK version
    try:
        import openai
        print(f"✅ OpenAI SDK version: {openai.__version__}")
        # Parse version to check if it's >= 1.12.0
        version_parts = openai.__version__.split('.')
        major, minor = int(version_parts[0]), int(version_parts[1])
        if major > 1 or (major == 1 and minor >= 12):
            print("✅ OpenAI SDK version is compatible with reasoning tokens")
        else:
            print("⚠️  OpenAI SDK version might be too old for reasoning tokens")
            print("   Consider upgrading: pip install --upgrade 'openai>=1.12.0'")
    except ImportError:
        print("❌ OpenAI SDK not found")
        return False
    except Exception as e:
        print(f"⚠️  Could not check OpenAI SDK version: {e}")
    
    # Check httpx
    try:
        import httpx
        print(f"✅ httpx version: {httpx.__version__}")
    except ImportError:
        print("❌ httpx not found - install with: pip install httpx")
        return False
    
    # Check API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        print(f"✅ OPENROUTER_API_KEY found (ending in ...{api_key[-4:]})")
    else:
        print("⚠️  OPENROUTER_API_KEY not found")
        print("   Set it with: export OPENROUTER_API_KEY=your_key_here")
    
    print()
    return True


async def test_model_detection():
    """Test auto-detection of reasoning capabilities."""
    print("🧪 Testing Model Detection")
    print("=" * 50)
    
    test_models = [
        "deepseek/deepseek-r1",
        "deepseek/deepseek-r1:free", 
        "google/gemini-2.5-flash-preview:thinking",
        "anthropic/claude-3-5-sonnet-20240620",
        "openai/gpt-4o",
        "openai/o1-preview",
        "grok/grok-2",
    ]
    
    for model in test_models:
        config = ModelConfig(
            model=model,
            provider="openrouter",
            client_preference="openrouter"
        )
        
        print(f"Model: {model}")
        print(f"  Supports reasoning: {config.supports_reasoning}")
        print(f"  Reasoning enabled: {config.reasoning_enabled}")
        if config.supports_reasoning:
            print(f"  Uses effort style: {config._uses_effort_style()}")
            print(f"  Uses token style: {config._uses_max_tokens_style()}")
            reasoning_config = config.get_reasoning_config()
            print(f"  Config: {reasoning_config}")
        print()


async def test_reasoning_config():
    """Test different reasoning configurations."""
    print("⚙️ Testing Reasoning Configuration")
    print("=" * 50)
    
    # Test effort-based configuration
    config1 = ModelConfig(
        model="openai/o1-preview",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort="high"
    )
    
    print("Effort-based configuration (OpenAI o1):")
    print(f"  Config: {config1.get_reasoning_config()}")
    
    # Test token-based configuration
    config2 = ModelConfig(
        model="deepseek/deepseek-r1",
        provider="openrouter", 
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=3000
    )
    
    print("\nToken-based configuration (DeepSeek R1):")
    print(f"  Config: {config2.get_reasoning_config()}")
    
    # Test excluded reasoning
    config3 = ModelConfig(
        model="deepseek/deepseek-r1",
        provider="openrouter",
        client_preference="openrouter", 
        reasoning_enabled=True,
        reasoning_max_tokens=2000,
        reasoning_exclude=True
    )
    
    print("\nExcluded reasoning configuration:")
    print(f"  Config: {config3.get_reasoning_config()}")
    print()


async def test_streaming_reasoning():
    """Test streaming reasoning tokens (requires API key)."""
    print("🌊 Testing Streaming Reasoning Tokens")
    print("=" * 50)
    
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️ OPENROUTER_API_KEY not found, skipping live tests")
        print("   Set your API key: export OPENROUTER_API_KEY=your_key_here")
        return
    
    # Configure model
    model_config = ModelConfig(
        model="deepseek/deepseek-r1:free",  # Use free model for testing
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=1000,
        streaming_enabled=True
    )
    
    print(f"Using model: {model_config.model}")
    print(f"Reasoning config: {model_config.get_reasoning_config()}")
    print()
    
    # Initialize gateway
    gateway = OpenRouterGateway(model_config)
    
    # Track reasoning and content separately
    reasoning_chunks = []
    content_chunks = []
    
    async def stream_callback(chunk: str, message_type: str = "assistant"):
        if message_type == "reasoning":
            reasoning_chunks.append(chunk)
            print(f"🤔 {chunk}", end="", flush=True)
        else:
            content_chunks.append(chunk)
            print(f"💭 {chunk}", end="", flush=True)
    
    # Test with a problem that should trigger reasoning
    messages = [
        {
            "role": "user",
            "content": "What's bigger: 9.11 or 9.9? Think through this step by step."
        }
    ]
    
    print("Asking: What's bigger: 9.11 or 9.9?")
    print("Response:")
    print("-" * 30)
    
    try:
        response = await gateway.get_response(
            messages=messages,
            stream=True,
            stream_callback=stream_callback
        )
        
        print("\n" + "-" * 30)
        print("\n📊 Results:")
        print(f"Reasoning chunks: {len(reasoning_chunks)}")
        print(f"Content chunks: {len(content_chunks)}")
        print(f"Total reasoning length: {sum(len(chunk) for chunk in reasoning_chunks)}")
        print(f"Total content length: {sum(len(chunk) for chunk in content_chunks)}")
        print(f"Final response: {response[:100]}...")
        
        if reasoning_chunks:
            print("✅ Reasoning tokens successfully received!")
        else:
            print("⚠️  No reasoning tokens received - this might be expected for some models")
        
    except Exception as e:
        print(f"❌ Error during streaming test: {e}")
        if "reasoning" in str(e):
            print("   This might be an OpenAI SDK version issue.")
            print("   Try: pip install --upgrade 'openai>=1.12.0'")
    
    print()


async def test_non_streaming_reasoning():
    """Test non-streaming reasoning tokens (requires API key)."""
    print("📄 Testing Non-Streaming Reasoning Tokens")
    print("=" * 50)
    
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠️ OPENROUTER_API_KEY not found, skipping live tests")
        print("   Set your API key: export OPENROUTER_API_KEY=your_key_here")
        return
    
    # Configure model
    model_config = ModelConfig(
        model="deepseek/deepseek-r1:free",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=800,
        streaming_enabled=False
    )
    
    # Initialize gateway
    gateway = OpenRouterGateway(model_config)
    
    # Track reasoning via callback
    reasoning_received = ""
    
    async def callback(chunk: str, message_type: str = "assistant"):
        nonlocal reasoning_received
        if message_type == "reasoning":
            reasoning_received += chunk
    
    messages = [
        {
            "role": "user", 
            "content": "If I have 3 apples and buy 2 more, then give away 1, how many do I have? Show your reasoning."
        }
    ]
    
    print("Asking simple math problem...")
    
    try:
        response = await gateway.get_response(
            messages=messages,
            stream=False,
            stream_callback=callback
        )
        
        print(f"📝 Response: {response}")
        print(f"🤔 Reasoning received: {len(reasoning_received)} chars")
        if reasoning_received:
            print(f"🤔 Reasoning preview: {reasoning_received[:200]}...")
            print("✅ Reasoning tokens successfully received!")
        else:
            print("⚠️  No reasoning tokens received - this might be expected for some models")
        
    except Exception as e:
        print(f"❌ Error during non-streaming test: {e}")
        if "reasoning" in str(e):
            print("   This might be an OpenAI SDK version issue.")
            print("   Try: pip install --upgrade 'openai>=1.12.0'")
    
    print()


async def main():
    """Run all tests."""
    print("🧠 Penguin Reasoning Tokens Test Suite")
    print("=" * 50)
    print()
    
    # Check dependencies first
    if not check_dependencies():
        print("❌ Dependency check failed. Please install missing dependencies.")
        return
    
    # Test model detection (always runs)
    await test_model_detection()
    
    # Test configuration (always runs)
    await test_reasoning_config()
    
    # Test live functionality (requires API key)
    await test_streaming_reasoning()
    await test_non_streaming_reasoning()
    
    print("✅ All tests completed!")
    print("\n💡 Tips:")
    print("   - Make sure you have OpenAI SDK >= 1.12.0")
    print("   - Set OPENROUTER_API_KEY for live testing")
    print("   - Try different reasoning models for different capabilities")
    print("   - Check the REASONING_TOKENS.md documentation for more details")


if __name__ == "__main__":
    # Set up environment
    print("Setting up test environment...")
    
    # Disable tokenizers parallelism warning
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    
    # Run tests
    asyncio.run(main()) 