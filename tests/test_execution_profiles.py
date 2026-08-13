"""Regression coverage for per-turn lean execution profiles."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.execution_profiles import (
    CHAT_SYSTEM_CONTEXT,
    RESEARCH_SYSTEM_CONTEXT,
    RESEARCH_TOOL_NAMES,
    resolve_execution_profile,
    resolve_profile_tools_enabled,
)
from penguin.llm.api_client import APIClient
from penguin.llm.runtime import execute_pending_tool_calls
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)
from penguin.web.routes import MessageRequest, handle_chat_message


def test_chat_profile_never_enables_tools_even_when_requested() -> None:
    profile = resolve_execution_profile("chat")

    assert profile.tools_enabled is False
    assert profile.allowed_tool_names == ()
    assert profile.include_web_search is False
    assert resolve_profile_tools_enabled(profile, True) is False


def test_research_profile_is_read_only_and_keeps_web_search() -> None:
    profile = resolve_execution_profile("research")

    assert profile.tools_enabled is True
    assert profile.include_web_search is True
    assert set(profile.allowed_tool_names or ()) == set(RESEARCH_TOOL_NAMES)
    assert "write_file" not in (profile.allowed_tool_names or ())
    assert "execute_command" not in (profile.allowed_tool_names or ())


@pytest.mark.asyncio
async def test_profile_system_context_is_request_scoped_and_keeps_agent_full_prompt() -> (
    None
):
    """Chat/research must not mutate a shared client's prompt for agent peers."""

    full_system_prompt = "SYSTEM_PROMPT " * 2_000
    original_messages = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": "Give me a short answer."},
    ]
    api_client = object.__new__(APIClient)
    api_client.system_prompt = full_system_prompt

    async def prepare_for(profile: str) -> list[dict[str, Any]]:
        with execution_context_scope(ExecutionContext(execution_profile=profile)):
            # Exercise context-local behavior while another task can use the
            # same client object at the same time.
            await asyncio.sleep(0)
            return api_client._prepare_messages_with_system_prompt(original_messages)

    chat_payload, agent_payload, research_payload = await asyncio.gather(
        prepare_for("chat"),
        prepare_for("agent"),
        prepare_for("research"),
    )

    assert api_client.system_prompt == full_system_prompt
    assert original_messages[0]["content"] == full_system_prompt

    assert chat_payload[0] == {"role": "system", "content": CHAT_SYSTEM_CONTEXT}
    assert full_system_prompt not in [
        message.get("content") for message in chat_payload
    ]
    assert len(CHAT_SYSTEM_CONTEXT) * 20 < len(full_system_prompt)

    assert agent_payload[0] == {"role": "system", "content": full_system_prompt}
    assert research_payload[0] == {
        "role": "system",
        "content": RESEARCH_SYSTEM_CONTEXT,
    }
    assert full_system_prompt not in [
        message.get("content") for message in research_payload
    ]


