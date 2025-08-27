#!/usr/bin/env python3
"""
Simple unit test for reasoning functionality.
"""

def test_reasoning_widget():
    """Test the reasoning widget functionality without running TUI."""
    
    # Test 1: Import and create ChatMessage
    print("Testing imports...")
    try:
        from penguin.cli.tui import ChatMessage
        print("✓ Successfully imported ChatMessage")
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    
    # Test 2: Create a ChatMessage instance
    print("Creating ChatMessage instance...")
    try:
        message = ChatMessage("", "assistant")
        print("✓ Successfully created ChatMessage")
    except Exception as e:
        print(f"✗ ChatMessage creation failed: {e}")
        return False
    
    # Test 3: Test stream_in functionality
    print("Testing stream_in with reasoning content...")
    try:
        # Start reasoning details block
        reasoning_header = "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
        message.stream_in(reasoning_header)
        print("✓ Successfully streamed reasoning header")
        
        # Stream reasoning content
        reasoning_content = "Let me think about this step by step.\n\nFirst, I need to understand the problem."
        message.stream_in(reasoning_content)
        print("✓ Successfully streamed reasoning content")
        
        # Close details block
        message.stream_in("\n\n</details>\n\n")
        print("✓ Successfully closed details block")
        
        # Add regular response
        response = "Here is my response based on the reasoning above."
        message.stream_in(response)
        print("✓ Successfully streamed regular response")
        
    except Exception as e:
        print(f"✗ Stream_in test failed: {e}")
        return False
    
    # Test 4: Check final content structure
    print("Verifying content structure...")
    final_content = message.content
    
    if "<details>" in final_content and "</details>" in final_content:
        print("✓ Details block structure is correct")
    else:
        print("✗ Details block structure is missing")
        print(f"Content: {final_content[:200]}...")
        return False
    
    if "🧠" in final_content:
        print("✓ Reasoning emoji is present")
    else:
        print("✗ Reasoning emoji is missing")
        return False
    
    if "reasoning" in final_content.lower():
        print("✓ Reasoning text is present")
    else:
        print("✗ Reasoning text is missing")
        return False
    
    # Test 5: Test the toggle method exists
    print("Testing toggle method...")
    try:
        if hasattr(message, '_toggle_reasoning_content'):
            print("✓ _toggle_reasoning_content method exists")
        else:
            print("✗ _toggle_reasoning_content method missing")
            return False
        
        if hasattr(message, 'action_toggle_expander'):
            print("✓ action_toggle_expander method exists")
        else:
            print("✗ action_toggle_expander method missing")
            return False
            
    except Exception as e:
        print(f"✗ Toggle method test failed: {e}")
        return False
    
    print(f"✓ All tests passed! Final content length: {len(final_content)} characters")
    print(f"Content preview: {final_content[:100]}...")
    return True

if __name__ == "__main__":
    success = test_reasoning_widget()
    if success:
        print("\n🎉 All reasoning widget tests passed!")
    else:
        print("\n❌ Some tests failed!")
        exit(1)