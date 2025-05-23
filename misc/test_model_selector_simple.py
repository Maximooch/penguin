#!/usr/bin/env python3
"""
Simple test for the model selector without caching and with /models command.
"""

import asyncio
import sys
from pathlib import Path

# Add the penguin module to the path
sys.path.insert(0, str(Path(__file__).parent / "penguin"))

async def main():
    """Test the simplified model selector"""
    print("Testing Simplified Model Selector\n")
    
    try:
        from penguin.chat.model_selector import interactive_model_selector
        
        # Test with current model
        print("Test 1: With current model specified")
        selected = await interactive_model_selector("anthropic/claude-3-5-sonnet-20240620")
        if selected:
            print(f"\n✓ Selected: {selected}")
        else:
            print("\n- No model selected")
            
        print("\n" + "="*50 + "\n")
        
        # Test without current model
        print("Test 2: Without current model")
        selected = await interactive_model_selector()
        if selected:
            print(f"\n✓ Selected: {selected}")
        else:
            print("\n- No model selected")
            
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you're running this from the penguin project root")
        return 1
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        return 0
    except Exception as e:
        print(f"Test error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 