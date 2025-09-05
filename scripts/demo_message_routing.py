#!/usr/bin/env python3
import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main():
    ws = Path.cwd() / "_tmp_workspace_routing"
    ws.mkdir(parents=True, exist_ok=True)
    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    # Register a child agent and send messages
    core.register_agent("child_alpha", system_prompt="You are a helpful child agent.")

    # Send directed message to agent
    await core.send_to_agent("child_alpha", "Hello from parent via MessageBus")

    # Send status to human
    await core.send_to_human("Parent has contacted child_alpha", message_type="status")

    # Simulate a human reply back to the agent
    await core.human_reply("child_alpha", "Hi child_alpha, please summarize context.")

    print("Demo complete. Check workspace at:", ws)


if __name__ == "__main__":
    asyncio.run(main())

