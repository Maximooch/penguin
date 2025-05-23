#!/usr/bin/env python3
"""
Test script for the model selector prototype.
Run this to test the prompt_toolkit autocomplete interface independently.

Usage:
    python test_model_selector.py
"""

import asyncio
import sys
from pathlib import Path

# Add the penguin module to the path
sys.path.insert(0, str(Path(__file__).parent / "penguin"))

async def main():
    """Test the model selector prototype"""
    try:
        from penguin.chat.model_selector import test_model_selector
        await test_model_selector()
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you're running this from the penguin project root")
        return 1
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        return 0
    except Exception as e:
        print(f"Test failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 