import os
import logging
import asyncio
import importlib.metadata
import datetime
import sys
from typing import Optional, Dict, Any, List

class PyDollBrowserManager:
    """Manages PyDoll browser instance and provides access to browser tools"""
    
    def __init__(self, dev_mode: bool = False):
        self.browser = None
        self.page = None
        self.initialized = False
        self.dev_mode = dev_mode
        
        # Detect pydoll version
        try:
            self.pydoll_version = importlib.metadata.version("pydoll-python")
            logging.info(f"Detected pydoll-python version: {self.pydoll_version}")
        except:
            self.pydoll_version = "unknown"
            logging.warning("Could not detect pydoll-python version")
        
    async def initialize(self, headless: bool = True):
        """Initialize the browser with OS-specific Chrome path"""
        if not self.browser:
            try:
                # Import pydoll packages
                from pydoll.browser.chrome import Chrome # type: ignore
                from pydoll.browser.options import Options # type: ignore
                
                # Configure Chrome options
                options = Options()
                
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
                
                if chrome_path:
                    options.binary_location = chrome_path
                
                # Configure common options
                if headless:
                    options.add_argument('--headless=new')
                
                # Add extra chromium arguments
                extra_args = [
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-popup-blocking',
                    '--disable-notifications'
                ]
                
                for arg in extra_args:
                    options.add_argument(arg)
                
                # Create browser instance
                self.browser = Chrome(options=options)
                await self.browser.start()
                
                # Get the page
                self.page = await self.browser.get_page()
                
                # Debug info only shown in dev mode
                if self.dev_mode:
                    logging.debug(f"Browser methods: {[m for m in dir(self.browser) if not m.startswith('_')]}")
                    print(f"Browser methods: {[m for m in dir(self.browser) if not m.startswith('_')]}")
                    logging.debug(f"Page methods: {[m for m in dir(self.page) if not m.startswith('_')]}")
                    print(f"Page methods: {[m for m in dir(self.page) if not m.startswith('_')]}")
                
                self.initialized = True
                return True
            except Exception as e:
                logging.error(f"Failed to initialize PyDoll browser: {str(e)}")
                if self.dev_mode:
                    # Show more detailed error info in dev mode
                    logging.error(f"Detailed error: {e}", exc_info=True)
                return False
        return True
    
    def set_dev_mode(self, enabled: bool):
        """Enable or disable developer mode for debug output"""
        self.dev_mode = enabled
        logging.info(f"PyDoll developer mode {'enabled' if enabled else 'disabled'}")
        return self.dev_mode

    async def get_page(self):
        """Get the current page - async version"""
        try:
            if self.page:
                return self.page
            elif self.browser:
                self.page = await self.browser.get_page()
                return self.page
            return None
        except Exception as e:
            logging.error(f"Error getting page: {str(e)}")
            if self.dev_mode:
                logging.error(f"Detailed error: {e}", exc_info=True)
            return None
            
    async def close(self):
        """Close the browser instance"""
        if self.browser:
            try:
                await self.browser.stop()
                self.browser = None
                self.page = None
                self.initialized = False
                return True
            except Exception as e:
                logging.error(f"Error closing browser: {str(e)}")
                if self.dev_mode:
                    logging.error(f"Detailed error: {e}", exc_info=True)
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
        
        try:
            # Check if page is available
            page = await self.get_page()
            if not page:
                logging.warning("No active page available")
                return False
            
            return True
        except Exception as e:
            logging.error(f"Error validating browser state: {str(e)}")
            if self.dev_mode:
                logging.error(f"Detailed error: {e}", exc_info=True)
            return False

    async def navigate_to(self, url: str) -> str:
        """Navigate to a URL"""
        if not await self.validate_browser_state():
            await self.initialize()
        
        page = await self.get_page()
        await page.go_to(url)
        return f"Navigated to {url}"

# Create a singleton instance with dev mode disabled by default
pydoll_browser_manager = PyDollBrowserManager(dev_mode=False)

# Add an initialization function to be called at startup
async def initialize_browser(headless=False):
    """Initialize the browser manager with configured settings"""
    await pydoll_browser_manager.initialize(headless=headless)
    return pydoll_browser_manager

class PyDollBrowserNavigationTool:
    def __init__(self):
        self.metadata = {
            "name": "pydoll_browser_navigate",
            "description": "Navigate to a URL in the browser",
            "parameters": {
                "url": {"type": "string", "description": "Full URL to navigate to"}
            }
        }

    async def execute(self, url: str) -> str:
        # Initialize with headless=False to see the browser window
        if not await pydoll_browser_manager.initialize(headless=False):
            return "Failed to initialize browser"
            
        try:
            # Navigate directly
            page = await pydoll_browser_manager.get_page()
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Navigating to URL: {url}")
                
            await page.go_to(url)
            
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Successfully navigated to: {url}")
                # Add page information in dev mode
                try:
                    title = await page.get_title()
                    current_url = await page.get_url()
                    return f"Navigated to {url}\n[Dev Mode] Page Title: {title}\nFinal URL: {current_url}"
                except Exception as e:
                    logging.error(f"[PyDoll Dev] Error getting page info: {str(e)}")
                    
            return f"Navigated to {url}"
        except Exception as e:
            error_msg = f"Navigation failed: {str(e)}"
            if pydoll_browser_manager.dev_mode:
                logging.error(f"[PyDoll Dev] {error_msg}", exc_info=True)
            return error_msg

