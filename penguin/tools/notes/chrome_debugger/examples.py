"""
Examples of using the Chrome DevTools Protocol debugger in Penguin.

This file contains examples for common Chrome debugging tasks.
"""

import asyncio
import os
import logging
from penguin.tools.chrome_debugger import ChromeDebugger

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a directory for the screenshots
os.makedirs("screenshots", exist_ok=True)


async def example_basic_navigation():
    """Example: Basic navigation and screenshot capture."""
    debugger = ChromeDebugger(host="localhost", port=9222)
    
    try:
        # Connect to Chrome
        if not await debugger.connect():
            logger.error("Failed to connect to Chrome")
            return
        
        logger.info("Connected to Chrome debugger")
        
        # Enable the Page domain
        await debugger.enable_domain("Page")
        
        # Navigate to a URL
        logger.info("Navigating to example.com")
        if await debugger.navigate("https://example.com"):
            logger.info("Navigation started")
        
        # Wait for page load (in a real scenario, you would use event handlers)
        logger.info("Waiting for page load")
        await asyncio.sleep(3)
        
        # Take a screenshot
        screenshot_path = await debugger.take_screenshot()
        logger.info(f"Screenshot saved to {screenshot_path}")
        
    finally:
        # Clean up
        await debugger.disconnect()
        logger.info("Disconnected from Chrome debugger")


async def example_console_monitoring():
    """Example: Monitor browser console messages."""
    debugger = ChromeDebugger(host="localhost", port=9222)
    
    try:
        # Connect to Chrome
        if not await debugger.connect():
            logger.error("Failed to connect to Chrome")
            return
        
        # Enable Console domain
        await debugger.enable_domain("Console")
        
        # Register event handler for console messages
        async def console_message_handler(params):
            message = params.get("message", {})
            text = message.get("text", "")
            level = message.get("level", "info")
            logger.info(f"Console {level}: {text}")
        
        await debugger.register_event_handler("Console.messageAdded", console_message_handler)
        
        # Enable Runtime domain
        await debugger.enable_domain("Runtime")
        
        # Navigate to a page
        await debugger.enable_domain("Page")
        await debugger.navigate("https://example.com")
        
        # Execute JavaScript that logs to console
        await debugger.evaluate_javascript("console.log('Hello from Python!'); console.error('This is an error');")
        
        # Wait to see console messages
        logger.info("Waiting for console messages...")
        await asyncio.sleep(5)
        
    finally:
        await debugger.disconnect()
        logger.info("Disconnected from Chrome debugger")


async def example_network_monitoring():
    """Example: Monitor network requests."""
    debugger = ChromeDebugger(host="localhost", port=9222)
    
    try:
        # Connect to Chrome
        if not await debugger.connect():
            logger.error("Failed to connect to Chrome")
            return
        
        # Enable Network domain
        await debugger.enable_domain("Network")
        
        # Register event handlers for network events
        async def request_handler(params):
            request = params.get("request", {})
            url = request.get("url", "")
            method = request.get("method", "")
            logger.info(f"Request: {method} {url}")
        
        async def response_handler(params):
            response = params.get("response", {})
            url = response.get("url", "")
            status = response.get("status", 0)
            logger.info(f"Response: {status} {url}")
        
        await debugger.register_event_handler("Network.requestWillBeSent", request_handler)
        await debugger.register_event_handler("Network.responseReceived", response_handler)
        
        # Navigate to a page
        await debugger.enable_domain("Page")
        await debugger.navigate("https://example.com")
        
        # Wait to see network activity
        logger.info("Monitoring network requests for 10 seconds...")
        await asyncio.sleep(10)
        
    finally:
        await debugger.disconnect()
        logger.info("Disconnected from Chrome debugger")


async def example_javascript_debugging():
    """Example: JavaScript debugging capabilities."""
    debugger = ChromeDebugger(host="localhost", port=9222)
    
    try:
        # Connect to Chrome
        if not await debugger.connect():
            logger.error("Failed to connect to Chrome")
            return
        
        # Enable Debugger domain
        await debugger.enable_domain("Debugger")
        
        # Register event handlers for debugging events
        async def script_parsed_handler(params):
            url = params.get("url", "")
            if url and not url.startswith("chrome-extension"):
                logger.info(f"Script parsed: {url}")
        
        async def paused_handler(params):
            reason = params.get("reason", "")
            location = params.get("callFrames", [{}])[0].get("location", {})
            logger.info(f"Debugger paused: {reason} at {location}")
            
            # Resume execution after a pause
            await debugger.execute("Debugger.resume")
        
        await debugger.register_event_handler("Debugger.scriptParsed", script_parsed_handler)
        await debugger.register_event_handler("Debugger.paused", paused_handler)
        
        # Navigate to a page
        await debugger.enable_domain("Page")
        await debugger.navigate("https://example.com")
        
        # Wait for scripts to load
        await asyncio.sleep(3)
        
        # Set a breakpoint in a setTimeout callback
        await debugger.evaluate_javascript("""
            setTimeout(() => {
                console.log('Before breakpoint');
                debugger;  // This will trigger a pause
                console.log('After breakpoint');
            }, 1000);
        """)
        
        # Wait for the breakpoint to hit
        logger.info("Waiting for breakpoint...")
        await asyncio.sleep(5)
        
    finally:
        await debugger.disconnect()
        logger.info("Disconnected from Chrome debugger")


async def example_dom_manipulation():
    """Example: DOM manipulation through CDP."""
    debugger = ChromeDebugger(host="localhost", port=9222)
    
    try:
        # Connect to Chrome
        if not await debugger.connect():
            logger.error("Failed to connect to Chrome")
            return
        
        # Enable required domains
        await debugger.enable_domain("Page")
        await debugger.enable_domain("DOM")
        
        # Navigate to a page
        await debugger.navigate("https://example.com")
        
        # Wait for page to load
        await asyncio.sleep(3)
        
        # Get the document node
        document = await debugger.execute("DOM.getDocument", {"depth": 1})
        root_node_id = document.get("root", {}).get("nodeId")
        
        # Find the <h1> element
        result = await debugger.execute("DOM.querySelector", {
            "nodeId": root_node_id,
            "selector": "h1"
        })
        h1_node_id = result.get("nodeId")
        
        # Get the text content of the <h1>
        result = await debugger.execute("DOM.getOuterHTML", {"nodeId": h1_node_id})
        logger.info(f"Current h1: {result.get('outerHTML')}")
        
        # Change the text content
        await debugger.execute("DOM.setNodeValue", {
            "nodeId": h1_node_id,
            "value": "Modified by Penguin CDP Debugger"
        })
        
        # Alternatively, use JavaScript to modify the DOM
        new_title = "Modified with evaluate_javascript"
        await debugger.evaluate_javascript(f"""
            document.querySelector('h1').textContent = '{new_title}';
        """)
        
        # Take a screenshot to verify
        screenshot_path = await debugger.take_screenshot()
        logger.info(f"Screenshot with modified DOM saved to {screenshot_path}")
        
    finally:
        await debugger.disconnect()
        logger.info("Disconnected from Chrome debugger")


async def main():
    """Run all examples one by one."""
    examples = [
        example_basic_navigation,
        example_console_monitoring,
        example_network_monitoring,
        example_javascript_debugging,
        example_dom_manipulation
    ]
    
    for i, example in enumerate(examples):
        logger.info(f"\n\n======== Running example {i+1}/{len(examples)}: {example.__name__} ========\n")
        try:
            await example()
        except Exception as e:
            logger.error(f"Example failed: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main()) 