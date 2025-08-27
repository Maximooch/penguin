#!/usr/bin/env python3
"""Quick test for reasoning toggle functionality."""

def test_toggle():
    from penguin.cli.tui import ChatMessage
    
    # Create a message with reasoning content
    message = ChatMessage("", "assistant")
    
    # Set up content with details block (simulating what streaming would create)
    content_with_reasoning = '''<details>
<summary>🧠 Click to show / hide internal reasoning</summary>

Let me think about this step by step.

First, I need to understand the problem.

</details>

Here is my response based on the reasoning above.'''
    
    message.content = content_with_reasoning
    
    print("Initial content:")
    print(f"Contains <details>: {'<details>' in message.content}")
    print(f"Contains open attribute: {'open' in message.content}")
    print()
    
    # Test first toggle (should add 'open')
    print("First toggle (should open)...")
    message._toggle_reasoning_content()
    print(f"Contains <details>: {'<details>' in message.content}")
    print(f"Contains open attribute: {'open' in message.content}")
    print()
    
    # Test second toggle (should remove 'open') 
    print("Second toggle (should close)...")
    message._toggle_reasoning_content()
    print(f"Contains <details>: {'<details>' in message.content}")
    print(f"Contains open attribute: {'open' in message.content}")
    print()
    
    # Verify content is preserved
    if "Let me think about this step by step" in message.content:
        print("✓ Reasoning content preserved!")
    else:
        print("✗ Reasoning content lost!")
    
    if "Here is my response" in message.content:
        print("✓ Response content preserved!")
    else:
        print("✗ Response content lost!")

if __name__ == "__main__":
    test_toggle()