@pytest.mark.asyncio
async def test_rest_route_forwards_chat_profile_as_a_no_tool_turn(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    class Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            execution_context = get_current_execution_context()
            captured["execution_profile"] = (
                execution_context.execution_profile if execution_context else None
            )
            return {"assistant_response": "ok", "action_results": []}

    response = await handle_chat_message(
        MessageRequest(
            text="Just answer directly",
            session_id="profile-session",
            execution_profile="chat",
            tools_enabled=True,
            include_reasoning=False,
            streaming=False,
        ),
        core=cast(Any, Core()),
    )

    assert response["response"] == "ok"
    assert captured["tools_enabled"] is False
    assert captured["allowed_tool_names"] == []
    assert captured["include_web_search"] is False
    assert captured["execution_profile"] == "chat"


@pytest.mark.asyncio
async def test_trace_distinguishes_rest_and_internal_streaming(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    captured: dict[str, Any] = {}
    caplog.set_level(logging.INFO)

    class Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"assistant_response": "ok", "action_results": []}

    await handle_chat_message(
        MessageRequest(
            text="Explain the mode",
            session_id="streaming-trace-session",
            execution_profile="chat",
            include_reasoning=True,
            streaming=False,
        ),
        core=cast(Any, Core()),
    )

    assert captured["streaming"] is True
    assert "request_streaming=False" in caplog.text
    assert "effective_streaming=True" in caplog.text
    assert "forced_for_reasoning=True" in caplog.text


def test_research_schema_forwards_only_the_curated_tool_names() -> None:
    model_config = SimpleNamespace(
        provider="openai",
        client_preference="native",
        use_responses_api=False,
        interrupt_on_tool_call=False,
    )
    captured: dict[str, Any] = {}

    def get_responses_tools(
        *,
        allowed_names: list[str] | None = None,
        include_web_search: bool = True,
    ) -> list[dict[str, Any]]:
        captured["allowed_names"] = allowed_names
        captured["include_web_search"] = include_web_search
        return [{"type": "function", "name": "read_file"}]

    engine_like = SimpleNamespace(
        _get_runtime_model_config=lambda: model_config,
    )
    profile = resolve_execution_profile("research")

    extra_kwargs = Engine._prepare_responses_tools(
        engine_like,
        SimpleNamespace(get_responses_tools=get_responses_tools),
        allowed_names=profile.allowed_tool_names,
        include_web_search=profile.include_web_search,
    )

    assert captured == {
        "allowed_names": list(RESEARCH_TOOL_NAMES),
        "include_web_search": True,
    }
    assert extra_kwargs["tools"][0]["name"] == "read_file"


@pytest.mark.asyncio
async def test_chat_llm_step_skips_schemas_and_all_tool_execution() -> None:
    session = SimpleNamespace(messages=[])
    conversation = SimpleNamespace(
        get_formatted_messages=MagicMock(
            return_value=[{"role": "user", "content": "hello"}]
        ),
        session=session,
        add_assistant_message=MagicMock(),
    )
    conversation_manager = SimpleNamespace(
        conversation=conversation,
        core=None,
        get_current_session=lambda: session,
    )
    api_client = SimpleNamespace(client_handler=SimpleNamespace())
    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        cast(Any, api_client),
        MagicMock(),
        MagicMock(),
    )
    engine._prepare_responses_tools = MagicMock(  # type: ignore[method-assign]
        side_effect=AssertionError("chat must not prepare native tool schemas")
    )
    engine._handle_responses_tool_calls = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("chat must not execute provider tool calls")
    )
    engine._execute_codeact_actions = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("chat must not execute ActionXML")
    )
    engine._call_llm_with_retry = AsyncMock(  # type: ignore[method-assign]
        return_value="Hello from a lean turn."
    )
    engine._finalize_streaming_response = AsyncMock(  # type: ignore[method-assign]
        return_value="Hello from a lean turn."
    )
    engine._extract_usage_from_api_client = MagicMock(  # type: ignore[method-assign]
        return_value={}
    )

    result = await engine._llm_step(tools_enabled=False, streaming=False)

    assert result["assistant_response"] == "Hello from a lean turn."
    assert result["action_results"] == []
    assert engine._call_llm_with_retry.await_args.args[-1] == {}
    engine._prepare_responses_tools.assert_not_called()
    engine._handle_responses_tool_calls.assert_not_awaited()
    engine._execute_codeact_actions.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_profile_drops_unadvertised_provider_tool_calls() -> None:
    class Handler:
        def get_and_clear_pending_tool_calls(self) -> list[dict[str, str]]:
            return [
                {
                    "name": "write_file",
                    "arguments": '{"path":"unsafe.txt","content":"no"}',
                    "call_id": "call-write",
                }
            ]

    execute_tool = MagicMock(side_effect=AssertionError("must not execute"))
    result = await execute_pending_tool_calls(
        api_client=SimpleNamespace(
            client_handler=Handler(),
            model_config=SimpleNamespace(provider="openai", model="gpt-test"),
        ),
        tool_manager=SimpleNamespace(execute_tool=execute_tool),
        persist_action_result=lambda *_args: None,
        allowed_tool_names=RESEARCH_TOOL_NAMES,
    )

    assert result == []
    execute_tool.assert_not_called()


@pytest.mark.asyncio
async def test_chat_profile_does_not_queue_malformed_action_repair_turn() -> None:
    session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=session,
        prepare_conversation=MagicMock(),
        add_message=MagicMock(),
        save=MagicMock(return_value=True),
    )
    conversation_manager = SimpleNamespace(
        core=None,
        conversation=conversation,
        get_agent_conversation=lambda *args, **kwargs: conversation,
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=session),
        agent_context_windows={},
    )
    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "assistant_response": '<read_file path="notes.md">',
            "action_results": [],
            "usage": {},
        }
    )
    engine._save_conversation = AsyncMock()  # type: ignore[method-assign]

    result = await engine.run_response(
        "answer directly",
        streaming=False,
        tools_enabled=False,
    )

    assert result["iterations"] == 1
    assert result["assistant_response"] == '<read_file path="notes.md">'
    conversation.add_message.assert_not_called()
