"""PenguinAgent – high-level convenience wrapper

This module provides a tiny *ergonomic* façade on top of PenguinCore so that
end-users can get started with one or two lines of code without having to deal
with `asyncio`, builders, or the full Core/Engine vocabulary.

Example (sync):
    from penguin import PenguinAgent

    agent = PenguinAgent()
    print(agent.chat("Hello Penguin!"))

Example (async):
    from penguin.agent import PenguinAgentAsync

    agent = await PenguinAgentAsync.create()
    await agent.chat("Hi async world")

The wrapper is intentionally thin: it defers *all* heavy lifting to the
existing `PenguinCore` + `Engine` stack.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from penguin.core import PenguinCore

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_sync(coro):
    """Run *coro* in a fresh event-loop or the current running loop if inside
    another async context.  This mirrors Trio's *blocking portal* pattern and
    avoids *RuntimeError: This event loop is already running* when the caller
    happens to be inside a notebook or FastAPI handler.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:  # already inside a running loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return loop.create_task(coro)  # type: ignore[return-value]
        else:
            return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Sync wrapper
# ---------------------------------------------------------------------------

class PenguinAgent:  # pylint: disable=too-few-public-methods
    """Blocking convenience API.

    Parameters mirror `PenguinCore.create` but are optional – sensible defaults
    are read from *config.yml* if omitted.
    """

    # NOTE: keep signature minimal; advanced users can switch to the async
    # class or the builder for full control.
    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> None:
        self._core: PenguinCore = _run_sync(
            PenguinCore.create(
                model=model,
                provider=provider,
                workspace_path=workspace,
                enable_cli=False,
            )
        )

    # ------------------------------------------------------------------
    # Public helper methods (blocking)
    # ------------------------------------------------------------------

    def chat(self, message: str, *, streaming: bool = False) -> str:
        """Single-turn chat – returns full assistant response."""
        async def _chat_async() -> str:
            # NOTE: `streaming` flag passed to run_single_turn for provider hints
            # but the full response is awaited and returned. For a streaming
            # response, use the `.stream()` method.
            response_data = await self._core.engine.run_single_turn(
                prompt=message,
                streaming=streaming,
            )
            return response_data.get("assistant_response", "")

        return _run_sync(_chat_async())

    def stream(self, message: str) -> Generator[str, None, None]:
        """Yield chunks **synchronously** for immediate printing."""
        agen = self._core.engine.stream(prompt=message)

        while True:
            try:
                chunk = _run_sync(agen.__anext__())
                yield chunk
            except StopAsyncIteration:
                break

    def run_task(self, prompt: str, *, max_iterations: int = 5) -> Dict[str, Any]:
        """Multi-step reasoning using Engine.run_task (blocking)."""
        return _run_sync(self._core.engine.run_task(prompt, max_iterations=max_iterations))

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def checkpoint(self, name: Optional[str] = None, description: Optional[str] = None) -> str:
        return _run_sync(self._core.create_checkpoint(name=name, description=description)) or ""

    # Add more thin wrappers as needed...

    # ------------------------------------------------------------------
    # Conversation helpers
    # ------------------------------------------------------------------
    def new_conversation(self) -> str:
        return _run_sync(self._core.create_conversation())
    
    def list_conversations(self, *, limit: int = 20, offset: int = 0):
        return self._core.list_conversations(limit=limit, offset=offset)

    def load_conversation(self, conversation_id: str) -> bool:
        return _run_sync(self._core.conversation_manager.load(conversation_id))  # type: ignore[attr-defined]

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._core.delete_conversation(conversation_id)

    def conversation_stats(self):
        return self._core.get_conversation_stats()

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------
    def list_checkpoints(self, session_id: Optional[str] = None, limit: int = 50):
        return self._core.list_checkpoints(session_id=session_id, limit=limit)

    def rollback(self, checkpoint_id: str) -> bool:
        return _run_sync(self._core.rollback_to_checkpoint(checkpoint_id))

    def branch(self, checkpoint_id: str, *, name: Optional[str] = None, description: Optional[str] = None):
        return _run_sync(self._core.branch_from_checkpoint(checkpoint_id, name=name, description=description))

    # ------------------------------------------------------------------
    # Model helpers
    # ------------------------------------------------------------------
    def list_models(self):
        return self._core.list_available_models()

    def switch_model(self, model_id: str) -> bool:
        return _run_sync(self._core.load_model(model_id))

    def current_model(self):
        mc = self._core.model_config
        if not mc:
            return None
        return {
            "model": mc.model,
            "provider": mc.provider,
            "client_preference": mc.client_preference,
            "max_tokens": mc.max_tokens,
        }

    # ------------------------------------------------------------------
    # Tools & context helpers
    # ------------------------------------------------------------------
    def list_tools(self):
        return [tool.get("name") for tool in getattr(self._core.tool_manager, "tools", [])]

    def run_tool(self, tool_name: str, tool_input: dict):
        return self._core.tool_manager.execute_tool(tool_name, tool_input)

    def list_context_files(self):
        return self._core.list_context_files()

    def attach_context_file(self, file_path: str) -> bool:
        return _run_sync(self._core.conversation_manager.load_context_file(file_path))  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def token_usage(self):
        return self._core.get_token_usage()


