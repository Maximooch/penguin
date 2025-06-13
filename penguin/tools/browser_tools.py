import os
# TEMPORARILY DISABLED: browser-use causing Python 3.8-3.10 compatibility issues
# Disable browser-use telemetry
# os.environ["ANONYMIZED_TELEMETRY"] = "false"
# The fact I need to do this is a bit of a pain. And pretty concerning. I might need to look into alternatives. 


from typing import Optional, Dict, Any
# TEMPORARILY DISABLED: Using PyDoll instead of browser_use for now
# from browser_use import Browser, BrowserConfig # type: ignore
# from PIL import Image # type: ignore
import io
import base64
import asyncio
import logging
import importlib.metadata
import os
import datetime
import sys

class BrowserManager:
    """Manages browser instance and provides access to browser tools"""
    
    def __init__(self):
        self.browser = None
        self.initialized = False
        
        # TEMPORARILY DISABLED: browser-use compatibility issues
        # Detect browser-use version
        # try:
        #     self.browser_use_version = importlib.metadata.version("browser-use")
        #     logging.info(f"Detected browser-use version: {self.browser_use_version}")
        # except:
        #     self.browser_use_version = "unknown"
        #     logging.warning("Could not detect browser-use version")
        
        self.browser_use_version = "disabled"
        logging.warning("browser-use temporarily disabled for Python 3.8-3.10 compatibility. Use PyDoll instead.")
        
        # logging.info(f"browser-use version: {browser_use.__version__}") # Doesn't work, fix later.
        
    async def initialize(self, headless: bool = True):
        """Initialize the browser with OS-specific Chrome path"""
        # TEMPORARILY DISABLED: Return early when browser-use is disabled
        logging.warning("Browser tools temporarily disabled. Please use PyDoll for browser automation.")
        return False
        
        if not self.browser:
            try:
                # Prioritize Chromium paths
                chrome_path = None
                if os.name == 'nt':  # Windows
                    paths = [
                        'C:\\Program Files\\Chromium\\Application\\chrome.exe',
                        'C:\\Program Files (x86)\\Chromium\\Application\\chrome.exe',
                        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
                    ]
                elif sys.platform == 'darwin':  # macOS
                    paths = [
                        '/Applications/Chromium.app/Contents/MacOS/Chromium',
                        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                    ]
                else:  # Linux
                    paths = [
                        '/usr/bin/chromium',
                        '/usr/bin/chromium-browser',
                        '/usr/bin/google-chrome'
                    ]

                # Find first existing valid path
                for path in paths:
                    if os.path.exists(path):
                        chrome_path = path
                        break

                config = BrowserConfig(
                    headless=headless,
                    chrome_instance_path=chrome_path,
                    extra_chromium_args=[
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-popup-blocking',
                        '--disable-notifications'
                    ]
                )
                
                self.browser = Browser(config=config)
                logging.info(f"Initializing browser with config: {config}")
                
                # Debug: Print available browser methods
                logging.debug(f"Browser methods: {[m for m in dir(self.browser) if not m.startswith('_')]}")
                print(f"Browser methods: {[m for m in dir(self.browser) if not m.startswith('_')]}")

                # Create initial page
                await self._create_page()
                self.initialized = True
                return True
            except Exception as e:
                logging.error(f"Failed to initialize browser: {str(e)}")
                return False
        return True
    
    async def _create_page(self):
        """Create a new page if none exists"""
        try:
            if not hasattr(self, 'context') or not self.context:
                if hasattr(self.browser, 'new_context'):
                    self.context = await self.browser.new_context()
                    await self.context.create_new_tab()
                    logging.info("Created new browser context")
                else:
                    logging.error("Browser missing new_context method")
                    return False
            return True
        except Exception as e:
            logging.error(f"Error creating page: {str(e)}")
            return False
    
    async def get_page(self):
        """Get the current page through the context - async version"""
        try:
            if hasattr(self, 'context') and self.context:
                return await self.context.get_current_page()
            return None
        except Exception as e:
            logging.error(f"Error getting page: {str(e)}")
            return None
            
    async def close(self):
        """Close the browser instance"""
        if self.browser:
            try:
                # Close context first if it exists
                if hasattr(self, 'context') and self.context:
                    try:
                        await self.context.close()
                    except Exception as e:
                        logging.error(f"Error closing context: {str(e)}")
                    self.context = None
                
                # Then close the browser
                await self.browser.close()
                self.browser = None
                self.initialized = False
                return True
            except Exception as e:
                logging.error(f"Error closing browser: {str(e)}")
                return False
        return True

    async def reset(self):
        """Reset browser state by closing and cleaning up"""
        await self.close()
        self.initialized = False

    async def validate_browser_state(self) -> bool:
        """Validate browser is initialized and has an active page"""
        if not self.initialized or not self.browser:
            logging.warning("Browser not initialized")
            return False
        
        if not hasattr(self, 'context') or not self.context:
            logging.warning("No browser context available")
            return False
        
        try:
            # Fix: Properly await the coroutine
            page = await self.get_page()
            if not page:
                logging.warning("No active page available")
                return False
            
            return True
        except Exception as e:
            logging.error(f"Error validating browser state: {str(e)}")
            return False

    async def navigate_to(self, url: str) -> str:
        if not await self.validate_browser_state():
            await self.initialize()
        await self.context.navigate_to(url)
        return f"Navigated to {url}"