class PyDollBrowserInteractionTool:
    def __init__(self):
        self.metadata = {
            "name": "pydoll_browser_interact",
            "description": "Interact with page elements",
            "parameters": {
                "action": {"type": "string", "enum": ["click", "input", "submit"]},
                "selector": {"type": "string"},
                "selector_type": {"type": "string", "enum": ["css", "xpath", "id", "class_name"], "default": "css"},
                "text": {"type": "string", "optional": True}
            }
        }

    async def execute(self, action: str, selector: str, selector_type: str = "css", text: Optional[str] = None) -> str:
        from pydoll.constants import By # type: ignore
        if not await pydoll_browser_manager.initialize():
            return "Failed to initialize browser"
            
        try:
            page = await pydoll_browser_manager.get_page()
            
            # Map selector type to By constant
            selector_map = {
                "css": By.CSS_SELECTOR,
                "xpath": By.XPATH,
                "id": By.ID,
                "class_name": By.CLASS_NAME
            }
            by_selector = selector_map.get(selector_type, By.CSS_SELECTOR)
            
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Executing {action} on {selector_type} selector: {selector}")
                if text:
                    logging.info(f"[PyDoll Dev] Text to input: {text}")
            
            if action == "click":
                element = await page.find_element(by_selector, selector)
                await element.click()
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully clicked on element")
                    element_text = await element.get_text()
                    return f"Successfully clicked on {selector}\n[Dev Mode] Element text: {element_text}"
                return f"Successfully clicked on {selector}"
                
            elif action == "input" and text:
                element = await page.find_element(by_selector, selector)
                await element.clear()
                await element.input(text)
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully input text into element")
                    return f"Successfully input text into {selector}\n[Dev Mode] Text entered: {text}"
                return f"Successfully input text into {selector}"
                
            elif action == "submit":
                if selector_type == "css" and selector.lower().startswith("form"):
                    # If selector is a form, find it and submit
                    form = await page.find_element(by_selector, selector)
                    await form.submit()
                else:
                    # If not a form selector, find the element and its parent form
                    element = await page.find_element(by_selector, selector)
                    await element.submit()
                
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully submitted form")
                    current_url = await page.get_url()
                    return f"Successfully submitted {selector}\n[Dev Mode] Current URL after submit: {current_url}"
                return f"Successfully submitted {selector}"
                
            return f"Successfully performed {action} on {selector}"
        except Exception as e:
            error_msg = f"Interaction failed: {str(e)}"
            if pydoll_browser_manager.dev_mode:
                logging.error(f"[PyDoll Dev] {error_msg}", exc_info=True)
            return error_msg

class PyDollBrowserScreenshotTool:
    def __init__(self):
        self.metadata = {
            "name": "pydoll_browser_screenshot",
            "description": "Capture visible page content as image",
            "parameters": {}
        }

    async def execute(self) -> Dict[str, Any]:
        """Take a screenshot of the current browser page."""
        try:
            # First ensure browser is initialized
            if not await pydoll_browser_manager.initialize(headless=False):
                return {"error": "Browser not initialized"}
            
            page = await pydoll_browser_manager.get_page()
            if not page:
                return {"error": "No active browser page found. Try navigating to a page first."}
            
            # Create screenshots directory if it doesn't exist
            screenshots_dir = os.path.join(os.getcwd(), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            # Generate a filename based on timestamp
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pydoll_screenshot_{timestamp}.png"
            filepath = os.path.join(screenshots_dir, filename)
            
            # Debug logging
            logging.info(f"Taking screenshot with PyDoll, saving to: {filepath}")
            
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Taking screenshot of current page")
                try:
                    url = await page.get_url()
                    title = await page.get_title()
                    logging.info(f"[PyDoll Dev] Current URL: {url}, Title: {title}")
                except Exception as e:
                    logging.error(f"[PyDoll Dev] Error getting page info: {str(e)}")
            
            # Take the screenshot using the correct PyDoll API
            # PyDoll's page.get_screenshot() method directly saves to the specified path
            await page.get_screenshot(filepath)
            
            # Verify the file was created
            if not os.path.exists(filepath):
                error_msg = "Screenshot was not saved properly"
                if pydoll_browser_manager.dev_mode:
                    logging.error(f"[PyDoll Dev] {error_msg} - File not found: {filepath}")
                return {"error": error_msg}
            
            logging.info(f"Screenshot successfully saved to {filepath}")
            
            if pydoll_browser_manager.dev_mode:
                # Add file size info in dev mode
                file_size = os.path.getsize(filepath)
                file_size_kb = file_size / 1024
                return {
                    "result": "Screenshot captured",
                    "filepath": filepath,
                    "timestamp": timestamp,
                    "dev_info": {
                        "file_size": f"{file_size_kb:.2f} KB",
                        "directory": screenshots_dir,
                        "absolute_path": os.path.abspath(filepath)
                    }
                }
            else:
                return {
                    "result": "Screenshot captured",
                    "filepath": filepath,
                    "timestamp": timestamp
                }
        except Exception as e:
            error_msg = f"Screenshot failed: {str(e)}"
            logging.error(f"Error in PyDoll screenshot: {str(e)}", exc_info=True)
            if pydoll_browser_manager.dev_mode:
                logging.error(f"[PyDoll Dev] {error_msg}", exc_info=True)
            return {"error": error_msg} 

async def pydoll_debug_toggle(enabled: Optional[bool] = None) -> bool:
    """
    Toggle PyDoll debug mode or set it to a specific state if enabled is provided.
    
    Args:
        enabled: Optional boolean to explicitly set the debug mode state
                If None, current state will be toggled
                
    Returns:
        New debug mode state (True if enabled, False if disabled)
    """
    if enabled is None:
        # Toggle the current state
        new_state = not pydoll_browser_manager.dev_mode
    else:
        # Set to the specified state
        new_state = enabled
        
    # Apply the new state
    return pydoll_browser_manager.set_dev_mode(new_state) 