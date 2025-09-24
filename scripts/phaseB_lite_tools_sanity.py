"""
Phase B – Lite Tools Sanity

Calls local grep and (best-effort) web search. Web search may fail under
restricted network; treat an error payload as acceptable.

Run: python scripts/phaseB_lite_tools_sanity.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from penguin.api_client import PenguinClient


async def main() -> None:
    async with PenguinClient() as client:
        core = client.core
        tm = core.tool_manager

        # Local grep
        res_grep = tm.execute_tool("grep_search", {"pattern": "class ConversationManager"})
        print("[grep result type]", type(res_grep).__name__)

        # Web search (may error when offline or when API key missing)
        res_web = tm.execute_tool(
            "perplexity_search", {"query": "python asyncio best practices", "max_results": 2}
        )
        try:
            import json
            preview = (
                json.dumps(res_web) if isinstance(res_web, (dict, list)) else str(res_web)
            )
            print("[web result]", preview[:120])
        except Exception as e:
            print("[web result] error while formatting:", e)


if __name__ == "__main__":
    asyncio.run(main())
