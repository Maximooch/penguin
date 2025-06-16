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
        self._last_activity = None
        self._cleanup_task = None
        
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
        
        # Start cleanup timer for inactive browser instances
        self._update_activity()
        await self._start_cleanup_timer()
        return True
    
    def set_dev_mode(self, enabled: bool):
        """Enable or disable developer mode for debug output"""
        self.dev_mode = enabled
        logging.info(f"PyDoll developer mode {'enabled' if enabled else 'disabled'}")
        return self.dev_mode

    def _update_activity(self):
        """Update the last activity timestamp"""
        import time
        self._last_activity = time.time()
    
    async def _start_cleanup_timer(self):
        """Start a background task to cleanup inactive browser instances"""
        if self._cleanup_task:
            return
            
        async def cleanup_worker():
            import time
            while self.browser and self.initialized:
                await asyncio.sleep(30)  # Check every 30 seconds
                if self._last_activity and (time.time() - self._last_activity) > 300:  # 5 minutes
                    logging.info("PyDoll browser inactive for 5 minutes, closing automatically")
                    await self.close()
                    break
                    
        self._cleanup_task = asyncio.create_task(cleanup_worker())

    async def get_page(self):
        """Get the current page - async version"""
        try:
            self._update_activity()
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
        # Cancel cleanup task first
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            
        if self.browser:
            try:
                await self.browser.stop()
                self.browser = None
                self.page = None
                self.initialized = False
                self._last_activity = None
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
        # Initialize with headless=True by default to prevent blocking
        # Only use headless=False if explicitly needed for debugging
        headless_mode = not pydoll_browser_manager.dev_mode
        
        if not await pydoll_browser_manager.initialize(headless=headless_mode):
            return "Failed to initialize browser"
            
        try:
            # Navigate directly with timeout to prevent hanging
            page = await pydoll_browser_manager.get_page()
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Navigating to URL: {url}")
                
            # Add timeout to prevent blocking
            await asyncio.wait_for(page.go_to(url), timeout=60.0)
            
            if pydoll_browser_manager.dev_mode:
                logging.info(f"[PyDoll Dev] Successfully navigated to: {url}")
                # Add page information in dev mode
                try:
                    title = await asyncio.wait_for(page.get_title(), timeout=5.0)
                    current_url = await asyncio.wait_for(page.get_url(), timeout=5.0)
                    return f"Navigated to {url}\n[Dev Mode] Page Title: {title}\nFinal URL: {current_url}"
                except asyncio.TimeoutError:
                    logging.warning("[PyDoll Dev] Timeout getting page info")
                except Exception as e:
                    logging.error(f"[PyDoll Dev] Error getting page info: {str(e)}")
                    
            return f"Navigated to {url}"
        except asyncio.TimeoutError:
            error_msg = f"Navigation timeout: {url} took longer than 60 seconds"
            logging.error(error_msg)
            return error_msg
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
        
        # Initialize with headless mode by default
        headless_mode = not pydoll_browser_manager.dev_mode
        if not await pydoll_browser_manager.initialize(headless=headless_mode):
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
                element = await asyncio.wait_for(page.find_element(by_selector, selector), timeout=10.0)
                await asyncio.wait_for(element.click(), timeout=5.0)
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully clicked on element")
                    try:
                        element_text = await asyncio.wait_for(element.get_text(), timeout=3.0)
                        return f"Successfully clicked on {selector}\n[Dev Mode] Element text: {element_text}"
                    except asyncio.TimeoutError:
                        logging.warning("[PyDoll Dev] Timeout getting element text")
                return f"Successfully clicked on {selector}"
                
            elif action == "input" and text:
                element = await asyncio.wait_for(page.find_element(by_selector, selector), timeout=10.0)
                await asyncio.wait_for(element.clear(), timeout=5.0)
                await asyncio.wait_for(element.input(text), timeout=5.0)
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully input text into element")
                    return f"Successfully input text into {selector}\n[Dev Mode] Text entered: {text}"
                return f"Successfully input text into {selector}"
                
            elif action == "submit":
                if selector_type == "css" and selector.lower().startswith("form"):
                    # If selector is a form, find it and submit
                    form = await asyncio.wait_for(page.find_element(by_selector, selector), timeout=10.0)
                    await asyncio.wait_for(form.submit(), timeout=10.0)
                else:
                    # If not a form selector, find the element and its parent form
                    element = await asyncio.wait_for(page.find_element(by_selector, selector), timeout=10.0)
                    await asyncio.wait_for(element.submit(), timeout=10.0)
                
                if pydoll_browser_manager.dev_mode:
                    logging.info(f"[PyDoll Dev] Successfully submitted form")
                    try:
                        current_url = await asyncio.wait_for(page.get_url(), timeout=5.0)
                        return f"Successfully submitted {selector}\n[Dev Mode] Current URL after submit: {current_url}"
                    except asyncio.TimeoutError:
                        logging.warning("[PyDoll Dev] Timeout getting URL after submit")
                return f"Successfully submitted {selector}"
                
            return f"Successfully performed {action} on {selector}"
        except asyncio.TimeoutError:
            error_msg = f"Interaction timeout: {action} on {selector} took too long"
            logging.error(error_msg)
            return error_msg
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
            # First ensure browser is initialized with headless mode by default
            headless_mode = not pydoll_browser_manager.dev_mode
            if not await pydoll_browser_manager.initialize(headless=headless_mode):
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
                    url = await asyncio.wait_for(page.get_url(), timeout=5.0)
                    title = await asyncio.wait_for(page.get_title(), timeout=5.0)
                    logging.info(f"[PyDoll Dev] Current URL: {url}, Title: {title}")
                except asyncio.TimeoutError:
                    logging.warning("[PyDoll Dev] Timeout getting page info for screenshot")
                except Exception as e:
                    logging.error(f"[PyDoll Dev] Error getting page info: {str(e)}")
            
            # Take the screenshot using the correct PyDoll API with timeout
            # PyDoll's page.get_screenshot() method directly saves to the specified path
            await asyncio.wait_for(page.get_screenshot(filepath), timeout=15.0)
            
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
        except asyncio.TimeoutError:
            error_msg = "Screenshot timeout: operation took longer than 15 seconds"
            logging.error(error_msg)
            return {"error": error_msg}
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