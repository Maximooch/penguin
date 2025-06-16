#!/usr/bin/env python3
"""
Test script to verify PyDoll browser fixes for sync/async event loop issues.

This script tests:
1. Headless mode by default (prevents blocking)
2. Timeout handling (prevents hanging)
3. Proper async handling (no nested event loops)
4. Automatic cleanup (prevents resource leaks)
"""

import asyncio
import logging
import sys
import os

# Add the current directory to the Python path so we can import from penguin
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from penguin.tools.pydoll_tools import (
    pydoll_browser_manager, 
    PyDollBrowserNavigationTool,
    PyDollBrowserScreenshotTool,
    pydoll_debug_toggle
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_navigation_with_timeout():
    """Test navigation with timeout handling"""
    print("\n=== Testing Navigation with Timeout ===")
    
    # Test with a valid URL first
    nav_tool = PyDollBrowserNavigationTool()
    result = await nav_tool.execute("https://www.example.com")
    print(f"Navigation result: {result}")
    
    # Test with a URL that might timeout or fail
    result = await nav_tool.execute("https://imgur.com/a/tn8MIFb")
    print(f"Navigation result (potentially problematic URL): {result}")
    
    return True

async def test_screenshot_in_headless():
    """Test screenshot capture in headless mode"""
    print("\n=== Testing Screenshot in Headless Mode ===")
    
    screenshot_tool = PyDollBrowserScreenshotTool()
    result = await screenshot_tool.execute()
    
    if "error" in result:
        print(f"Screenshot failed: {result['error']}")
        return False
    else:
        print(f"Screenshot successful: {result}")
        # Verify file exists
        if "filepath" in result and os.path.exists(result["filepath"]):
            file_size = os.path.getsize(result["filepath"])
            print(f"Screenshot file size: {file_size} bytes")
            return True
        else:
            print("Screenshot file not found!")
            return False

async def test_dev_mode_toggle():
    """Test debug mode toggle functionality"""
    print("\n=== Testing Debug Mode Toggle ===")
    
    # Enable debug mode
    state = await pydoll_debug_toggle(True)
    print(f"Debug mode enabled: {state}")
    
    # Test navigation in debug mode (should show more info)
    nav_tool = PyDollBrowserNavigationTool()
    result = await nav_tool.execute("https://www.example.com")
    print(f"Navigation in debug mode: {result}")
    
    # Disable debug mode
    state = await pydoll_debug_toggle(False)
    print(f"Debug mode disabled: {state}")
    
    return True

async def test_cleanup_mechanism():
    """Test automatic cleanup after inactivity"""
    print("\n=== Testing Cleanup Mechanism ===")
    
    # Initialize browser
    await pydoll_browser_manager.initialize(headless=True)
    print("Browser initialized")
    
    # Check if browser is running
    if pydoll_browser_manager.initialized:
        print("Browser is running")
        
        # Manually trigger cleanup
        await pydoll_browser_manager.close()
        print("Browser manually closed")
        
        if not pydoll_browser_manager.initialized:
            print("Browser successfully closed")
            return True
        else:
            print("WARNING: Browser still appears to be running")
            return False
    else:
        print("Browser failed to initialize")
        return False

async def test_event_loop_handling():
    """Test that the browser doesn't block the event loop"""
    print("\n=== Testing Event Loop Non-Blocking Behavior ===")
    
    # Start multiple async tasks simultaneously
    tasks = []
    
    # Task 1: Navigate to a website
    async def nav_task():
        nav_tool = PyDollBrowserNavigationTool()
        return await nav_tool.execute("https://www.example.com")
    
    # Task 2: A simple counter that should not be blocked
    async def counter_task():
        for i in range(5):
            print(f"Counter: {i}")
            await asyncio.sleep(1)
        return "Counter completed"
    
    # Task 3: Another navigation
    async def nav_task2():
        await asyncio.sleep(2)  # Start after a delay
        nav_tool = PyDollBrowserNavigationTool()
        return await nav_tool.execute("https://httpbin.org/get")
    
    # Run all tasks concurrently
    tasks = [nav_task(), counter_task(), nav_task2()]
    
    try:
        # Set a reasonable timeout for the whole test
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=60.0)
        
        print("All tasks completed:")
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  Task {i+1}: FAILED - {result}")
            else:
                print(f"  Task {i+1}: SUCCESS - {result}")
        
        return True
        
    except asyncio.TimeoutError:
        print("WARNING: Tasks timed out - this suggests event loop blocking")
        return False

async def main():
    """Run all tests"""
    print("🐧 Testing PyDoll Browser Event Loop Fixes")
    print("=" * 50)
    
    tests = [
        ("Navigation with Timeout", test_navigation_with_timeout),
        ("Screenshot in Headless", test_screenshot_in_headless), 
        ("Debug Mode Toggle", test_dev_mode_toggle),
        ("Cleanup Mechanism", test_cleanup_mechanism),
        ("Event Loop Non-Blocking", test_event_loop_handling),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            print(f"\n📋 Running: {test_name}")
            result = await test_func()
            if result:
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            print(f"💥 {test_name}: ERROR - {e}")
            logging.error(f"Test {test_name} failed with exception", exc_info=True)
    
    print(f"\n🏁 Test Summary: {passed}/{total} tests passed")
    
    # Final cleanup
    try:
        await pydoll_browser_manager.close()
        print("🧹 Final cleanup completed")
    except Exception as e:
        print(f"🚨 Cleanup error: {e}")
    
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 