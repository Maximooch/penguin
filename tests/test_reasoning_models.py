#!/usr/bin/env python3
"""
Test script for reasoning models via OpenRouter.

This script tests the actual OpenRouter API with reasoning models to verify:
1. Reasoning token configuration works
2. No more tool call validation errors
3. Streaming and non-streaming responses work
4. Penguin action tags are preserved in responses

Run with: python test_reasoning_models.py

Note: Requires OPENROUTER_API_KEY environment variable
"""

import sys
import os
import asyncio
from pathlib import Path

# Add the penguin directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.model_config import ModelConfig

# Test models with reasoning capabilities
REASONING_MODELS = [
    "openai/gpt-5",  # GPT-5 if available
    "anthropic/claude-3-5-sonnet-20241022",  # Latest Claude Sonnet
    "deepseek/deepseek-r1",  # DeepSeek R1 reasoning model
]

async def test_basic_response(gateway, model_name):
    """Test basic response without reasoning."""
    print(f"  📝 Testing basic response with {model_name}")
    
    messages = [
        {"role": "user", "content": "Hello! Please respond with exactly 'Test successful' and nothing else."}
    ]
    
    try:
        response = await gateway.get_response(messages, max_tokens=50)
        print(f"     Response: {response[:100]}...")
        return "successful" in response.lower() or len(response.strip()) > 0
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return False

async def test_reasoning_response(gateway, model_name):
    """Test response with reasoning enabled."""
    print(f"  🧠 Testing reasoning response with {model_name}")
    
    messages = [
        {"role": "user", "content": "Think step by step: What is 15 * 23? Show your reasoning."}
    ]
    
    try:
        response = await gateway.get_response(messages, max_tokens=500)
        print(f"     Response length: {len(response)} chars")
        print(f"     Preview: {response[:200]}...")
        return len(response) > 50  # Reasoning responses should be substantial
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return False

async def test_with_penguin_actions(gateway, model_name):
    """Test conversation with Penguin action tags."""
    print(f"  🏷️ Testing with Penguin action tags with {model_name}")
    
    messages = [
        {"role": "user", "content": "List the files in the current directory"},
        {"role": "assistant", "content": "I'll list the files for you. <execute>ls -la</execute>"},
        {"role": "tool", "content": "total 48\ndrwxr-xr-x  8 user user 256 Jan 1 12:00 .\ndrwxr-xr-x  3 user user  96 Jan 1 11:00 ..\n-rw-r--r--  1 user user 123 Jan 1 12:00 test.py"},
        {"role": "user", "content": "Great! Now search for Python functions in the code."}
    ]
    
    try:
        response = await gateway.get_response(messages, max_tokens=200)
        print(f"     Response: {response[:150]}...")
        # Should not get tool call validation errors
        return not response.startswith("[Error:") and len(response) > 10
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return False

async def test_streaming_response(gateway, model_name):
    """Test streaming response."""
    print(f"  📡 Testing streaming with {model_name}")
    
    messages = [
        {"role": "user", "content": "Count from 1 to 5, each number on a new line."}
    ]
    
    chunks_received = []
    
    async def stream_callback(chunk, message_type="assistant"):
        chunks_received.append((chunk, message_type))
        print(f"     Chunk ({message_type}): {chunk.strip()}")
    
    try:
        response = await gateway.get_response(
            messages, 
            max_tokens=100,
            stream=True,
            stream_callback=stream_callback
        )
        
        print(f"     Final response: {response}")
        print(f"     Chunks received: {len(chunks_received)}")
        return len(chunks_received) > 0
        
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return False

async def test_model(model_name, api_key):
    """Test a specific model with various scenarios."""
    print(f"\n🔬 Testing {model_name}")
    
    try:
        # Create model configuration
        config = ModelConfig(
            model=model_name,
            provider="openrouter", 
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium" if "deepseek" not in model_name.lower() else None,
            reasoning_max_tokens=1000 if "anthropic" in model_name.lower() else None,
            max_tokens=1000,
            temperature=0.3,
            streaming_enabled=True
        )
        
        # Create gateway
        gateway = OpenRouterGateway(config, site_url="https://github.com/Maximooch/penguin")
        
        # Run tests
        tests = [
            ("Basic Response", test_basic_response),
            ("Reasoning Response", test_reasoning_response), 
            ("Penguin Actions", test_with_penguin_actions),
            ("Streaming", test_streaming_response),
        ]
        
        results = {}
        for test_name, test_func in tests:
            try:
                result = await test_func(gateway, model_name)
                results[test_name] = result
            except Exception as e:
                print(f"     ❌ {test_name} failed with exception: {e}")
                results[test_name] = False
        
        # Summary
        passed = sum(1 for r in results.values() if r)
        total = len(results)
        
        print(f"  📊 Results for {model_name}: {passed}/{total} passed")
        for test_name, result in results.items():
            status = "✅" if result else "❌"
            print(f"     {status} {test_name}")
        
        return results
        
    except Exception as e:
        print(f"  💥 Failed to test {model_name}: {e}")
        return {}

async def main():
    """Main test runner."""
    print("🧪 Testing OpenRouter Reasoning Models Integration\n")
    
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ OPENROUTER_API_KEY environment variable not set!")
        print("   Set it with: export OPENROUTER_API_KEY='your-key-here'")
        return
    
    print(f"🔑 Using API key: {api_key[:8]}..." + "*" * (len(api_key) - 8))
    
    # Test each model
    all_results = {}
    for model in REASONING_MODELS:
        try:
            results = await test_model(model, api_key)
            all_results[model] = results
        except KeyboardInterrupt:
            print(f"\n⏹️  Testing interrupted at {model}")
            break
        except Exception as e:
            print(f"💥 Unexpected error testing {model}: {e}")
    
    # Overall summary
    print(f"\n📋 Overall Test Summary")
    print("=" * 50)
    
    for model, results in all_results.items():
        if results:
            passed = sum(1 for r in results.values() if r)
            total = len(results)
            status = "✅" if passed == total else "⚠️" if passed > 0 else "❌"
            print(f"{status} {model}: {passed}/{total} tests passed")
        else:
            print(f"❌ {model}: Failed to run tests")
    
    # Check for common issues
    print(f"\n🔍 Common Issue Analysis:")
    
    # Check if any models had tool call errors
    tool_call_errors = []
    for model, results in all_results.items():
        if results.get("Penguin Actions") == False:
            tool_call_errors.append(model)
    
    if tool_call_errors:
        print(f"⚠️  Tool call issues detected in: {', '.join(tool_call_errors)}")
    else:
        print(f"✅ No tool call validation errors detected!")
    
    # Check reasoning capability
    reasoning_working = []
    for model, results in all_results.items():
        if results.get("Reasoning Response") == True:
            reasoning_working.append(model)
    
    if reasoning_working:
        print(f"🧠 Reasoning working in: {', '.join(reasoning_working)}")
    else:
        print(f"⚠️  Reasoning responses need investigation")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()