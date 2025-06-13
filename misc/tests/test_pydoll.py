import asyncio
import logging
import os
from penguin.tools.pydoll_tools import pydoll_browser_manager, PyDollBrowserScreenshotTool

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def test_screenshot():
    print("Testing PyDoll browser screenshot functionality...")
    
    # Initialize browser with headless=False to see what's happening
    result = await pydoll_browser_manager.initialize(headless=False)
    print(f'Browser initialization: {"Success" if result else "Failed"}')
    
    if not result:
        print("Failed to initialize browser, aborting test.")
        return
        
    # Navigate to a test website
    page = await pydoll_browser_manager.get_page()
    print("Navigating to example.com...")
    await page.go_to('https://www.example.com')
    print("Navigation complete.")
    
    # Test screenshot tool
    screenshot_tool = PyDollBrowserScreenshotTool()
    print("Taking screenshot...")
    screenshot_result = await screenshot_tool.execute()
    
    # Print full result
    print(f"Screenshot result: {screenshot_result}")
    
    # Check if the screenshot was successful
    if "error" in screenshot_result:
        print(f"Screenshot failed: {screenshot_result['error']}")
    elif "filepath" in screenshot_result:
        print(f"Screenshot saved to: {screenshot_result['filepath']}")
        # Verify file exists
        if os.path.exists(screenshot_result['filepath']):
            print(f"Confirmed file exists, size: {os.path.getsize(screenshot_result['filepath'])} bytes")
        else:
            print(f"WARNING: File does not exist on disk!")
    
    # Close the browser
    await pydoll_browser_manager.close()
    print("Browser closed.")

# Run the test
if __name__ == "__main__":
    asyncio.run(test_screenshot()) 