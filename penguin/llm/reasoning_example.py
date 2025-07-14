#!/usr/bin/env python3
"""
Simple example demonstrating reasoning tokens with Penguin.

This example shows how to:
1. Configure a reasoning-capable model
2. See the model's reasoning process
3. Get the final answer

Before running:
    export OPENROUTER_API_KEY=your_key_here
    pip install --upgrade "openai>=1.12.0"
"""

import asyncio
import os
from pathlib import Path
import sys

# Add penguin to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


async def reasoning_example():
    """Demonstrate reasoning tokens with a complex problem."""
    
    # Check for API key
    if not os.getenv("OPENROUTER_API_KEY"):
        print("❌ Please set OPENROUTER_API_KEY environment variable")
        return
    
    print("🧠 Penguin Reasoning Tokens Example")
    print("=" * 50)
    
    # Configure a reasoning model
    model_config = ModelConfig(
        model="deepseek/deepseek-r1:free",  # Free reasoning model
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_max_tokens=2000,  # Allow plenty of reasoning space
        streaming_enabled=True
    )
    
    print(f"🤖 Using model: {model_config.model}")
    print(f"⚙️  Reasoning config: {model_config.get_reasoning_config()}")
    print()
    
    # Create gateway
    gateway = OpenRouterGateway(model_config)
    
    # Problem that should trigger reasoning
    problem = """
    A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. 
    How much does the ball cost?
    
    Think through this step by step and show your reasoning.
    """
    
    print("🧩 Problem:")
    print(problem.strip())
    print("\n🤔 Model's Reasoning Process:")
    print("-" * 40)
    
    reasoning_text = ""
    response_text = ""
    
    async def stream_handler(chunk: str, message_type: str):
        nonlocal reasoning_text, response_text
        
        if message_type == "reasoning":
            reasoning_text += chunk
            # Show reasoning in a different color/style
            print(f"\033[90m{chunk}\033[0m", end="", flush=True)  # Gray text
        else:
            response_text += chunk
            # Show final answer in normal text
            print(f"\033[1m{chunk}\033[0m", end="", flush=True)  # Bold text
    
    try:
        # Get response with reasoning
        final_response = await gateway.get_response(
            messages=[{"role": "user", "content": problem}],
            stream=True,
            stream_callback=stream_handler
        )
        
        print("\n" + "-" * 40)
        print("\n📊 Summary:")
        print(f"🧠 Reasoning length: {len(reasoning_text)} characters")
        print(f"💬 Response length: {len(response_text)} characters")
        
        if reasoning_text:
            print("\n✅ Success! The model showed its reasoning process.")
            print("🔍 You can see how it worked through the problem step by step.")
        else:
            print("\n⚠️  No reasoning tokens received.")
            print("💡 This might be normal for some models or API configurations.")
        
        print(f"\n🎯 Final Answer: {final_response[:100]}...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if "reasoning" in str(e):
            print("💡 Try upgrading OpenAI SDK: pip install --upgrade 'openai>=1.12.0'")


async def simple_comparison():
    """Compare reasoning vs non-reasoning responses."""
    
    if not os.getenv("OPENROUTER_API_KEY"):
        return
        
    print("\n\n🔬 Comparison: With vs Without Reasoning")
    print("=" * 50)
    
    # Same problem, two different configurations
    problem = "What's 9.11 + 9.9? Show your work."
    
    # Without reasoning
    model_no_reasoning = ModelConfig(
        model="deepseek/deepseek-r1:free",
        provider="openrouter", 
        client_preference="openrouter",
        reasoning_enabled=False,  # Disabled
        streaming_enabled=False
    )
    
    # With reasoning  
    model_with_reasoning = ModelConfig(
        model="deepseek/deepseek-r1:free",
        provider="openrouter",
        client_preference="openrouter", 
        reasoning_enabled=True,
        reasoning_max_tokens=1000,
        streaming_enabled=False
    )
    
    print("🧮 Problem:", problem)
    print()
    
    try:
        # Test without reasoning
        print("🚫 Without Reasoning:")
        gateway1 = OpenRouterGateway(model_no_reasoning)
        response1 = await gateway1.get_response([{"role": "user", "content": problem}])
        print(f"   {response1[:150]}...")
        
        print("\n✅ With Reasoning:")
        gateway2 = OpenRouterGateway(model_with_reasoning)
        
        reasoning_received = ""
        async def capture_reasoning(chunk: str, message_type: str):
            nonlocal reasoning_received
            if message_type == "reasoning":
                reasoning_received += chunk
        
        response2 = await gateway2.get_response(
            [{"role": "user", "content": problem}],
            stream_callback=capture_reasoning
        )
        
        if reasoning_received:
            print(f"   🧠 Reasoning: {reasoning_received[:100]}...")
        print(f"   💬 Answer: {response2[:150]}...")
        
    except Exception as e:
        print(f"❌ Comparison failed: {e}")


async def main():
    """Run the reasoning examples."""
    # Disable warnings
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    
    await reasoning_example()
    await simple_comparison()
    
    print("\n\n🎉 Reasoning tokens example completed!")
    print("📖 Check REASONING_TOKENS.md for more detailed documentation.")


if __name__ == "__main__":
    asyncio.run(main()) 