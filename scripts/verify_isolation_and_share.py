#!/usr/bin/env python3
"""Smoke check: Agent isolation + partial SYSTEM/CONTEXT share on sub-agent creation.

Creates a child agent via core.register_agent(share_session_with=parent). The
ConversationManager enforces isolation but copies SYSTEM+CONTEXT messages once.
Verifies categories and CWM limits.

Usage:
  python -m penguin.scripts.verify_isolation_and_share
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore
from penguin.system.state import MessageCategory


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_isolation"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)
    cm = core.conversation_manager

    parent_id = cm.current_agent_id  # "default"
    parent_conv = cm.get_agent_conversation(parent_id)
    parent_conv.add_message("system", "Parent system note", category=MessageCategory.SYSTEM)
    parent_conv.add_message("system", "Project docs loaded", category=MessageCategory.CONTEXT)

    child_id = "child_agent"
    core.register_agent(child_id, share_session_with=parent_id, model_max_tokens=168_000)

    child_conv = cm.get_agent_conversation(child_id)
    cats = [m.category for m in child_conv.session.messages]

    parent_cw = cm.agent_context_windows[parent_id]
    child_cw = cm.agent_context_windows[child_id]

    print("--- verify_isolation_and_share results ---")
    print(f"Workspace: {ws}")
    print(f"Child has SYSTEM: {MessageCategory.SYSTEM in cats}")
    print(f"Child has CONTEXT: {MessageCategory.CONTEXT in cats}")
    print(f"Child has DIALOG: {MessageCategory.DIALOG in cats}")
    print(f"Child CWM <= Parent CWM: {child_cw.max_tokens <= parent_cw.max_tokens}")

    ok = (
        (MessageCategory.SYSTEM in cats)
        and (MessageCategory.CONTEXT in cats)
        and (MessageCategory.DIALOG not in cats)
        and (child_cw.max_tokens <= parent_cw.max_tokens)
    )
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

