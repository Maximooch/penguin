#!/usr/bin/env python3
"""
Debug utilities for Penguin LLM integration troubleshooting.

This module provides comprehensive debugging tools for:
- OpenRouter API interactions
- Streaming response analysis
- Tool execution flow
- Configuration validation
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import httpx

class LLMDebugger:
    """Comprehensive debugging for LLM integrations."""
    
    def __init__(self, log_dir: Path = Path("debug_logs")):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup debug logger
        self.logger = logging.getLogger("llm_debugger")
        self.logger.setLevel(logging.DEBUG)
        
        # Create debug log file
        debug_file = self.log_dir / f"llm_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        handler = logging.FileHandler(debug_file)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Also log to console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Initialize session tracking
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.request_count = 0
        self.streaming_sessions = {}
        
    def log_request_start(self, messages: List[Dict], config: Dict, request_type: str = "completion") -> str:
        """Log the start of an LLM request with full context."""
        self.request_count += 1
        request_id = f"{self.session_id}_{self.request_count:04d}"
        
        self.logger.info(f"🚀 REQUEST START [{request_id}] Type: {request_type}")
        self.logger.debug(f"📋 Config: {json.dumps(config, indent=2)}")
        self.logger.debug(f"💬 Messages ({len(messages)} total):")
        
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            content_preview = content[:100] + "..." if len(content) > 100 else content
            self.logger.debug(f"   [{i}] {role}: {content_preview}")
            
        return request_id
        
    def log_streaming_start(self, request_id: str, config: Dict):
        """Log streaming session initialization."""
        self.streaming_sessions[request_id] = {
            'start_time': time.time(),
            'chunk_count': 0,
            'reasoning_chunks': 0,
            'content_chunks': 0,
            'total_reasoning': 0,
            'total_content': 0,
            'last_chunk_time': time.time(),
            'errors': []
        }
        
        self.logger.info(f"🌊 STREAMING START [{request_id}]")
        self.logger.debug(f"📊 Stream config: {json.dumps(config, indent=2)}")
        
    def log_stream_chunk(self, request_id: str, chunk_data: Dict, message_type: str = "content"):
        """Log individual streaming chunks with detailed analysis."""
        if request_id not in self.streaming_sessions:
            self.logger.warning(f"⚠️  Unknown streaming session: {request_id}")
            return
            
        session = self.streaming_sessions[request_id]
        session['chunk_count'] += 1
        session['last_chunk_time'] = time.time()
        
        chunk_content = chunk_data.get('content', chunk_data.get('chunk', ''))
        chunk_length = len(chunk_content)
        
        if message_type == "reasoning":
            session['reasoning_chunks'] += 1
            session['total_reasoning'] += chunk_length
            self.logger.debug(f"🧠 REASONING CHUNK [{request_id}] #{session['reasoning_chunks']}: '{chunk_content[:50]}...' ({chunk_length} chars)")
        else:
            session['content_chunks'] += 1
            session['total_content'] += chunk_length
            self.logger.debug(f"💭 CONTENT CHUNK [{request_id}] #{session['content_chunks']}: '{chunk_content[:50]}...' ({chunk_length} chars)")
            
        # Log timing between chunks
        elapsed = time.time() - session['start_time']
        self.logger.debug(f"⏱️  Chunk timing: {elapsed:.2f}s total, chunk #{session['chunk_count']}")
        
    def log_streaming_complete(self, request_id: str, final_response: str = ""):
        """Log streaming completion with full statistics."""
        if request_id not in self.streaming_sessions:
            self.logger.warning(f"⚠️  Unknown streaming session for completion: {request_id}")
            return
            
        session = self.streaming_sessions[request_id]
        total_time = time.time() - session['start_time']
        
        self.logger.info(f"✅ STREAMING COMPLETE [{request_id}]")
        self.logger.info(f"📊 Stream Statistics:")
        self.logger.info(f"   ⏱️  Total time: {total_time:.2f}s")
        self.logger.info(f"   📦 Total chunks: {session['chunk_count']}")
        self.logger.info(f"   🧠 Reasoning chunks: {session['reasoning_chunks']} ({session['total_reasoning']} chars)")
        self.logger.info(f"   💭 Content chunks: {session['content_chunks']} ({session['total_content']} chars)")
        self.logger.info(f"   🚀 Chunks/sec: {session['chunk_count']/total_time:.1f}")
        
        if final_response:
            self.logger.debug(f"📝 Final response: {final_response[:200]}..." if len(final_response) > 200 else final_response)
            
        # Clean up session
        del self.streaming_sessions[request_id]
        
    def log_openrouter_error(self, error: Exception, request_context: Dict):
        """Log OpenRouter-specific errors with context."""
        self.logger.error(f"❌ OPENROUTER ERROR: {type(error).__name__}: {str(error)}")
        self.logger.error(f"📋 Request context: {json.dumps(request_context, indent=2)}")
        
        # Check for common OpenRouter issues
        error_str = str(error).lower()
        if "quota" in error_str:
            self.logger.error("💰 QUOTA ISSUE: Consider switching models or waiting")
        elif "authentication" in error_str or "401" in error_str:
            self.logger.error("🔐 AUTH ISSUE: Check OPENROUTER_API_KEY")
        elif "rate limit" in error_str or "429" in error_str:
            self.logger.error("🐌 RATE LIMIT: Slow down requests or try different model")
        elif "empty" in error_str or "no content" in error_str:
            self.logger.error("📭 EMPTY RESPONSE: Try different model or adjust parameters")
            
    def log_tool_execution(self, tool_name: str, tool_args: Dict, result: Any, execution_time: float):
        """Log tool execution details."""
        self.logger.info(f"🔧 TOOL EXECUTED: {tool_name}")
        self.logger.debug(f"📥 Args: {json.dumps(tool_args, indent=2)}")
        self.logger.debug(f"📤 Result: {str(result)[:300]}..." if len(str(result)) > 300 else str(result))
        self.logger.info(f"⏱️  Execution time: {execution_time:.2f}s")
        
    async def validate_openrouter_config(self, config: Dict) -> Dict[str, Any]:
        """Validate OpenRouter configuration and connectivity."""
        validation_results = {
            'api_key_valid': False,
            'model_available': False,
            'streaming_supported': False,
            'reasoning_supported': False,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Check API key
            api_key = config.get('api_key') or os.getenv('OPENROUTER_API_KEY')
            if not api_key:
                validation_results['errors'].append("No OpenRouter API key found")
                return validation_results
                
            # Test basic connectivity
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient() as client:
                # Test models endpoint
                models_response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                    timeout=10.0
                )
                
                if models_response.status_code == 200:
                    validation_results['api_key_valid'] = True
                    models_data = models_response.json()
                    
                    # Check if configured model is available
                    model_id = config.get('model', '')
                    available_models = [m['id'] for m in models_data.get('data', [])]
                    
                    if model_id in available_models:
                        validation_results['model_available'] = True
                        
                        # Get model details
                        model_info = next((m for m in models_data['data'] if m['id'] == model_id), None)
                        if model_info:
                            # Check capabilities
                            if 'streaming' in str(model_info).lower():
                                validation_results['streaming_supported'] = True
                            if 'reasoning' in str(model_info).lower() or 'claude' in model_id.lower():
                                validation_results['reasoning_supported'] = True
                    else:
                        validation_results['errors'].append(f"Model {model_id} not found in available models")
                        validation_results['warnings'].append(f"Available models: {available_models[:10]}...")
                        
                else:
                    validation_results['errors'].append(f"API connectivity failed: {models_response.status_code}")
                    
        except Exception as e:
            validation_results['errors'].append(f"Validation error: {str(e)}")
            
        return validation_results
        
    def analyze_conversation_flow(self, conversation_data: List[Dict]) -> Dict[str, Any]:
        """Analyze conversation flow for debugging issues."""
        analysis = {
            'message_count': len(conversation_data),
            'roles': {},
            'tool_calls': 0,
            'tool_results': 0,
            'gaps': [],
            'issues': []
        }
        
        for i, msg in enumerate(conversation_data):
            role = msg.get('role', 'unknown')
            analysis['roles'][role] = analysis['roles'].get(role, 0) + 1
            
            # Check for tool usage
            if 'tool_calls' in msg:
                analysis['tool_calls'] += len(msg.get('tool_calls', []))
            if role == 'tool':
                analysis['tool_results'] += 1
                
            # Look for conversation gaps
            if i > 0:
                prev_msg = conversation_data[i-1]
                if prev_msg.get('role') == 'assistant' and role == 'user':
                    # Check if assistant message was complete
                    content = prev_msg.get('content', '')
                    if not content.strip() or content.startswith('[Error:'):
                        analysis['gaps'].append(f"Empty/error assistant message at index {i-1}")
                        
        # Check for imbalanced tool calls vs results
        if analysis['tool_calls'] > analysis['tool_results']:
            analysis['issues'].append(f"Missing tool results: {analysis['tool_calls']} calls vs {analysis['tool_results']} results")
            
        return analysis

# Global debugger instance
_global_debugger = None

def get_debugger() -> LLMDebugger:
    """Get or create global debugger instance."""
    global _global_debugger
    if _global_debugger is None:
        _global_debugger = LLMDebugger()
    return _global_debugger

# Convenience functions
def debug_request(messages: List[Dict], config: Dict, request_type: str = "completion") -> str:
    return get_debugger().log_request_start(messages, config, request_type)

def debug_stream_start(request_id: str, config: Dict):
    get_debugger().log_streaming_start(request_id, config)

def debug_stream_chunk(request_id: str, chunk_data: Dict, message_type: str = "content"):
    get_debugger().log_stream_chunk(request_id, chunk_data, message_type)

def debug_stream_complete(request_id: str, final_response: str = ""):
    get_debugger().log_streaming_complete(request_id, final_response)

def debug_error(error: Exception, context: Dict):
    get_debugger().log_openrouter_error(error, context)

def debug_tool(tool_name: str, args: Dict, result: Any, exec_time: float):
    get_debugger().log_tool_execution(tool_name, args, result, exec_time)

# CLI interface for debugging
async def main():
    """CLI interface for LLM debugging."""
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description="Penguin LLM Debug Utilities")
    parser.add_argument("--validate-config", action="store_true", help="Validate OpenRouter configuration")
    parser.add_argument("--model", default="anthropic/claude-sonnet-4", help="Model to test")
    parser.add_argument("--test-streaming", action="store_true", help="Test streaming functionality")
    parser.add_argument("--analyze-logs", help="Analyze log file for issues")
    
    args = parser.parse_args()
    
    debugger = get_debugger()
    
    if args.validate_config:
        print("🔍 Validating OpenRouter configuration...")
        config = {
            'model': args.model,
            'api_key': os.getenv('OPENROUTER_API_KEY')
        }
        results = await debugger.validate_openrouter_config(config)
        
        print("\n📊 Validation Results:")
        print(f"   ✅ API Key Valid: {results['api_key_valid']}")
        print(f"   ✅ Model Available: {results['model_available']}")
        print(f"   ✅ Streaming Supported: {results['streaming_supported']}")
        print(f"   ✅ Reasoning Supported: {results['reasoning_supported']}")
        
        if results['errors']:
            print("\n❌ Errors:")
            for error in results['errors']:
                print(f"   • {error}")
                
        if results['warnings']:
            print("\n⚠️  Warnings:")
            for warning in results['warnings']:
                print(f"   • {warning}")
    
    if args.test_streaming:
        print("🌊 Testing streaming functionality...")
        # This would integrate with your existing gateway
        print("   Use this with your OpenRouterGateway for live testing")
        
    if args.analyze_logs:
        print(f"📋 Analyzing log file: {args.analyze_logs}")
        # Log analysis would go here
        print("   Log analysis functionality ready for implementation")

if __name__ == "__main__":
    asyncio.run(main()) 