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

                # Performance-oriented flags (avoid when dev_mode enabled)
                if not self.dev_mode:
                    perf_args = [
                        '--disable-extensions',
                        '--disable-gpu',
                        '--disable-dev-shm-usage',
                        '--blink-settings=imagesEnabled=false',
                        '--disable-background-timer-throttling',
                        '--disable-renderer-backgrounding',
                        '--disable-backgrounding-occluded-windows',
                        '--mute-audio',
                        '--window-size=1280,800',
                    ]
                    for arg in perf_args:
                        options.add_argument(arg)
                
                # Create browser instance
                self.browser = Chrome(options=options)
                await self.browser.start()
                
                # Get the page
                self.page = await self.browser.get_page()
                
                # Debug info only shown in dev mode
                if self.dev_mode:
                    logging.debug(f"Browser methods: {[m for m in dir(self.browser) if not m.startswith('_')]}")
                    logging.debug(f"Page methods: {[m for m in dir(self.page) if not m.startswith('_')]}")
                
                self.initialized = True
                return True
            except Exception as e:
                logging.error(f"Failed to initialize PyDoll browser: {str(e)}")
                # Always show traceback for debugging
                import traceback
                logging.error(f"Full traceback:\n{traceback.format_exc()}")
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
        """Perform an interaction with reliability improvements.

        - Scrolls target into view (JS fallback) before clicking
        - Uses wait_element when available; retries on transient failures
        - Returns richer debug info in dev mode
        """
        try:
            from pydoll.constants import By # type: ignore
        except ModuleNotFoundError:
            return (
                "PyDoll is not installed. Install with 'uv pip install pydoll-python' "
                "or 'pip install pydoll-python', then re-run."
            )

        async def _try_eval_js(page_obj: Any, script: str) -> bool:
            """Attempt multiple JS-eval method names exposed by PyDoll; return True on success."""
            candidates = [
                "evaluate", "evaluate_script", "execute_javascript", "execute_script", "eval_js", "run_js"
            ]
            for name in candidates:
                fn = getattr(page_obj, name, None)
                if not fn:
                    continue
                try:
                    if asyncio.iscoroutinefunction(fn):
                        await fn(script)
                    else:
                        res = fn(script)
                        if asyncio.iscoroutine(res):
                            await res
                    return True
                except Exception:
                    continue
            return False

        def _build_scroll_js(sel: str, sel_type: str) -> str:
            s = sel.replace("\\", "\\\\").replace("\"", "\\\"")
            if sel_type == "css":
                return (
                    f"(function(){{const el=document.querySelector(\"{s}\");"
                    f"if(el){{el.scrollIntoView({{block:'center',behavior:'auto'}});}}}})();"
                )
            if sel_type == "id":
                return (
                    f"(function(){{const el=document.getElementById(\"{s}\");"
                    f"if(el){{el.scrollIntoView({{block:'center',behavior:'auto'}});}}}})();"
                )
            if sel_type == "class_name":
                return (
                    f"(function(){{const el=document.getElementsByClassName(\"{s}\")[0];"
                    f"if(el){{el.scrollIntoView({{block:'center',behavior:'auto'}});}}}})();"
                )
            if sel_type == "xpath":
                return (
                    "(function(){const x=\"" + s + "\";"
                    "const r=document.evaluate(x,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);"
                    "const el=r.singleNodeValue; if(el){el.scrollIntoView({block:'center',behavior:'auto'});} })();"
                )
            # default css
            return (
                f"(function(){{const el=document.querySelector(\"{s}\");"
                f"if(el){{el.scrollIntoView({{block:'center',behavior:'auto'}});}}}})();"
            )

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

            # Prefer wait_element if available, else fall back to find_element
            get_element = getattr(page, "wait_element", None)
            if not callable(get_element):
                get_element = getattr(page, "find_element", None)

            async def _fetch_element(timeout: float = 10.0):
                return await asyncio.wait_for(get_element(by_selector, selector), timeout=timeout)  # type: ignore[arg-type]

            # Pre-scroll into view (best-effort)
            try:
                await _try_eval_js(page, _build_scroll_js(selector, selector_type))
            except Exception:
                pass

            if action == "click":
                last_exc: Optional[Exception] = None
                for attempt in range(3):
                    try:
                        element = await _fetch_element(timeout=12.0 if attempt == 0 else 8.0)
                        # Best-effort element-centered scroll
                        try:
                            await _try_eval_js(page, _build_scroll_js(selector, selector_type))
                        except Exception:
                            pass
                        await asyncio.wait_for(element.click(), timeout=8.0)
                        if pydoll_browser_manager.dev_mode:
                            logging.info("[PyDoll Dev] Successfully clicked on element")
                            try:
                                element_text = await asyncio.wait_for(element.get_text(), timeout=3.0)
                                return f"Successfully clicked on {selector}\n[Dev Mode] Element text: {element_text}"
                            except asyncio.TimeoutError:
                                logging.warning("[PyDoll Dev] Timeout getting element text")
                        return f"Successfully clicked on {selector}"
                    except Exception as e:
                        last_exc = e
                        # Retry after short delay and attempt another scroll
                        await asyncio.sleep(0.6)
                        try:
                            await _try_eval_js(page, _build_scroll_js(selector, selector_type))
                        except Exception:
                            pass
                # Exhausted retries
                err = f"Interaction failed: click on {selector} - {last_exc}"
                if pydoll_browser_manager.dev_mode:
                    logging.error(f"[PyDoll Dev] {err}", exc_info=True)
                return err

            elif action == "input" and text is not None:
                element = await _fetch_element(timeout=12.0)
                # Ensure visible
                try:
                    await _try_eval_js(page, _build_scroll_js(selector, selector_type))
                except Exception:
                    pass
                await asyncio.wait_for(element.clear(), timeout=6.0)
                await asyncio.wait_for(element.input(text), timeout=8.0)
                if pydoll_browser_manager.dev_mode:
                    logging.info("[PyDoll Dev] Successfully input text into element")
                    return f"Successfully input text into {selector}\n[Dev Mode] Text entered: {text}"
                return f"Successfully input text into {selector}"

            elif action == "submit":
                # Try to submit the element or its form
                element = await _fetch_element(timeout=12.0)
                try:
                    await asyncio.wait_for(element.submit(), timeout=10.0)
                except Exception:
                    # Fallback: attempt to submit via JS if it is a form or has a form parent
                    js = (
                        "(function(){const s=\"" + selector.replace("\\", "\\\\").replace("\"", "\\\"") + "\";"
                        "let el=null;"
                        + ("if('" + selector_type + "'=='css'){el=document.querySelector(s);}"
                           "else if('" + selector_type + "'=='id'){el=document.getElementById(s);}"
                           "else if('" + selector_type + "'=='class_name'){el=document.getElementsByClassName(s)[0];}"
                           "else {el=document.evaluate(s,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;}") +
                        "if(el){const f=el.tagName==='FORM'?el:el.form; if(f){f.submit();}}})();"
                    )
                    await _try_eval_js(page, js)
                if pydoll_browser_manager.dev_mode:
                    logging.info("[PyDoll Dev] Successfully submitted form")
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

