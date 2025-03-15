from typing import Optional, Dict, Any
from browser_use import Browser # type: ignore
from PIL import Image # type: ignore
import io
import base64

class BrowserNavigationTool:
    def __init__(self, browser: Browser):
        self.browser = browser
        self.metadata = {
            "name": "browser_navigate",
            "description": "Navigate to a URL in the browser",
            "parameters": {
                "url": {"type": "string", "description": "Full URL to navigate to"}
            }
        }

    async def execute(self, url: str) -> str:
        try:
            await self.browser.goto(url)
            return f"Navigated to {url}"
        except Exception as e:
            return f"Navigation failed: {str(e)}"

class BrowserInteractionTool:
    def __init__(self, browser: Browser):
        self.browser = browser
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
        try:
            element = await self.browser.find_element(selector)
            if action == "click":
                await element.click()
            elif action == "input" and text:
                await element.type(text)
            elif action == "submit":
                await element.submit()
            return f"Successfully performed {action} on {selector}"
        except Exception as e:
            return f"Interaction failed: {str(e)}"

class BrowserScreenshotTool:
    def __init__(self, browser: Browser):
        self.browser = browser
        self.metadata = {
            "name": "browser_screenshot",
            "description": "Capture visible page content as image",
            "parameters": {}
        }

    async def execute(self) -> Dict[str, Any]:
        try:
            screenshot = await self.browser.screenshot()
            img = Image.open(io.BytesIO(screenshot))
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return {
                "image": base64.b64encode(buffered.getvalue()).decode("utf-8"),
                "message": "Screenshot captured"
            }
        except Exception as e:
            return {"error": str(e)} 