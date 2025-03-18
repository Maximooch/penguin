import os
# Disable browser-use telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "false"
# The fact I need to do this is a bit of a pain. And pretty concerning. I might need to look into alternatives. 


from typing import Optional, Dict, Any
from browser_use import Browser, BrowserConfig # type: ignore
from PIL import Image # type: ignore
import io
import base64
import asyncio
import logging
import importlib.metadata
import os
import datetime

class BrowserManager:
    """Manages browser instance and provides access to browser tools"""
    
    def __init__(self):
        self.browser = None
        self.initialized = False
        
        # Detect browser-use version
        try:
            self.browser_use_version = importlib.metadata.version("browser-use")
            logging.info(f"Detected browser-use version: {self.browser_use_version}")
        except:
            self.browser_use_version = "unknown"
            logging.warning("Could not detect browser-use version")
        
        # logging.info(f"browser-use version: {browser_use.__version__}") # Doesn't work, fix later.
        
    async def initialize(self, headless: bool = True):
        """Initialize the browser with minimal configuration"""
        if not self.browser:
            try:
                self.browser = Browser(
                    config=BrowserConfig(
                        headless=headless
                    )
                )
                
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
            # Create a context first, then create a tab
            if hasattr(self.browser, 'new_context'):
                # Store the context for future use
                self.context = await self.browser.new_context()
                
                # Create a new tab
                await self.context.create_new_tab()
                # Could it be that self.context is not for a next context session 
                
                # Don't try to directly store the page - the context manages it
                logging.info("Successfully created browser context and tab")
                return True
            else:
                logging.error("Browser API missing expected methods (new_context)")
                return False
        except Exception as e:
            logging.error(f"Error creating page: {str(e)}")
            logging.error(f"Exception type: {type(e)}")
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
        
        page = self.get_page()
        if not page:
            logging.warning("No active page available")
            return False
        
        return True

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
                return {"error": "Failed to initialize browser"}
            
            # Get page asynchronously
            page = await browser_manager.get_page()
            if not page:
                return {"error": "No active browser page found. Try navigating to a page first."}
            
            # Generate timestamp-based filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            
            # Define screenshots directory (relative to workspace)
            screenshots_dir = os.path.join(os.getcwd(), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)
            
            filepath = os.path.join(screenshots_dir, filename)
            
            # Take the screenshot - make sure to await this as well
            await page.screenshot(path=filepath)
            
            return {
                "result": f"Screenshot saved to {filepath}",
                "filepath": filepath,
                "filename": filename
            }
        except Exception as e:
            logging.error(f"Screenshot failed: {str(e)}")
            return {"error": f"Screenshot failed: {str(e)}"} 