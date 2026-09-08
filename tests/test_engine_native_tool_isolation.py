"""Exercise tool/prose isolation through the real Engine step and loops."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.llm.contracts import FinishReason, LLMRequestLifecycle
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Session

REVIEW = (
    "Review example only:\n"
    "- First response: `<execute_command>echo`\n"
    "- Continuation: `hello</execute_command>`"
)
NATIVE = SimpleNamespace(provider="openai", client_preference="native", model="gpt-5.4")
FALLBACK = SimpleNamespace(provider="local", client_preference="litellm")


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    session = Session()
    conversation = ConversationSystem(
        session_manager=SimpleNamespace(
            current_session=session,
            mark_session_modified=lambda _: None,
            check_session_boundary=lambda _: False,
        )
    )
    conversation.session = session
    cm = SimpleNamespace(
        conversation=conversation,
        get_current_session=lambda: session,
        save=lambda: True,
        add_action_result=conversation.add_action_result,
        core=None,
    )
    handler = SimpleNamespace(get_and_clear_last_tool_call=Mock(return_value=None))
    api = SimpleNamespace(model_config=NATIVE, client_handler=handler)
    tools = SimpleNamespace(
        execute_tool=Mock(return_value="hello"),
        get_responses_tools=Mock(
            return_value=[{"type": "function", "name": "execute_command"}]
        ),
    )
    executor = SimpleNamespace(execute_action=AsyncMock(return_value="hello"))
    engine = Engine(EngineSettings(streaming_default=False), cm, api, tools, executor)
    monkeypatch.setattr(engine, "_get_scoped_conversation_manager", lambda cm, _: cm)
    # Only provider I/O is replaced. Parsing, execution, persistence, and loop
    # completion remain real. Exhaustion fails instead of calling a live model.
    provider = AsyncMock(side_effect=[REVIEW])
    monkeypatch.setattr(engine, "_call_llm_with_retry", provider)
    return SimpleNamespace(
        engine=engine,
        api=api,
        handler=handler,
        tools=tools,
        executor=executor,
        provider=provider,
        conversation=conversation,
    )


async def run(runtime: SimpleNamespace, mode: str, **kwargs: Any) -> dict[str, Any]:
    if mode == "task":
        return await runtime.engine.run_task(
            "Review only", enable_events=False, **kwargs
        )
    return await runtime.engine.run_response("Review only", **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["response", "task"])
@pytest.mark.parametrize(
    "text",
    [REVIEW, "Example: `<execute_command>echo`", "Example: `</execute_command>`"],
)
async def test_native_prose_finishes_without_execution_or_repair(
    runtime: SimpleNamespace, mode: str, text: str
) -> None:
    runtime.provider.side_effect = [text]
    result = await run(runtime, mode)
    assert result["assistant_response"] == text
    assert result["status"] in {"completed", "implicit_completion"}
    assert result["action_results"] == []
    assert runtime.provider.await_count == 1
    runtime.executor.execute_action.assert_not_awaited()
    runtime.tools.execute_tool.assert_not_called()
    assert not any(
        m.metadata.get("type") == "malformed_action_output"
        for m in runtime.conversation.session.messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["response", "task"])
async def test_native_call_executes_once_then_final_review_finishes(
    runtime: SimpleNamespace, mode: str
) -> None:
    runtime.provider.side_effect = ["Checking now.", REVIEW]
    runtime.handler.get_and_clear_last_tool_call.side_effect = [
        {
            "call_id": "call-1",
            "name": "execute_command",
            "arguments": '{"command":"echo hello"}',
        },
        None,
    ]
    result = await run(runtime, mode)
    assert runtime.provider.await_count == 2
    runtime.tools.execute_tool.assert_called_once()
    runtime.executor.execute_action.assert_not_awaited()
    assert len(result["action_results"]) == 1
    assert result["assistant_response"] == REVIEW


@pytest.mark.asyncio
async def test_fallback_execution_is_unchanged(runtime: SimpleNamespace) -> None:
    runtime.api.model_config = FALLBACK
    runtime.provider.side_effect = [
        "<execute_command>echo hello</execute_command>",
        "Done.",
    ]
    result = await run(runtime, "response")
    runtime.executor.execute_action.assert_awaited_once()
    runtime.tools.execute_tool.assert_not_called()
    assert len(result["action_results"]) == 1
    assert runtime.provider.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [NATIVE, FALLBACK])
async def test_tools_disabled_neither_advertises_nor_executes(
    runtime: SimpleNamespace, config: SimpleNamespace
) -> None:
    runtime.api.model_config = config
    runtime.handler.get_and_clear_last_tool_call.return_value = {
        "call_id": "call-1",
        "name": "execute_command",
        "arguments": "{}",
    }
    result = await runtime.engine.run_single_turn("Review only", tools_enabled=False)
    assert result["action_results"] == []
    assert runtime.provider.call_args.args[4] == {}
    runtime.tools.execute_tool.assert_not_called()
    runtime.executor.execute_action.assert_not_awaited()
    runtime.tools.get_responses_tools.assert_not_called()


@pytest.mark.asyncio
async def test_run_model_override_controls_native_isolation(
    runtime: SimpleNamespace,
) -> None:
    runtime.api.model_config = FALLBACK
    result = await run(runtime, "response", model_config_override=NATIVE)
    assert result["action_results"] == []
    assert runtime.provider.await_count == 1
    runtime.executor.execute_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_failure_does_not_enable_text_execution(
    runtime: SimpleNamespace,
) -> None:
    runtime.tools.get_responses_tools.side_effect = ValueError("invalid schema")
    result = await run(runtime, "response")
    assert result["action_results"] == []
    assert runtime.provider.await_count == 1
    runtime.executor.execute_action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,preference", [("anthropic", "native"), ("openrouter", "openrouter")]
)
async def test_other_native_providers_keep_prose_inert(
    runtime: SimpleNamespace, provider: str, preference: str
) -> None:
    runtime.api.model_config = SimpleNamespace(
        provider=provider, client_preference=preference
    )
    result = await run(runtime, "response")
    assert result["action_results"] == []
    assert runtime.provider.await_count == 1
    runtime.executor.execute_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_provider_wins_over_engine_default(
    runtime: SimpleNamespace,
) -> None:
    runtime.engine.model_config = FALLBACK
    runtime.engine.register_agent(
        agent_id="reviewer",
        conversation_manager=runtime.engine.conversation_manager,
        api_client=runtime.api,
    )
    result = await run(runtime, "response", agent_id="reviewer")
    assert result["action_results"] == []
    assert runtime.provider.await_count == 1
    runtime.executor.execute_action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["response", "task"])
async def test_native_output_boundary_continues_and_sums_usage(
    runtime: SimpleNamespace, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime.provider.side_effect = ["Hello ", "world."]
    runtime.api.get_last_request_lifecycle = lambda: LLMRequestLifecycle(
        request_id="test-continuation",
        provider="openai",
        model="test",
        finish_reason=(
            FinishReason.LENGTH
            if runtime.provider.await_count == 1
            else FinishReason.STOP
        ),
    )
    monkeypatch.setattr(
        runtime.engine,
        "_extract_usage_from_api_client",
        lambda _: {"total_tokens": 13 if runtime.provider.await_count == 1 else 12},
    )
    result = await run(runtime, mode)
    assert result["assistant_response"] == "Hello world."
    assert runtime.provider.await_count == 2
    assert result["usage"]["total_tokens"] == 25
    runtime.executor.execute_action.assert_not_awaited()
    assert [
        m.content
        for m in runtime.conversation.session.messages
        if m.role == "assistant"
    ] == ["Hello ", "world."]
