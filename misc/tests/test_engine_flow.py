import asyncio
import pytest # type: ignore

from penguin.core import PenguinCore

@pytest.mark.asyncio
async def test_engine_single_turn(monkeypatch):
    core = await PenguinCore.create()
    core.reset_context() # Ensure a clean conversation state
    
    # stub the LLM call
    async def fake_response(*args, **kwargs):
        return "Hello from stub LLM!"
    monkeypatch.setattr(core.api_client, "get_response", fake_response)

    result = await core.process("Hi Engine!")
    assert "assistant_response" in result
    assert result["assistant_response"] == "Hello from stub LLM!"
    # ensure Engine path (no 'action_results' key if stubbed)
    assert result.get("action_results") == []

    # conversation should have 3 messages (system + user + assistant)
    msgs = core.conversation_manager.conversation.session.messages
    assert len(msgs) == 3
    assert msgs[0].role == "system" # Optional: Verify system prompt exists
    assert msgs[1].role == "user"
    assert msgs[1].content == "Hi Engine!"
    assert msgs[-1].content == "Hello from stub LLM!"

@pytest.mark.asyncio
async def test_runmode_delegates(monkeypatch):
    core = await PenguinCore.create()
    # stub LLM
    async def fake_response(*a, **k):
        return "TASK_COMPLETED"
    monkeypatch.setattr(core.api_client, "get_response", fake_response)

    run_mode = core.run_mode = None  # ensure fresh RunMode
    from penguin.run_mode import RunMode
    run_mode = RunMode(core, max_iterations=2)
    await run_mode._execute_task("demo", "just finish")

    # last assistant message must be TASK_COMPLETED
    msgs = core.conversation_manager.conversation.session.messages
    assert "TASK_COMPLETED" in msgs[-1].content