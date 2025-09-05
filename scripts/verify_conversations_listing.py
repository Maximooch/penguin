#!/usr/bin/env python3
"""Smoke check: list_all_conversations includes agent_id and session ids.

Creates multiple agents and conversations, then inspects
core.list_all_conversations() for expected fields.

Usage:
  python -m penguin.scripts.verify_conversations_listing
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_conversations"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    # Ensure some agents and conversations exist
    core.register_agent("lister1")
    core.register_agent("lister2")
    core.create_agent_conversation("lister1")
    core.create_agent_conversation("lister2")

    all_convs = core.list_all_conversations()
    has_agent_ids = all(isinstance(item.get("agent_id"), str) and item.get("agent_id") for item in all_convs)
    has_session_ids = all(isinstance(item.get("id"), str) and item.get("id") for item in all_convs)

    print("--- verify_conversations_listing results ---")
    print(f"Workspace: {ws}")
    print(f"conversations: {len(all_convs)} items")
    print(f"all have agent_id: {has_agent_ids}")
    print(f"all have id: {has_session_ids}")
    ok = bool(all_convs) and has_agent_ids and has_session_ids
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

