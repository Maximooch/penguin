from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.core import PenguinCore
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory


class StubConversation:
    def __init__(self) -> None:
        self.prepared: List[Any] = []

    def prepare_conversation(self, message: str, image_path: Optional[str] = None) -> None:
        self.prepared.append((message, image_path))


class StubConversationManager:
    def __init__(self) -> None:
        self.current_agent_id = "default"
        self.loaded: List[tuple[str, str]] = []
        self.loaded_files: List[tuple[str, str]] = []
        self.saved = False
        self.conversation = StubConversation()

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


class StubEngine:
    def __init__(self, conversation_manager: StubConversationManager) -> None:
        self._conversation_manager = conversation_manager
        self.run_single_turn = AsyncMock(return_value={
            "assistant_response": "stub-response",
            "action_results": []
        })
        self.run_response = AsyncMock()
        self.run_task = AsyncMock()
        self.requested_agent: Optional[str] = None

    def get_conversation_manager(self, agent_id: Optional[str] = None) -> StubConversationManager:
        self.requested_agent = agent_id
        return self._conversation_manager


def _build_core_with_stubs(cm: StubConversationManager, engine: StubEngine) -> PenguinCore:
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = cm
    core.engine = engine
    core.emit_ui_event = AsyncMock()

    async def _noop_stream(*args: Any, **kwargs: Any) -> None:
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


def test_sub_agent_clamp_and_partial_share_once(tmp_path):
    cm = ConversationManager(workspace_path=tmp_path)
    parent_id = "default"
    cm.add_context("Parent shared context")
    parent_cw = cm.agent_context_windows[parent_id]

    cm.create_sub_agent("child", parent_agent_id=parent_id, shared_cw_max_tokens=512)

    child_cw = cm.agent_context_windows["child"]
    assert child_cw.max_tokens == min(parent_cw.max_tokens, 512)

    parent_conv = cm.get_agent_conversation(parent_id)
    clamp_notes = [
        msg for msg in parent_conv.session.messages
        if (msg.metadata or {}).get("type") == "cw_clamp_notice"
    ]
    assert clamp_notes, "parent should receive clamp notice"

    child_conv = cm.get_agent_conversation("child")
    child_context_messages = [
        msg.content for msg in child_conv.session.messages
        if msg.category == MessageCategory.CONTEXT
    ]
    assert "Parent shared context" in child_context_messages

    cm.set_current_agent(parent_id)
    cm.add_context("New parent context post-clone")
    child_context_after = [
        msg.content for msg in child_conv.session.messages
        if msg.category == MessageCategory.CONTEXT
    ]
    assert "New parent context post-clone" not in child_context_after


@pytest.mark.asyncio
async def test_core_process_routes_agent_context():
    stub_cm = StubConversationManager()
    engine = StubEngine(stub_cm)
    core = _build_core_with_stubs(stub_cm, engine)

    result = await core.process(
        input_data={"text": "Ping"},
        conversation_id="conv-123",
        agent_id="planner",
        context_files=["notes.md"],
        streaming=False,
        multi_step=False,
    )

    assert result == engine.run_single_turn.return_value
    assert engine.run_single_turn.await_args.kwargs["agent_id"] == "planner"
    assert stub_cm.current_agent_id == "planner"
    assert stub_cm.loaded == [("planner", "conv-123")]
    assert stub_cm.loaded_files == [("planner", "notes.md")]
    assert stub_cm.saved is True

    message_calls = [call for call in core.emit_ui_event.call_args_list if call.args[0] == "message"]
    assert message_calls, "expected message events to be emitted"
    assert any(call.args[1].get("agent_id") == "planner" for call in message_calls)


def test_guarded_delete_warns_on_shared_session(tmp_path):
    cm = ConversationManager(workspace_path=tmp_path)
    shared_conv = cm.agent_sessions["default"]
    cm.agent_sessions["legacy"] = shared_conv
    cm.agent_session_managers["legacy"] = cm.agent_session_managers["default"]
    cm.agent_checkpoint_managers["legacy"] = cm.agent_checkpoint_managers.get("default")
    cm.agent_context_windows["legacy"] = cm.agent_context_windows["default"]

    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = cm

    delete_mock = MagicMock(return_value=True)
    cm.delete_agent_conversation = delete_mock  # type: ignore[assignment]

    result = core.delete_agent_conversation_guarded("legacy", shared_conv.session.id)

    assert result["success"] is False
    assert "legacy" in (result["warning"] or "")
    delete_mock.assert_not_called()
