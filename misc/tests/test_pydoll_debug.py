#!/usr/bin/env python
"""
Test script for PyDoll debug toggle functionality
"""

import asyncio
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add parent directory to sys.path to allow importing from penguin module
sys.path.insert(0, '.')

async def main():
    try:
        # Import the necessary modules
        from penguin.tools.pydoll_tools import pydoll_browser_manager, pydoll_debug_toggle
        
        # Check initial state
        print(f"Initial dev mode: {pydoll_browser_manager.dev_mode}")
        
        # Toggle to enabled
        new_state = await pydoll_debug_toggle(True)
        print(f"After enabling: {pydoll_browser_manager.dev_mode} (returned: {new_state})")
        
        # Toggle to disabled
        new_state = await pydoll_debug_toggle(False)
        print(f"After disabling: {pydoll_browser_manager.dev_mode} (returned: {new_state})")
        
        # Toggle (should enable again)
        new_state = await pydoll_debug_toggle()
        print(f"After toggling: {pydoll_browser_manager.dev_mode} (returned: {new_state})")
        
        print("Test completed successfully!")
        
    except Exception as e:
        print(f"Error running test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 