#!/usr/bin/env python3
"""PyDoll Wikipedia smoke test (no pytest).

Run:
    uv run python penguin/scripts/pydoll_wiki_smoke.py
    # or
    python penguin/scripts/pydoll_wiki_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure project root is importable when running from scripts/
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from penguin.tools.pydoll_tools import (  # noqa: E402
    pydoll_browser_manager,
    PyDollBrowserNavigationTool,
    PyDollBrowserInteractionTool,
    PyDollBrowserScreenshotTool,
    PyDollBrowserScrollTool,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_smoke(url: str = "https://en.wikipedia.org/wiki/Penguin") -> Dict[str, Any]:
    nav = PyDollBrowserNavigationTool()
    interact = PyDollBrowserInteractionTool()
    scroll = PyDollBrowserScrollTool()
    snap = PyDollBrowserScreenshotTool()

    summary: Dict[str, Any] = {"steps": []}

    step = {"name": "navigate", "url": url}
    step["result"] = await nav.execute(url)
    summary["steps"].append(step)

    # If PyDoll missing or init failed, stop early
    if isinstance(step["result"], str) and ("failed" in step["result"].lower() or "not installed" in step["result"].lower()):
        return summary

    await asyncio.sleep(1.0)
    page = await pydoll_browser_manager.get_page()
    try:
        title = await asyncio.wait_for(page.get_title(), timeout=5.0) if page else None
        current_url = await asyncio.wait_for(page.get_url(), timeout=5.0) if page else None
    except Exception:
        title = None
        current_url = None

    shot1 = await snap.execute()
    summary["steps"].append({"name": "screenshot_initial", "title": title, "current_url": current_url, "screenshot": shot1})

    summary["steps"].append({"name": "scroll_to_bottom", "result": await scroll.execute(mode="to", to="bottom")})
    summary["steps"].append({"name": "screenshot_bottom", "screenshot": await snap.execute()})

    summary["steps"].append({"name": "scroll_to_top", "result": await scroll.execute(mode="to", to="top")})
    summary["steps"].append({"name": "screenshot_top", "screenshot": await snap.execute()})

    anchors = [("#Etymology", "css"), ("#Systematics_and_evolution", "css"), ("#Behaviour", "css"), ("#References", "css")]
    for sel, sel_type in anchors:
        summary["steps"].append({"name": "scroll_section", "selector": sel, "result": await scroll.execute(mode="element", selector=sel, selector_type=sel_type, behavior="smooth")})

    for sel, sel_type in [("#toc a[href='#References']", "css"), ("a[href='#References']", "css")]:
        res = await interact.execute("click", sel, sel_type)
        summary["steps"].append({"name": "click_best_effort", "selector": sel, "result": res})
        if isinstance(res, str) and "Successfully clicked" in res:
            break

    summary["steps"].append({"name": "screenshot_final", "screenshot": await snap.execute()})
    return summary


def main() -> None:
    data = asyncio.run(run_smoke())
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