# ---------------------------------------------------------------------------
# Async class – thin pass-through
# ---------------------------------------------------------------------------

class PenguinAgentAsync:
    """Full-async wrapper for advanced users / servers."""

    def __init__(self, core: PenguinCore):
        self._core = core

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------
    @classmethod
    async def create(
        cls,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> "PenguinAgentAsync":
        core = await PenguinCore.create(
            model=model,
            provider=provider,
            workspace_path=workspace,
            enable_cli=False,
        )
        return cls(core)

    # ------------------------------------------------------------------
    # Public async methods mirror the sync API (chat / stream / run_task)
    # ------------------------------------------------------------------

    async def chat(self, message: str, *, streaming: bool = False) -> str:
        """Single-turn chat – returns full assistant response."""
        # NOTE: `streaming` flag passed for provider hints, but the full
        # response is awaited and returned. For a streaming response,
        # use the `.stream()` method.
        response_data = await self._core.engine.run_single_turn(
            prompt=message,
            streaming=streaming,
        )
        return response_data.get("assistant_response", "")

    async def stream(self, message: str):  # -> AsyncGenerator[str, None]
        async for chunk in self._core.engine.stream(prompt=message):
            yield chunk

    async def run_task(self, prompt: str, *, max_iterations: int = 5):
        return await self._core.engine.run_task(prompt, max_iterations=max_iterations)

    async def checkpoint(self, name: Optional[str] = None, description: Optional[str] = None):
        return await self._core.create_checkpoint(name=name, description=description)

    # ------------------------------------------------------------------
    # Conversation helpers (async)
    # ------------------------------------------------------------------
    async def new_conversation(self) -> str:
        return await self._core.create_conversation()

    async def list_conversations(self, *, limit: int = 20, offset: int = 0):
        return self._core.list_conversations(limit=limit, offset=offset)

    async def load_conversation(self, conversation_id: str) -> bool:
        return await self._core.conversation_manager.load(conversation_id)  # type: ignore[attr-defined]

    async def delete_conversation(self, conversation_id: str) -> bool:
        return self._core.delete_conversation(conversation_id)

    async def conversation_stats(self):
        return self._core.get_conversation_stats()

    # ------------------------------------------------------------------
    # Checkpoint helpers (async)
    # ------------------------------------------------------------------
    async def list_checkpoints(self, session_id: Optional[str] = None, limit: int = 50):
        return self._core.list_checkpoints(session_id=session_id, limit=limit)

    async def rollback(self, checkpoint_id: str) -> bool:
        return await self._core.rollback_to_checkpoint(checkpoint_id)

    async def branch(self, checkpoint_id: str, *, name: Optional[str] = None, description: Optional[str] = None):
        return await self._core.branch_from_checkpoint(checkpoint_id, name=name, description=description)

    # ------------------------------------------------------------------
    # Model helpers (async)
    # ------------------------------------------------------------------
    async def list_models(self):
        return self._core.list_available_models()

    async def switch_model(self, model_id: str) -> bool:
        return await self._core.load_model(model_id)

    async def current_model(self):
        mc = self._core.model_config
        if not mc:
            return None
        return {
            "model": mc.model,
            "provider": mc.provider,
            "client_preference": mc.client_preference,
            "max_tokens": mc.max_tokens,
        }

    # ------------------------------------------------------------------
    # Tools & context helpers (async)
    # ------------------------------------------------------------------
    async def list_tools(self):
        return [tool.get("name") for tool in getattr(self._core.tool_manager, "tools", [])]

    async def run_tool(self, tool_name: str, tool_input: dict):
        # ToolManager.execute_tool is sync – run in default loop executor
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._core.tool_manager.execute_tool, tool_name, tool_input)

    async def list_context_files(self):
        return self._core.list_context_files()

    async def attach_context_file(self, file_path: str) -> bool:
        return await self._core.conversation_manager.load_context_file(file_path)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Diagnostics (async)
    # ------------------------------------------------------------------
    async def token_usage(self):
        return self._core.get_token_usage() 

__all__ = [
     "PenguinAgent",
     "PenguinAgentAsync",
     "AgentConfig",
     "BaseAgent",
     "AgentLauncher",
     # Core re-exports added at top-level package, not here.
 ]

# Re-export advanced agent runtime symbols for convenience
from penguin.agent.schema import AgentConfig  # noqa: E402  (after sys.path tweaks)
from penguin.agent.base import BaseAgent  # noqa: E402
from penguin.agent.launcher import AgentLauncher  # noqa: E402 