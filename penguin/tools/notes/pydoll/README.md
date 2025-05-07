# PyDoll Browser Tools

## Overview

PyDoll Browser Tools provide a webdriver-free alternative to browser automation in Penguin. Unlike traditional browser automation tools like Selenium or Playwright that require a separate WebDriver, PyDoll connects directly to browsers using their DevTools Protocol, providing several advantages:

1. **No WebDriver dependency**: Eliminates compatibility issues between browser versions and WebDrivers
2. **Native Captcha Bypass**: Better handles Cloudflare Turnstile and reCAPTCHA v3 challenges
3. **Asynchronous performance**: Built with Python's asyncio for efficient operations
4. **Human-like interactions**: More realistic browsing patterns that avoid detection
5. **Simpler setup**: Less configuration and fewer external dependencies

## Installation

PyDoll is automatically installed when you install Penguin. If you need to install it manually:

```bash
pip install pydoll-python
```

PyDoll has minimal dependencies (websockets, aiohttp, aiofiles, bs4).

## Available Tools

### 1. PyDoll Browser Navigation

Navigate to any URL in the browser.

```python
# Example usage
result = await pydoll_browser_manager.navigate_to("https://example.com")
```

### 2. PyDoll Browser Interaction

Interact with page elements using various selectors (CSS, XPath, ID, class name).

```python
# Click example
await pydoll_browser_interaction_tool.execute("click", ".button-class", "css")

# Input example
await pydoll_browser_interaction_tool.execute("input", "#search-input", "css", "search term")

# Submit form example
await pydoll_browser_interaction_tool.execute("submit", "form#login", "css")
```

### 3. PyDoll Browser Screenshot

Capture screenshots of the current page.

```python
# Take a screenshot
result = await pydoll_browser_screenshot_tool.execute()
# Returns the path to the saved screenshot
```

## Usage in Penguin Core

When using these tools in Penguin, the tools are available through the ToolManager:

```python
# Example inside a function
async def process_with_browser():
    tool_manager = ToolManager(log_error)
    
    # Navigate to a URL
    tool_manager.execute_tool("pydoll_browser_navigate", {"url": "https://example.com"})
    
    # Click a button
    tool_manager.execute_tool("pydoll_browser_interact", {
        "action": "click",
        "selector": ".my-button",
        "selector_type": "css"
    })
    
    # Take a screenshot
    screenshot_result = tool_manager.execute_tool("pydoll_browser_screenshot", {})
    
    # Remember to close the browser when done
    await tool_manager.close_pydoll_browser()
```

## Configuration

PyDoll's browser can be configured with various options for headless mode, proxies, and other browser settings:

```python
from pydoll.browser.chrome import Chrome
from pydoll.browser.options import Options

# Configure options
options = Options()
options.add_argument('--headless=new')  # Run in headless mode
options.add_argument('--start-maximized')  # Maximize window
options.add_argument('--disable-notifications')  # Disable browser notifications

# Create browser with options
browser = Chrome(options=options)
await browser.start()
```

## Error Handling

PyDoll browser tools include comprehensive error handling and logging:

- Each function returns clear error messages when operations fail
- Errors are logged through Penguin's logging system
- Screenshots can be captured for debugging purposes

## Comparison with Browser-Use

While both PyDoll and Browser-Use provide browser automation capabilities, PyDoll offers some advantages:

1. **Better detection avoidance**: More human-like interactions that avoid bot detection
2. **Captcha handling**: Built-in capabilities for bypassing common captcha systems
3. **API consistency**: More Selenium-like API that's familiar to many developers
4. **Active development**: Ongoing updates and improvements

## When to Use PyDoll vs Browser-Use

- **Use PyDoll** when working with sites that have sophisticated bot detection, need captcha bypassing, or when you need more human-like interactions.
- **Use Browser-Use** for simpler automation tasks or when you have existing code that works well with it.

Both tools are available in Penguin, giving you flexibility based on your specific needs. 