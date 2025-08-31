import asyncio
import os
from pathlib import Path

import pytest

from penguin.core import PenguinCore
from penguin.system.state import MessageCategory


@pytest.mark.asyncio
async def test_agent_isolation_and_partial_share(tmp_path: Path):
    # Use a temporary workspace inside the test path
    workspace = tmp_path / "penguin_workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(workspace), enable_cli=False, fast_startup=True)

    # Parent agent: ensure some SYSTEM + CONTEXT content exists
    cm = core.conversation_manager
    parent_id = cm.current_agent_id  # default
    parent_conv = cm.get_agent_conversation(parent_id)
    # Add a SYSTEM note and a CONTEXT entry
    parent_conv.add_message("system", "Parent system note", category=MessageCategory.SYSTEM)
    parent_conv.add_message("system", "Project docs loaded", category=MessageCategory.CONTEXT)

    # Register an isolated sub-agent with lower model limit
    child_id = "child_agent"
    await asyncio.sleep(0)  # ensure event loop ready
    core.register_agent(child_id, share_session_with=parent_id, model_max_tokens=168_000)

    # Check smoke snapshot
    snap = core.smoke_check_agents()
    agent_ids = {a["agent_id"] for a in snap["agents"]}
    assert child_id in agent_ids

    # Verify child conversation contains copied SYSTEM + CONTEXT but no DIALOG
    child_conv = cm.get_agent_conversation(child_id)
    cats = [m.category for m in child_conv.session.messages]
    assert MessageCategory.SYSTEM in cats
    assert MessageCategory.CONTEXT in cats
    assert MessageCategory.DIALOG not in cats

    # Verify child CWM max <= parent CWM max
    parent_cw = cm.agent_context_windows[parent_id]
    child_cw = cm.agent_context_windows[child_id]
    assert child_cw.max_tokens <= parent_cw.max_tokens


@pytest.mark.asyncio
async def test_checkpoints_and_autosave(tmp_path: Path):
    workspace = tmp_path / "penguin_workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(workspace), enable_cli=False, fast_startup=True)
    cm = core.conversation_manager

    # Add a message to trigger checkpoint logic (frequency=1 by default)
    conv = cm.get_agent_conversation(cm.current_agent_id)
    conv.add_message("system", "Trigger checkpoint", category=MessageCategory.SYSTEM)

    # Allow background workers to process checkpoint request
    await asyncio.sleep(0.1)

    # Verify checkpoint index exists (best effort)
    cp_root = Path(cm.workspace_path) / "checkpoints"
    index_path = cp_root / "checkpoint_index.json"
    assert index_path.exists(), "Checkpoint index not found; checkpoint worker may have failed to initialize."

    # Autosave thread should be running for the session manager
    sm = cm.session_manager
    assert hasattr(sm, "_auto_save_thread"), "Autosave thread not initialized"
    assert getattr(sm, "_auto_save_thread").is_alive(), "Autosave thread is not running"

