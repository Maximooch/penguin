#!/usr/bin/env python3
"""Test PyDoll tools integration."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("Importing penguin.tools.pydoll_tools...")
try:
    from penguin.tools.pydoll_tools import (
        pydoll_browser_manager,
        PyDollBrowserNavigationTool,
    )
    print("✓ Import successful\n")
except Exception as e:
    print(f"✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

async def test_tools():
    print("Creating navigation tool...")
    nav = PyDollBrowserNavigationTool()
    print("✓ Tool created\n")
    
    print("Attempting navigation to https://example.com...")
    try:
        result = await nav.execute("https://example.com")
        print(f"Result: {result}")
        return True
    except Exception as e:
        print(f"✗ Navigation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_tools())
    sys.exit(0 if success else 1)