# Create a singleton instance
browser_manager = BrowserManager()

# Add an initialization function to be called at startup
async def initialize_browser(headless=False):
    """Initialize the browser manager with configured settings"""
    await browser_manager.initialize(headless=headless)
    return browser_manager

class BrowserNavigationTool:
    def __init__(self):
        self.metadata = {
            "name": "browser_navigate",
            "description": "Navigate to a URL in the browser",
            "parameters": {
                "url": {"type": "string", "description": "Full URL to navigate to"}
            }
        }

    async def execute(self, url: str) -> str:
        # Initialize with headless=False to see the browser window
        if not await browser_manager.initialize(headless=False):
            return "Failed to initialize browser"
            
        try:
            # Navigate directly using the context
            await browser_manager.context.navigate_to(url)
            return f"Navigated to {url}"
        except Exception as e:
            return f"Navigation failed: {str(e)}"

class BrowserInteractionTool:
    def __init__(self):
        self.metadata = {
            "name": "browser_interact",
            "description": "Interact with page elements",
            "parameters": {
                "action": {"type": "string", "enum": ["click", "input", "submit"]},
                "selector": {"type": "string"},
                "text": {"type": "string", "optional": True}
            }
        }

    async def execute(self, action: str, selector: str, text: Optional[str] = None) -> str:
        if not await browser_manager.initialize():
            return "Failed to initialize browser"
            
        try:
            # Use different API methods based on context behavior
            if action == "click":
                # Fix JavaScript string escaping
                clean_selector = selector.replace('"', '\\"')
                await browser_manager.context.execute_javascript(
                    f'document.querySelector("{clean_selector}").click();'
                )
                return f"Successfully clicked on {selector}"
            elif action == "input" and text:
                # Use proper escaping for both selector and text
                clean_selector = selector.replace('"', '\\"')
                clean_text = text.replace('"', '\\"').replace('\n', '\\n')
                await browser_manager.context.execute_javascript(
                    f'const element = document.querySelector("{clean_selector}"); '
                    f'element.value = "{clean_text}"; '
                    f'element.dispatchEvent(new Event("input", {{bubbles: true}}));'
                )
                return f"Successfully input text into {selector}"
            elif action == "submit":
                # Use JavaScript to submit form
                await browser_manager.context.execute_javascript(f"""
                    const element = document.querySelector("{selector}");
                    if (element.form) {{
                        element.form.submit();
                    }} else if (element.tagName === "FORM") {{
                        element.submit();
                    }}
                """)
                return f"Successfully submitted {selector}"
                
            return f"Successfully performed {action} on {selector}"
        except Exception as e:
            return f"Interaction failed: {str(e)}"

class BrowserScreenshotTool:
    def __init__(self):
        self.metadata = {
            "name": "browser_screenshot",
            "description": "Capture visible page content as image",
            "parameters": {}
        }

    async def execute(self) -> Dict[str, Any]:
        """Take a screenshot of the current browser page."""
        try:
            # First ensure browser is initialized
            if not await browser_manager.initialize(headless=False):
                return {"error": "Browser not initialized"}
            
            page = await browser_manager.get_page()
            if not page:
                return {"error": "No active browser page found. Try navigating to a page first."}
            
            # Get screenshot as bytes
            screenshot_bytes = await page.screenshot()
            
            # Save to a file in the screenshots directory
            import os
            import datetime
            from pathlib import Path
            
            # Create screenshots directory if it doesn't exist
            screenshots_dir = os.path.join(os.environ.get("WORKSPACE_PATH", "."), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            # Generate a filename based on timestamp
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.jpg"
            filepath = os.path.join(screenshots_dir, filename)
            
            # Save the bytes to file
            with open(filepath, "wb") as f:
                f.write(screenshot_bytes)
            
            return {
                "result": "Screenshot captured",
                "filepath": filepath,
                "timestamp": timestamp
            }
        except Exception as e:
            return {"error": str(e)} 