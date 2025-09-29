"""PyDoll click reliability matrix on Wikipedia Penguin page (no pytest).

This script runs a small matrix of selectors and click attempts to gauge
robustness of the interaction tool across different locator strategies.

Run:
    python penguin/scripts/pydoll_wiki_click_matrix.py

It prints a JSON report with outcomes per selector, including retries
already handled within the interaction tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure project root is importable when running from scripts/
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from penguin.tools.pydoll_tools import (  # noqa: E402
    pydoll_browser_manager,
    PyDollBrowserNavigationTool,
    PyDollBrowserInteractionTool,
    PyDollBrowserScrollTool,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


TEST_URL = "https://en.wikipedia.org/wiki/Penguin"


SELECTORS: List[Tuple[str, str, str]] = [
    # (label, selector, type)
    ("toc_references_css", "#toc a[href='#References']", "css"),
    ("references_css", "a[href='#References']", "css"),
    ("first_toc_css", "#toc li a", "css"),
    ("search_box_css", "input[name='search']", "css"),
    # ID/class (common on enwiki layout wrappers; may not be clickable)
    ("content_id", "content", "id"),
    ("vector_body_class", "vector-body", "class_name"),
    # XPath (best-effort; may be brittle across edits)
    ("first_link_xpath", "(//a)[10]", "xpath"),
]


async def run_matrix() -> Dict[str, Any]:
    nav = PyDollBrowserNavigationTool()
    interact = PyDollBrowserInteractionTool()
    scroll = PyDollBrowserScrollTool()

    report: Dict[str, Any] = {"url": TEST_URL, "results": []}

    report["navigate"] = await nav.execute(TEST_URL)
    await asyncio.sleep(0.8)

    # Early-out if PyDoll is not installed
    if isinstance(report.get("navigate"), str) and "not installed" in report["navigate"].lower():
        return report

    # Ensure at top before testing
    await scroll.execute(mode="to", to="top")
    await asyncio.sleep(0.1)

    # Try small page-down to emulate normal browsing
    await scroll.execute(mode="page", to="down", repeat=1)

    for label, selector, sel_type in SELECTORS:
        # Scroll element into view where applicable (best-effort)
        if sel_type in ("css", "id", "class_name"):
            await scroll.execute(mode="element", selector=selector, selector_type=sel_type)
            await asyncio.sleep(0.1)
        res = await interact.execute("click", selector, sel_type)
        report["results"].append({
            "label": label,
            "selector": selector,
            "selector_type": sel_type,
            "result": res,
        })

    # Return to top at end
    await scroll.execute(mode="to", to="top")

    return report


def main() -> None:
    data = asyncio.run(run_matrix())
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()


