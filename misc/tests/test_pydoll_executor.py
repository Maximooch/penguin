"""
Test script for the PyDoll browser tools.
This tests the tools directly rather than through the ActionExecutor.
"""

import asyncio
import logging
import os
from penguin.tools.pydoll_tools import (
    pydoll_browser_manager,
    PyDollBrowserNavigationTool,
    PyDollBrowserInteractionTool,
    PyDollBrowserScreenshotTool
)

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_pydoll_browser_tools():
    """Test PyDoll browser tools directly."""
    
    # Create tool instances
    navigation_tool = PyDollBrowserNavigationTool()
    interaction_tool = PyDollBrowserInteractionTool()
    screenshot_tool = PyDollBrowserScreenshotTool()
    
    # Test flow:
    # 1. Navigate to a website
    # 2. Take a screenshot
    # 3. Interact with elements
    # 4. Take another screenshot
    
    try:
        print("1. Testing PyDoll browser navigation...")
        result = await navigation_tool.execute("https://example.com")
        print(f"Navigation result: {result}")
        
        print("\n2. Testing PyDoll browser screenshot...")
        result = await screenshot_tool.execute()
        print(f"Screenshot result: {result}")
        
        if "filepath" in result and os.path.exists(result["filepath"]):
            print(f"Screenshot saved successfully to {result['filepath']}")
            print(f"File size: {os.path.getsize(result['filepath'])} bytes")
        else:
            print(f"Screenshot failed or file not found: {result}")
        
        print("\n3. Testing PyDoll browser interaction (clicking a link)...")
        result = await interaction_tool.execute("click", "a", "css")
        print(f"Interaction result: {result}")
        
        print("\n4. Taking another screenshot after interaction...")
        result = await screenshot_tool.execute()
        print(f"Second screenshot result: {result}")
        
        if "filepath" in result and os.path.exists(result["filepath"]):
            print(f"Second screenshot saved successfully to {result['filepath']}")
            print(f"File size: {os.path.getsize(result['filepath'])} bytes")
        else:
            print(f"Second screenshot failed or file not found: {result}")
        
        # Close browser - cleanup
        await pydoll_browser_manager.close()
        print("\nTest completed successfully")
        
    except Exception as e:
        logger.error(f"Test failed: {str(e)}", exc_info=True)
        print(f"Test failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_pydoll_browser_tools()) 