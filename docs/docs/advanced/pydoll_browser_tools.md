# PyDoll Browser Tools

Penguin includes [PyDoll](https://github.com/pydoll) integration for browser automation. PyDoll connects directly to Chrome or other browsers via their DevTools protocol, so no separate WebDriver is required.

## Features

- Human‑like browsing that helps avoid detection
- Supports captcha bypass and login flows
- Asynchronous API built on `asyncio`
- Screenshot capture and DOM interaction helpers
- Optional developer mode with a Chrome debugger

## Basic Usage

The tools are available through the `ToolManager` once Penguin is running:

```python
from penguin.tools import ToolManager

async def use_browser():
    tm = ToolManager()
    await tm.execute_tool("pydoll_browser_navigate", {"url": "https://example.com"})
    await tm.execute_tool(
        "pydoll_browser_interact",
        {"action": "click", "selector": "#submit", "selector_type": "css"},
    )
    screenshot = await tm.execute_tool("pydoll_browser_screenshot", {})
```

Developer mode exposes a lower‑level Chrome debugger for advanced automation. See the source under `penguin/tools/notes/chrome_debugger` for examples.
