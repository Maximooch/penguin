"""Phase 0 validation script for Penguin multi-agent plumbing.

This module mirrors the smoke tests in ``tests/test_multi_agent_smoke.py`` but
is runnable as a standalone Python script (ideal for ``uv run`` workflows).
It exercises:

* Per-agent conversation routing through ``PenguinCore.process``
* Context file loading scoped to the requested agent
* MessageBus routing via ``core.send_to_agent``

No real engine/model startup occurs – we patch in lightweight stubs so the
script can run quickly in constrained environments.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from penguin.core import PenguinCore
from penguin.system.message_bus import MessageBus, ProtocolMessage
from penguin.system.state import MessageCategory


# ---------------------------------------------------------------------------
# Stub Conversation / Engine implementations (borrowed from test suite)
# ---------------------------------------------------------------------------


class StubConversation:
    def __init__(self) -> None:
        self.prepared: List[Any] = []
        self.session = StubSession()

    def prepare_conversation(self, message: str, image_path: Optional[str] = None) -> None:
        self.prepared.append((message, image_path))


@dataclass
class StubSession:
    id: str = "session-default"
    messages: List[Any] = field(default_factory=list)


class StubConversationManager:
    def __init__(self) -> None:
        self.current_agent_id = "default"
        self.loaded: List[tuple[str, str]] = []
        self.loaded_files: List[tuple[str, str]] = []
        self.saved = False
        self.conversation = StubConversation()

    # API surface that PenguinCore.process touches
    def set_current_agent(self, agent_id: str) -> None:
        self.current_agent_id = agent_id

    def load(self, conversation_id: str) -> bool:
        self.loaded.append((self.current_agent_id, conversation_id))
        return True

    def load_context_file(self, path: str) -> None:
        self.loaded_files.append((self.current_agent_id, path))

    def save(self) -> None:
        self.saved = True

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        return {"total": {"input": 0, "output": 0}, "session": {"input": 0, "output": 0}}

    # Minimal hooks so MessageBus fallback path can emit messages
    def add_system_note(self, agent_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.conversation.session.messages.append(
            StubMessage(
                role="system",
                content=content,
                category=MessageCategory.SYSTEM,
                metadata=metadata or {},
                agent_id=agent_id,
            )
        )


@dataclass
class StubMessage:
    role: str
    content: Any
    category: MessageCategory
    metadata: Dict[str, Any]
    agent_id: Optional[str]


class StubEngine:
    def __init__(self, conversation_manager: StubConversationManager) -> None:
        self._conversation_manager = conversation_manager
        self.run_single_turn = AsyncMock(
            return_value={
                "assistant_response": "stub-response",
                "action_results": [],
            }
        )

    def get_conversation_manager(self, agent_id: Optional[str] = None) -> StubConversationManager:
        # PenguinCore expects this method when agent_id is supplied
        if agent_id:
            self._conversation_manager.set_current_agent(agent_id)
        return self._conversation_manager


def _build_core_with_stubs(cm: StubConversationManager, engine: StubEngine) -> PenguinCore:
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = cm
    core.engine = engine
    core.emit_ui_event = AsyncMock()

    async def _noop_stream(*_: Any, **__: Any) -> None:
        return None

    core._handle_stream_chunk = _noop_stream  # type: ignore[attr-defined]
    # Mock StreamingStateManager for streaming property accessors
    from unittest.mock import MagicMock
    core._stream_manager = MagicMock()
    core._stream_manager.is_active = False
    core._stream_manager.content = ""
    core._stream_manager.reasoning_content = ""
    core._stream_manager.stream_id = None
    core.event_types = {"message", "token_update", "error"}
    core._interrupted = False
    return core


# ---------------------------------------------------------------------------
# Validation routines
# ---------------------------------------------------------------------------


async def validate_process_routing() -> None:
    cm = StubConversationManager()
    engine = StubEngine(cm)
    core = _build_core_with_stubs(cm, engine)

    result = await core.process(
        input_data={"text": "Ping"},
        conversation_id="conv-123",
        agent_id="planner",
        context_files=["notes.md"],
        streaming=False,
        multi_step=False,
    )

    assert result == engine.run_single_turn.return_value
    assert cm.current_agent_id == "planner"
    assert cm.loaded == [("planner", "conv-123")]
    assert cm.loaded_files == [("planner", "notes.md")]
    assert cm.saved is True

    print("process() routing ✔ – agent scoped conversation + context files")


async def validate_message_bus() -> None:
    cm = StubConversationManager()
    engine = StubEngine(cm)
    core = _build_core_with_stubs(cm, engine)

    captured: List[ProtocolMessage] = []

    async def handler(msg: ProtocolMessage) -> None:
        captured.append(msg)

    bus = MessageBus.get_instance()
    bus.register_handler("worker", handler)

    ok = await core.send_to_agent("worker", {"hello": "world"}, message_type="status")
    assert ok is True

    # Allow event loop to flush handler
    await asyncio.sleep(0)

    assert captured, "Expected bus handler invocation"
    msg = captured[0]
    assert msg.recipient == "worker"
    assert msg.content == {"hello": "world"}
    assert msg.message_type == "status"

    print("MessageBus routing ✔ – core.send_to_agent reached handler")


async def main() -> None:
    print("Running Phase 0 multi-agent validation…")
    await validate_process_routing()
    await validate_message_bus()
    print("Phase 0 validation complete.")


if __name__ == "__main__":
    asyncio.run(main())