class PyDollBrowserScrollTool:
    def __init__(self):
        self.metadata = {
            "name": "pydoll_browser_scroll",
            "description": "Scroll the page or an element using PyDoll with robust JS fallbacks.",
            "parameters": {
                "mode": {"type": "string", "enum": ["to", "by", "element", "page"]},
                "to": {"type": "string", "enum": ["top", "bottom"], "optional": True},
                "delta_y": {"type": "integer", "optional": True},
                "delta_x": {"type": "integer", "optional": True},
                "repeat": {"type": "integer", "optional": True},
                "selector": {"type": "string", "optional": True},
                "selector_type": {"type": "string", "enum": ["css", "xpath", "id", "class_name"], "optional": True},
                "behavior": {"type": "string", "enum": ["auto", "smooth"], "optional": True}
            }
        }

    async def execute(
        self,
        mode: str,
        to: Optional[str] = None,
        delta_y: Optional[int] = None,
        delta_x: Optional[int] = None,
        repeat: Optional[int] = None,
        selector: Optional[str] = None,
        selector_type: str = "css",
        behavior: str = "auto",
    ) -> str:
        """Scroll the page or a specific element.

        Args:
            mode: One of "to", "by", "element", or "page".
            to: When mode=="to", either "top" or "bottom".
            delta_y: When mode=="by" or "page", pixels to scroll vertically (default 800 for page down / -800 up).
            delta_x: Pixels to scroll horizontally (default 0).
            repeat: Repeat count for incremental scrolls (default 1).
            selector: When mode=="element", a selector to scroll into view.
            selector_type: One of css, xpath, id, class_name.
            behavior: "auto" or "smooth".
        """

        async def _try_eval_js(page_obj: Any, script: str) -> bool:
            candidates = [
                "evaluate", "evaluate_script", "execute_javascript", "execute_script", "eval_js", "run_js"
            ]
            for name in candidates:
                fn = getattr(page_obj, name, None)
                if not fn:
                    continue
                try:
                    if asyncio.iscoroutinefunction(fn):
                        await fn(script)
                    else:
                        res = fn(script)
                        if asyncio.iscoroutine(res):
                            await res
                    return True
                except Exception:
                    continue
            return False

        # Initialize with headless mode by default
        headless_mode = not pydoll_browser_manager.dev_mode
        if not await pydoll_browser_manager.initialize(headless=headless_mode):
            return "Failed to initialize browser"

        page = await pydoll_browser_manager.get_page()
        if not page:
            return "No active browser page found"

        try:
            behavior_js = "'smooth'" if behavior == "smooth" else "'auto'"
            if mode == "to":
                if to not in ("top", "bottom"):
                    return "Invalid 'to' value. Use 'top' or 'bottom'."
                top_expr = "0" if to == "top" else "document.body.scrollHeight"
                js = f"window.scrollTo({{top: {top_expr}, left: 0, behavior: {behavior_js}}});"
                ok = await _try_eval_js(page, js)
                return "Scrolled to bottom" if (ok and to == "bottom") else ("Scrolled to top" if ok else "Scroll failed")

            if mode == "by":
                dy = delta_y if isinstance(delta_y, int) else 800
                dx = delta_x if isinstance(delta_x, int) else 0
                times = repeat if isinstance(repeat, int) and repeat > 0 else 1
                js = f"window.scrollBy({{top: {dy}, left: {dx}, behavior: {behavior_js}}});"
                for _ in range(times):
                    await _try_eval_js(page, js)
                    await asyncio.sleep(0.05)
                return f"Scrolled by (x={dx}, y={dy}) x{times}"

            if mode == "page":
                # Convenience for page up/down/end/home
                direction = (to or "down").lower()
                if direction in ("down", "pagedown"):
                    dy = delta_y if isinstance(delta_y, int) else 800
                    times = repeat if isinstance(repeat, int) and repeat > 0 else 1
                    js = f"window.scrollBy({{top: {dy}, left: 0, behavior: {behavior_js}}});"
                    for _ in range(times):
                        await _try_eval_js(page, js)
                        await asyncio.sleep(0.05)
                    return f"Page scrolled down x{times}"
                if direction in ("up", "pageup"):
                    dy = -(delta_y if isinstance(delta_y, int) else 800)
                    times = repeat if isinstance(repeat, int) and repeat > 0 else 1
                    js = f"window.scrollBy({{top: {dy}, left: 0, behavior: {behavior_js}}});"
                    for _ in range(times):
                        await _try_eval_js(page, js)
                        await asyncio.sleep(0.05)
                    return f"Page scrolled up x{times}"
                if direction in ("end", "bottom"):
                    js = f"window.scrollTo({{top: document.body.scrollHeight, left: 0, behavior: {behavior_js}}});"
                    await _try_eval_js(page, js)
                    return "Scrolled to bottom"
                if direction in ("home", "top"):
                    js = f"window.scrollTo({{top: 0, left: 0, behavior: {behavior_js}}});"
                    await _try_eval_js(page, js)
                    return "Scrolled to top"
                return "Invalid page scroll direction"

            if mode == "element":
                if not selector:
                    return "Selector required for element scroll"
                s = selector.replace("\\", "\\\\").replace("\"", "\\\"")
                if selector_type == "css":
                    js = f"(function(){{const el=document.querySelector(\"{s}\"); if(el){{el.scrollIntoView({{block:'center',behavior:{behavior_js}}});}}}})();"
                elif selector_type == "id":
                    js = f"(function(){{const el=document.getElementById(\"{s}\"); if(el){{el.scrollIntoView({{block:'center',behavior:{behavior_js}}});}}}})();"
                elif selector_type == "class_name":
                    js = f"(function(){{const el=document.getElementsByClassName(\"{s}\")[0]; if(el){{el.scrollIntoView({{block:'center',behavior:{behavior_js}}});}}}})();"
                else:  # xpath
                    js = (
                        "(function(){const x=\"" + s + "\";"
                        "const r=document.evaluate(x,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);"
                        "const el=r.singleNodeValue; if(el){el.scrollIntoView({block:'center',behavior:" + behavior_js + "});} })();"
                    )
                ok = await _try_eval_js(page, js)
                return "Scrolled element into view" if ok else "Element scroll failed"

            return "Invalid scroll mode"
        except Exception as e:
            msg = f"Scroll failed: {str(e)}"
            logging.error(msg, exc_info=True)
            return msg

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