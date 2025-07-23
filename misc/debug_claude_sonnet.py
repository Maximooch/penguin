#!/usr/bin/env python3
"""
Claude Sonnet 4 + OpenRouter Diagnostic Script

This script helps debug the specific issue you're experiencing with:
- Claude Sonnet 4 through OpenRouter
- Streaming responses
- Tool result processing
- Conversation flow

Usage:
    python debug_claude_sonnet.py --run-full-test
    python debug_claude_sonnet.py --validate-config
    python debug_claude_sonnet.py --test-streaming
    python debug_claude_sonnet.py --test-tools
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add penguin modules to path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.debug_utils import get_debugger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class ClaudeSonnetDiagnostic:
    """Comprehensive diagnostic suite for Claude Sonnet 4 + OpenRouter."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.debugger = get_debugger()
        self.model_config = None
        self.gateway = None
        
    async def setup(self) -> bool:
        """Setup the diagnostic environment."""
        print("🔧 Setting up Claude Sonnet 4 diagnostic environment...")
        
        # Check API key
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            print("❌ OPENROUTER_API_KEY environment variable not found")
            print("   Set it with: export OPENROUTER_API_KEY=your_key_here")
            return False
            
        # Create model config
        self.model_config = ModelConfig(
            model="anthropic/claude-sonnet-4",
            provider="openrouter", 
            client_preference="openrouter",
            api_key=api_key,
            streaming_enabled=True,
            temperature=0.5,
            max_tokens=4000,
            reasoning_enabled=True  # Enable reasoning for Claude
        )
        
        # Create gateway
        try:
            self.gateway = OpenRouterGateway(self.model_config)
            print("✅ Gateway initialized successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to initialize gateway: {e}")
            return False
            
    async def validate_configuration(self) -> Dict[str, Any]:
        """Validate the current configuration."""
        print("\n🔍 Validating OpenRouter + Claude Sonnet 4 configuration...")
        
        config = {
            'model': self.model_config.model,
            'api_key': self.model_config.api_key
        }
        
        results = await self.debugger.validate_openrouter_config(config)
        
        print(f"   API Key Valid: {'✅' if results['api_key_valid'] else '❌'}")
        print(f"   Model Available: {'✅' if results['model_available'] else '❌'}")
        print(f"   Streaming Supported: {'✅' if results['streaming_supported'] else '❌'}")
        print(f"   Reasoning Supported: {'✅' if results['reasoning_supported'] else '❌'}")
        
        if results['errors']:
            print("\n❌ Configuration Errors:")
            for error in results['errors']:
                print(f"   • {error}")
                
        if results['warnings']:
            print("\n⚠️  Configuration Warnings:")
            for warning in results['warnings']:
                print(f"   • {warning}")
                
        return results
        
    async def test_basic_response(self) -> bool:
        """Test basic non-streaming response."""
        print("\n💬 Testing basic non-streaming response...")
        
        messages = [
            {"role": "user", "content": "Say 'Hello from Claude Sonnet 4!' and nothing else."}
        ]
        
        try:
            response = await self.gateway.get_response(
                messages=messages,
                stream=False
            )
            
            if response and response.strip():
                print(f"✅ Basic response successful: {response[:100]}...")
                return True
            else:
                print(f"❌ Basic response failed: empty response")
                return False
                
        except Exception as e:
            print(f"❌ Basic response failed: {e}")
            return False
            
    async def test_streaming_response(self) -> bool:
        """Test streaming response with detailed logging."""
        print("\n🌊 Testing streaming response...")
        
        messages = [
            {"role": "user", "content": "Count from 1 to 5, with a brief explanation of each number."}
        ]
        
        # Track streaming data
        stream_data = {
            'chunks_received': 0,
            'reasoning_chunks': 0,
            'content_chunks': 0,
            'total_content': '',
            'errors': []
        }
        
        async def stream_callback(chunk: str, message_type: str = "assistant"):
            stream_data['chunks_received'] += 1
            
            if message_type == "reasoning":
                stream_data['reasoning_chunks'] += 1
                print(f"🧠 Reasoning chunk #{stream_data['reasoning_chunks']}: {chunk[:50]}...")
            else:
                stream_data['content_chunks'] += 1
                stream_data['total_content'] += chunk
                print(f"💭 Content chunk #{stream_data['content_chunks']}: {chunk}", end='', flush=True)
        
        try:
            start_time = time.time()
            response = await self.gateway.get_response(
                messages=messages,
                stream=True,
                stream_callback=stream_callback
            )
            elapsed = time.time() - start_time
            
            print(f"\n✅ Streaming completed in {elapsed:.2f}s")
            print(f"   Total chunks: {stream_data['chunks_received']}")
            print(f"   Reasoning chunks: {stream_data['reasoning_chunks']}")
            print(f"   Content chunks: {stream_data['content_chunks']}")
            print(f"   Final response length: {len(response)}")
            
            if response and response.strip():
                return True
            else:
                print(f"⚠️  Streaming completed but final response is empty")
                return False
                
        except Exception as e:
            print(f"❌ Streaming failed: {e}")
            stream_data['errors'].append(str(e))
            return False
            
    async def test_tool_simulation(self) -> bool:
        """Simulate the tool execution scenario from your debug log."""
        print("\n🔧 Testing tool execution scenario...")
        
        # Simulate the conversation from your debug log
        messages = [
            {"role": "user", "content": "To test, list the folders in your workspace dir"},
            {"role": "assistant", "content": "*Let me take a peek at what we're working with here...*\n\nI'll check the current workspace structure for you. Let me use the enhanced file listing to get a clean view of the directories:"},
            {"role": "system", "content": "Tool Result (list_files_filtered):\nFiles in: /Users/maximusputnam/penguin_workspace\n\nDIRECTORIES:\n  adder_project/\n  backend/\n  calculator/\n  checkpoints/"},
            {"role": "system", "content": "Tool Result (execute):\nCurrent working directory: /Users/maximusputnam/penguin_workspace\nAbsolute path: /Users/maximusputnam/penguin_workspace\n\nDirectories found: 34\n  📁 adder_project\n  📁 backend\n  📁 calculator"},
            {"role": "user", "content": "To test, do you see the results?"}
        ]
        
        # Track what happens after tool results
        try:
            start_time = time.time()
            
            async def tool_callback(chunk: str, message_type: str = "assistant"):
                if message_type == "reasoning":
                    print(f"🧠 {chunk}", end='', flush=True)
                else:
                    print(f"💭 {chunk}", end='', flush=True)
            
            response = await self.gateway.get_response(
                messages=messages,
                stream=True,
                stream_callback=tool_callback
            )
            
            elapsed = time.time() - start_time
            print(f"\n✅ Tool scenario completed in {elapsed:.2f}s")
            print(f"📝 Response: {response}")
            
            if response and response.strip():
                print("✅ Assistant properly responded to tool results")
                return True
            else:
                print("❌ Assistant did not respond to tool results (this matches your issue!)")
                return False
                
        except Exception as e:
            print(f"❌ Tool scenario failed: {e}")
            return False
            
    async def test_conversation_flow(self) -> bool:
        """Test the complete conversation flow that's failing."""
        print("\n🎯 Testing complete conversation flow...")
        
        # Start with a greeting
        conversation = []
        
        # Step 1: Initial greeting
        conversation.append({"role": "user", "content": "Howdy!"})
        
        try:
            response1 = await self.gateway.get_response(conversation, stream=False)
            conversation.append({"role": "assistant", "content": response1})
            print(f"✅ Step 1 - Greeting: {response1[:100]}...")
            
            # Step 2: Request that triggers tools
            conversation.append({"role": "user", "content": "To test, list the folders in your workspace dir"})
            
            response2 = await self.gateway.get_response(conversation, stream=True)
            conversation.append({"role": "assistant", "content": response2})
            print(f"✅ Step 2 - Tool request: {response2[:100]}...")
            
            # Step 3: Simulate tool results (this is where the issue occurs)
            conversation.append({"role": "system", "content": "Tool results: Found 34 directories including adder_project/, backend/, calculator/"})
            conversation.append({"role": "user", "content": "To test, do you see the results?"})
            
            # This is where your issue occurs - the assistant doesn't respond
            response3 = await self.gateway.get_response(conversation, stream=True)
            print(f"📝 Step 3 - After tool results: '{response3}'")
            
            if response3 and response3.strip():
                print("✅ Conversation flow working correctly")
                return True
            else:
                print("❌ Conversation breaks after tool results (this is your issue!)")
                print("🔍 Analysis: The assistant receives tool results but doesn't generate a response")
                return False
                
        except Exception as e:
            print(f"❌ Conversation flow failed: {e}")
            return False
            
    async def run_full_diagnostic(self):
        """Run the complete diagnostic suite."""
        print("🚀 Starting Claude Sonnet 4 + OpenRouter Full Diagnostic")
        print("=" * 60)
        
        if not await self.setup():
            return
            
        results = {}
        
        # Test 1: Configuration validation
        results['config'] = await self.validate_configuration()
        
        # Test 2: Basic response
        results['basic'] = await self.test_basic_response()
        
        # Test 3: Streaming
        results['streaming'] = await self.test_streaming_response()
        
        # Test 4: Tool simulation
        results['tools'] = await self.test_tool_simulation()
        
        # Test 5: Conversation flow
        results['conversation'] = await self.test_conversation_flow()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 DIAGNOSTIC SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for test in ['basic', 'streaming', 'tools', 'conversation'] if results.get(test))
        total = 4
        
        print(f"✅ Tests passed: {passed}/{total}")
        
        if not results.get('conversation'):
            print("\n🎯 ISSUE IDENTIFIED:")
            print("   The assistant fails to respond after receiving tool results.")
            print("   This suggests a problem with:")
            print("   • Tool result processing in the conversation flow")
            print("   • Message formatting after system messages")
            print("   • Context window or token handling")
            print("   • OpenRouter's handling of complex conversations")
            
            print("\n💡 RECOMMENDED FIXES:")
            print("   1. Check conversation message formatting")
            print("   2. Verify tool result integration")
            print("   3. Test with different models")
            print("   4. Check for context length issues")
            print("   5. Enable verbose debugging in core.py")
            
        return results

async def main():
    """Main CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Claude Sonnet 4 + OpenRouter Diagnostic Tool")
    parser.add_argument("--run-full-test", action="store_true", help="Run complete diagnostic suite")
    parser.add_argument("--validate-config", action="store_true", help="Validate configuration only")
    parser.add_argument("--test-streaming", action="store_true", help="Test streaming only")
    parser.add_argument("--test-tools", action="store_true", help="Test tool execution scenario")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        
    diagnostic = ClaudeSonnetDiagnostic()
    
    if args.run_full_test:
        await diagnostic.run_full_diagnostic()
    elif args.validate_config:
        await diagnostic.setup()
        await diagnostic.validate_configuration()
    elif args.test_streaming:
        await diagnostic.setup()
        await diagnostic.test_streaming_response()
    elif args.test_tools:
        await diagnostic.setup()
        await diagnostic.test_tool_simulation()
    else:
        print("Run with --help to see available options")
        print("Quick start: python debug_claude_sonnet.py --run-full-test")

if __name__ == "__main__":
    asyncio.run(main()) 