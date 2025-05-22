# PyDoll Browser Tools

Penguin includes [PyDoll](https://github.com/pydoll) integration for browser automation. PyDoll connects directly to Chrome or other browsers via their DevTools protocol, so no separate WebDriver is required.

## Features

- Human‑like browsing that helps avoid detection
- Supports captcha bypass and login flows
- Asynchronous API built on `asyncio`
- Screenshot capture and DOM interaction helpers
- Optional developer mode with a Chrome debugger

## Basic Usage

Some examples of what Penguin would use. (these are from prompt_actions.py)

```XML
-   `<pydoll_browser_navigate>URL</pydoll_browser_navigate >`
-   `<pydoll_browser_interact>action:selector[:selector_type][:text]</pydoll_browser_interact >` (actions: `click`, `input`, `submit`, selector_types: `css`, `xpath`, `id`, `class_name`)
-   `<pydoll_browser_screenshot></pydoll_browser_screenshot >`
-   `<pydoll_debug_toggle>[on|off]</pydoll_debug_toggle >` (Enable/disable detailed PyDoll logging and outputs)
```

Developer mode exposes a lower‑level Chrome debugger for advanced automation. See the source under `penguin/tools/notes/chrome_debugger` for examples.
