#!/usr/bin/env python3
"""
Test script to verify the aggressive conversation reformatting fix.

This tests that tool call conversations are properly converted to plain text
to avoid OpenRouter validation errors.

Run with: python test_conversation_fix.py
"""

import sys
from pathlib import Path

# Add the penguin directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.model_config import ModelConfig

def test_conversation_reformatting():
    """Test the aggressive conversation reformatting."""
    print("🔧 Testing Aggressive Conversation Reformatting")
    
    # Create gateway for testing
    config = ModelConfig(
        model="openai/gpt-5",
        provider="openrouter",
        client_preference="openrouter"
    )
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    # Mock logger
    import logging
    gateway.logger = logging.getLogger('test')
    
    # Simulate the problematic conversation from the logs
    problematic_conversation = [
        {
            "role": "user",
            "content": "Create a file called TUI_text34.txt"
        },
        {
            "role": "assistant",
            "content": "I'll check if the file exists first.\n\n```python\n# <execute>\nfrom pathlib import Path\nfile_path = Path('TUI_text34.txt')\nprint(f'Exists: {file_path.exists()}')\n# </execute>\n```",
            "tool_calls": [
                {
                    "id": "call_dd739a1e",
                    "type": "function",
                    "function": {
                        "name": "execute",
                        "arguments": "..."
                    }
                }
            ]
        },
        {
            "role": "tool",
            "content": "Workspace root: /Users/maximusputnam/penguin_workspace\nChecking existence of: /Users/maximusputnam/penguin_workspace/TUI_text34.txt\nExists: False",
            "tool_call_id": "call_dd739a1e"
        },
        {
            "role": "user",
            "content": "Proceed"
        }
    ]
    
    print("Original conversation:")
    for i, msg in enumerate(problematic_conversation):
        role = msg['role']
        has_tool_calls = 'tool_calls' in msg
        has_tool_call_id = 'tool_call_id' in msg
        content_preview = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
        print(f"  {i+1}. {role}: {content_preview}")
        if has_tool_calls:
            print(f"       -> Has tool_calls: {len(msg['tool_calls'])} calls")
        if has_tool_call_id:
            print(f"       -> Has tool_call_id: {msg['tool_call_id']}")
    
    # Test the reformatting
    try:
        reformatted = gateway._clean_conversation_format(problematic_conversation)
        
        print(f"\nReformatted conversation:")
        for i, msg in enumerate(reformatted):
            role = msg['role']
            has_tool_calls = 'tool_calls' in msg
            has_tool_call_id = 'tool_call_id' in msg
            content_preview = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
            print(f"  {i+1}. {role}: {content_preview}")
            if has_tool_calls:
                print(f"       -> Still has tool_calls: {len(msg['tool_calls'])} calls")
            if has_tool_call_id:
                print(f"       -> Still has tool_call_id: {msg['tool_call_id']}")
        
        # Verify transformations
        checks = []
        
        # Check that assistant message with tool_calls was cleaned
        assistant_with_tools = [m for m in problematic_conversation if m.get('role') == 'assistant' and 'tool_calls' in m]
        reformatted_assistant = [m for m in reformatted if m.get('role') == 'assistant' and 'tool_calls' in m]
        
        if len(assistant_with_tools) > 0 and len(reformatted_assistant) == 0:
            print("✅ Assistant messages with tool_calls converted to plain text")
            checks.append(True)
        else:
            print(f"❌ Assistant tool_calls not properly removed: {len(assistant_with_tools)} -> {len(reformatted_assistant)}")
            checks.append(False)
        
        # Check that tool messages were converted to assistant
        tool_messages = [m for m in problematic_conversation if m.get('role') == 'tool']
        reformatted_tool_messages = [m for m in reformatted if m.get('role') == 'tool']
        
        if len(tool_messages) > 0 and len(reformatted_tool_messages) == 0:
            print("✅ Tool messages converted to assistant messages")
            checks.append(True)
        else:
            print(f"❌ Tool messages not properly converted: {len(tool_messages)} -> {len(reformatted_tool_messages)}")
            checks.append(False)
        
        # Check that content is preserved
        total_original_content = sum(len(m.get('content', '')) for m in problematic_conversation)
        total_reformatted_content = sum(len(m.get('content', '')) for m in reformatted)
        
        if total_reformatted_content >= total_original_content * 0.9:  # Allow for small changes due to prefixes
            print(f"✅ Content preserved: {total_original_content} -> {total_reformatted_content} chars")
            checks.append(True)
        else:
            print(f"❌ Significant content loss: {total_original_content} -> {total_reformatted_content} chars")
            checks.append(False)
        
        # Check that XML action tags are preserved
        original_has_xml = any(gateway._contains_penguin_action_tags(m.get('content', '')) for m in problematic_conversation)
        reformatted_has_xml = any(gateway._contains_penguin_action_tags(m.get('content', '')) for m in reformatted)
        
        if original_has_xml == reformatted_has_xml:
            print("✅ XML action tags preservation status maintained")
            checks.append(True)
        else:
            print(f"❌ XML action tags changed: {original_has_xml} -> {reformatted_has_xml}")
            checks.append(False)
        
        passed = sum(checks)
        total = len(checks)
        
        print(f"\n📊 Conversation reformatting: {passed}/{total} checks passed")
        return passed == total
        
    except Exception as e:
        print(f"❌ Conversation reformatting failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing Conversation Reformatting Fix\n")
    
    try:
        success = test_conversation_reformatting()
        
        if success:
            print("\n🎉 Conversation reformatting fix working!")
            print("   ✅ Tool calls converted to plain text")
            print("   ✅ Tool results converted to assistant messages")  
            print("   ✅ Content preserved")
            print("   ✅ Should prevent 'No tool call found' errors")
        else:
            print("\n⚠️  Conversation reformatting needs more work")
        
        print(f"\n💡 Next step: Test with actual Penguin conversation")
        
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted")
    except Exception as e:
        print(f"💥 Test error: {e}")
        import traceback
        traceback.print_exc()