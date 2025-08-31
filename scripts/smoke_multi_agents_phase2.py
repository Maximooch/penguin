#!/usr/bin/env python3
import asyncio
from pathlib import Path

from penguin.core import PenguinCore
from penguin.system.state import MessageCategory


async def main():
    workspace = Path.cwd() / "_tmp_workspace_phase2"
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"Using workspace: {workspace}")

    core = await PenguinCore.create(workspace_path=str(workspace), enable_cli=False, fast_startup=True)
    cm = core.conversation_manager

    parent_id = cm.current_agent_id
    parent_conv = cm.get_agent_conversation(parent_id)
    parent_conv.add_message("system", "Parent system note", category=MessageCategory.SYSTEM)
    parent_conv.add_message("system", "Project docs loaded", category=MessageCategory.CONTEXT)

    # Create isolated sub-agent and clamp to smaller model
    child_id = "child_agent"
    core.register_agent(child_id, share_session_with=parent_id, model_max_tokens=168_000)

    snap = core.smoke_check_agents()
    print("Smoke snapshot:")
    print(snap)

    child_conv = cm.get_agent_conversation(child_id)
    cats = [m.category.name for m in child_conv.session.messages]
    print("Child categories:", cats)

    parent_cw = cm.agent_context_windows[parent_id]
    child_cw = cm.agent_context_windows[child_id]
    print("Parent CWM max:", getattr(parent_cw, "max_tokens", None))
    print("Child CWM max: ", getattr(child_cw, "max_tokens", None))

    # Trigger a checkpoint and wait briefly
    child_conv.add_message("system", "Trigger checkpoint", category=MessageCategory.SYSTEM)
    await asyncio.sleep(0.1)

    cp_index = Path(cm.workspace_path) / "checkpoints" / "checkpoint_index.json"
    print("Checkpoint index exists:", cp_index.exists())


if __name__ == "__main__":
    asyncio.run(main())

