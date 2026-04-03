import asyncio
import time
from pathlib import Path

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.system.conversation_manager import ConversationManager
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.system.state import MessageCategory


@pytest.mark.asyncio
async def test_scoped_conversation_manager_isolates_concurrent_sessions(tmp_path):
    conversation_manager = ConversationManager(
        workspace_path=tmp_path,
        system_prompt="system prompt",
        auto_save_interval=0,
    )
    conversation_manager.create_new_conversation()

    engine = Engine(
        EngineSettings(streaming_default=False),
        conversation_manager,
        api_client=None,
        tool_manager=None,
        action_executor=None,
    )

    async def worker(session_id: str, text: str):
        context = ExecutionContext(
            session_id=session_id,
            conversation_id=session_id,
            request_id=session_id,
        )
        with execution_context_scope(context):
            scoped = engine.get_conversation_manager("default")
            assert scoped is not None
            scoped.conversation.prepare_conversation(text)
            await asyncio.sleep(0.05)
            assert scoped.get_current_session().id == session_id
            contents = [msg.content for msg in scoped.conversation.session.messages]
            assert text in contents
            return contents

    first_contents, second_contents = await asyncio.gather(
        worker("scope-a", "alpha"),
        worker("scope-b", "beta"),
    )

    assert "alpha" in first_contents
    assert "beta" not in first_contents
    assert "beta" in second_contents
    assert "alpha" not in second_contents


@pytest.mark.asyncio
async def test_live_conversation_load_does_not_flip_default_session(tmp_path):
    conversation_manager = ConversationManager(
        workspace_path=tmp_path,
        system_prompt="system prompt",
        auto_save_interval=0,
    )
    conversation_manager.create_new_conversation()

    engine = Engine(
        EngineSettings(streaming_default=False),
        conversation_manager,
        api_client=None,
        tool_manager=None,
        action_executor=None,
    )

    context = ExecutionContext(
        session_id="scope-c",
        conversation_id="scope-c",
        request_id="scope-c",
    )
    with execution_context_scope(context):
        scoped = engine.get_conversation_manager("default")
        assert scoped is not None
        scoped.conversation.prepare_conversation("gamma")
        scoped.save()

    active_session = conversation_manager.get_current_session()
    assert active_session is not None
    assert active_session.id != "scope-c"
