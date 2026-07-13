from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallResult,
    LLMError,
    LLMProviderError,
)
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Message, MessageCategory, Session


class _Conversation:
    def __init__(self) -> None:
        self.session = Session()

    def prepare_conversation(
        self,
        user_input: str,
        image_paths: list[str] | None = None,
        *,
        category: MessageCategory | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        del image_paths
        self.add_message(
            "user",
            user_input,
            category=category or MessageCategory.DIALOG,
            metadata=metadata,
        )

    def add_message(
        self,
        role: str,
        content: Any,
        category: MessageCategory = MessageCategory.DIALOG,
        metadata: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> Message:
        message = Message(
            role=role,
            content=content,
            category=category,
            metadata=metadata or {},
        )
        self.session.messages.append(message)
        return message

    def add_assistant_message(self, content: str) -> Message:
        return self.add_message("assistant", content)


class _ConversationManager:
    def __init__(self) -> None:
        self.conversation = _Conversation()

    def get_current_session(self) -> Session:
        return self.conversation.session

    def save(self) -> bool:
        return True


class _ScriptedTaskEngine(Engine):
    def __init__(
        self,
        turns: list[dict[str, Any]],
        *,
        settings: EngineSettings | None = None,
    ) -> None:
        self.test_conversation_manager = _ConversationManager()
        self.turns = deque(turns)
        self.provider_calls = 0
        self.streaming_flags: list[bool | None] = []
        super().__init__(
            settings=settings or EngineSettings(streaming_default=False),
            conversation_manager=self.test_conversation_manager,
            api_client=object(),
            tool_manager=object(),
            action_executor=object(),
        )

    def _resolve_components(self, agent_id: str | None = None) -> tuple[Any, ...]:
        del agent_id
        return self.test_conversation_manager, object(), object(), object()

    async def _llm_step(self, **kwargs: Any) -> dict[str, Any]:
        self.provider_calls += 1
        self.streaming_flags.append(kwargs.get("streaming"))
        return self.turns.popleft()


def _finish_turn(
    *,
    status: str,
    summary: str,
    action_status: str = "completed",
) -> dict[str, Any]:
    return {
        "assistant_response": "",
        "action_results": [
            {
                "action": "finish_task",
                "status": action_status,
                "result": "Task marked for review.",
                "tool_arguments": (f'{{"status": "{status}", "summary": "{summary}"}}'),
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }


@pytest.mark.asyncio
async def test_run_task_without_limits_crosses_legacy_iteration_and_token_thresholds() -> (
    None
):
    progress_turns = [
        {
            "assistant_response": f"Continuing {iteration}",
            "action_results": [
                {
                    "action": "read_file",
                    "status": "completed",
                    "result": f"result {iteration}",
                }
            ],
            "usage": {"total_tokens": 300_001 if iteration == 1 else 1},
        }
        for iteration in range(1, 102)
    ]
    engine = _ScriptedTaskEngine(
        [
            *progress_turns,
            _finish_turn(status="done", summary="Finished without a local cap"),
        ],
        settings=EngineSettings(
            streaming_default=False,
        ),
    )

    result = await engine.run_task(
        task_prompt="Keep going until complete",
        enable_events=False,
    )

    assert result["finish_status"] == "done"
    assert result["iterations"] == 102
    assert result["usage"]["total_tokens"] > 300_000
    assert engine.provider_calls == 102


@pytest.mark.asyncio
async def test_run_task_reports_typed_provider_timeout_without_implicit_completion() -> (
    None
):
    engine = _ScriptedTaskEngine([])
    provider_error = LLMError(
        message="OpenRouter SDK stream stalled",
        category=ErrorCategory.TIMEOUT,
        retryable=True,
        provider="openrouter",
        model="z-ai/glm-5.2",
    )
    engine._llm_step = AsyncMock(side_effect=LLMProviderError(provider_error))
    engine._check_wallet_guard_termination = MagicMock()
    messages: list[tuple[str, str]] = []

    async def message_callback(message: str, message_type: str) -> None:
        messages.append((message, message_type))

    result = await engine.run_task(
        task_prompt="Keep working",
        enable_events=False,
        message_callback=message_callback,
    )

    assert result["status"] == "provider_recoverable_error"
    assert result["finish_status"] is None
    assert result["error"] == provider_error.to_dict()
    assert result["recoverable"] is True
    assert messages == [("Provider Error: OpenRouter SDK stream stalled", "error")]
    engine._check_wallet_guard_termination.assert_not_called()


@pytest.mark.asyncio
async def test_run_task_uses_validated_finish_arguments() -> None:
    engine = _ScriptedTaskEngine(
        [_finish_turn(status="done", summary="Implemented the requested change")]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=3,
        enable_events=False,
    )

    assert result["status"] == "pending_review"
    assert result["finish_status"] == "done"
    assert result["finish_summary"] == "Implemented the requested change"


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_status", ["partial", "blocked"])
async def test_run_task_preserves_nonterminal_finish_statuses(
    finish_status: str,
) -> None:
    engine = _ScriptedTaskEngine(
        [_finish_turn(status=finish_status, summary="Current run summary")]
    )

    result = await engine.run_task(
        task_prompt="Continue the task",
        max_iterations=3,
        enable_events=False,
    )

    assert result["status"] == "pending_review"
    assert result["finish_status"] == finish_status
    assert result["finish_summary"] == "Current run summary"


@pytest.mark.asyncio
async def test_run_task_ignores_failed_finish_action() -> None:
    engine = _ScriptedTaskEngine(
        [
            _finish_turn(
                status="done",
                summary="This result failed",
                action_status="error",
            )
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        enable_events=False,
    )

    assert result["status"] == "iterations_exceeded"
    assert result["finish_status"] is None
    assert result["finish_summary"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arguments",
    [
        None,
        "not-json",
        '{"summary": "No status"}',
        '{"status": "complete"}',
    ],
)
async def test_run_task_never_defaults_invalid_finish_arguments_to_done(
    tool_arguments: str | None,
) -> None:
    result_info: dict[str, Any] = {
        "action": "finish_task",
        "status": "completed",
        "result": "Task marked for review.",
    }
    if tool_arguments is not None:
        result_info["tool_arguments"] = tool_arguments
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [result_info],
                "usage": {"total_tokens": 1},
            }
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        enable_events=False,
    )

    assert result["status"] == "iterations_exceeded"
    assert result["finish_status"] is None


@pytest.mark.asyncio
async def test_run_task_rejects_modern_finish_marker_without_structured_status() -> (
    None
):
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [
                    {
                        "action": "finish_task",
                        "status": "completed",
                        "result": "Task objective achieved [FINISH_STATUS:done]",
                    }
                ],
                "usage": {"total_tokens": 1},
            }
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        enable_events=False,
    )

    assert result["status"] == "iterations_exceeded"
    assert result["finish_status"] is None


@pytest.mark.asyncio
async def test_run_task_plain_completion_phrase_is_not_review_ready() -> None:
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "Finished. TASK_COMPLETED",
                "action_results": [],
                "usage": {"total_tokens": 1},
            }
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=2,
        enable_events=False,
    )

    assert result["status"] == "completion_phrase"
    assert result["finish_status"] is None


@pytest.mark.asyncio
async def test_run_task_accepts_explicit_legacy_finish_marker() -> None:
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [
                    {
                        "action": "task_completed",
                        "status": "completed",
                        "result": "Legacy completion [FINISH_STATUS:blocked]",
                        "tool_arguments": "legacy summary",
                    }
                ],
                "usage": {"total_tokens": 1},
            }
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        enable_events=False,
    )

    assert result["status"] == "pending_review"
    assert result["finish_status"] == "blocked"
    assert result["finish_summary"] == "legacy summary"


@pytest.mark.asyncio
async def test_legacy_finish_uses_tool_owned_terminal_status_marker() -> None:
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [
                    {
                        "action": "task_completed",
                        "status": "completed",
                        "result": (
                            "Summary: work [FINISH_STATUS:blocked] [FINISH_STATUS:done]"
                        ),
                        "tool_arguments": "work [FINISH_STATUS:blocked]",
                    }
                ],
                "usage": {"total_tokens": 1},
            }
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        enable_events=False,
    )

    assert result["status"] == "pending_review"
    assert result["finish_status"] == "done"


@pytest.mark.asyncio
async def test_run_task_accumulates_usage_across_provider_turns() -> None:
    finish_turn = _finish_turn(status="done", summary="Finished")
    finish_turn["usage"] = {
        "input_tokens": 7,
        "output_tokens": 3,
        "cache_read_tokens": 2,
        "total_tokens": 10,
        "cost": 0.2,
    }
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [
                    {
                        "action": "read_file",
                        "status": "completed",
                        "result": "contents",
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cache_read_tokens": 1,
                    "total_tokens": 12,
                    "cost": 0.1,
                },
            },
            finish_turn,
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=3,
        enable_events=False,
    )

    assert result["usage"] == {
        "input_tokens": 17,
        "output_tokens": 5,
        "cache_read_tokens": 3,
        "total_tokens": 22,
        "cost": pytest.approx(0.3),
    }


@pytest.mark.asyncio
async def test_run_task_accounts_for_every_empty_response_retry_attempt() -> None:
    class _UsageHandler:
        def __init__(self) -> None:
            self.usage: dict[str, Any] = {}

        def get_last_usage(self) -> dict[str, Any]:
            return dict(self.usage)

    class _RetryClient:
        def __init__(self) -> None:
            self.client_handler = _UsageHandler()
            self.usages = deque(
                [
                    {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                ]
            )

        async def get_response_result(self, *_args: Any, **_kwargs: Any) -> Any:
            self.client_handler.usage = self.usages.popleft()
            return LLMCallResult(text="")

    engine = _ScriptedTaskEngine([])
    retry_client = _RetryClient()

    async def retrying_step(**_kwargs: Any) -> dict[str, Any]:
        await engine._call_llm_with_retry(
            retry_client,
            [{"role": "user", "content": "continue"}],
            False,
            None,
            {},
        )
        raise AssertionError("empty retries should raise before returning")

    engine._llm_step = AsyncMock(side_effect=retrying_step)

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=1,
        token_budget=100,
        enable_events=False,
    )

    assert result["status"] == "llm_empty_response_error"
    assert result["usage"] == {
        "input_tokens": 7,
        "output_tokens": 5,
        "total_tokens": 12,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("max_iterations", [0, 3])
async def test_run_task_does_not_call_provider_when_budget_is_exhausted(
    max_iterations: int,
) -> None:
    engine = _ScriptedTaskEngine(
        [_finish_turn(status="done", summary="Must not execute")]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=max_iterations,
        token_budget=0,
        enable_events=False,
    )

    assert result["status"] == "budget_limited"
    assert result["iterations"] == 0
    assert result["usage"] == {}
    assert engine.provider_calls == 0


@pytest.mark.asyncio
async def test_exhausted_budget_short_circuits_before_lite_agent_resolution() -> None:
    engine = _ScriptedTaskEngine([])
    engine._resolve_agent = AsyncMock(
        return_value=(
            "lite-agent",
            {
                "status": "completed",
                "assistant_response": "Lite result",
            },
        )
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        token_budget=0,
        enable_events=False,
    )

    assert result["status"] == "budget_limited"
    engine._resolve_agent.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("token_budget", [-1, True, 1.5])
async def test_run_task_rejects_invalid_token_budget(token_budget: Any) -> None:
    engine = _ScriptedTaskEngine(
        [_finish_turn(status="done", summary="Must not execute")]
    )

    with pytest.raises(ValueError, match="token_budget"):
        await engine.run_task(
            task_prompt="Implement the change",
            max_iterations=3,
            token_budget=token_budget,
            enable_events=False,
        )

    assert engine.provider_calls == 0


@pytest.mark.asyncio
async def test_run_task_stops_after_turn_crosses_budget_threshold() -> None:
    first_action = {
        "action": "read_file",
        "status": "completed",
        "result": "contents",
    }
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [first_action],
                "usage": {
                    "input_tokens": 6,
                    "output_tokens": 2,
                    "reasoning_tokens": 2,
                },
            },
            _finish_turn(status="done", summary="Must not execute"),
        ]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=3,
        token_budget=9,
        enable_events=False,
    )

    assert result["status"] == "budget_limited"
    assert result["iterations"] == 1
    assert result["action_results"] == [first_action]
    assert result["usage"]["total_tokens"] == 10
    assert result["finish_status"] is None
    assert engine.provider_calls == 1


@pytest.mark.asyncio
async def test_valid_finish_wins_on_turn_that_reaches_budget() -> None:
    engine = _ScriptedTaskEngine(
        [_finish_turn(status="done", summary="Completed at the boundary")]
    )

    result = await engine.run_task(
        task_prompt="Implement the change",
        max_iterations=3,
        token_budget=12,
        enable_events=False,
    )

    assert result["status"] == "pending_review"
    assert result["finish_status"] == "done"
    assert result["finish_summary"] == "Completed at the boundary"
    assert result["usage"]["total_tokens"] == 12
    assert engine.provider_calls == 1


@pytest.mark.asyncio
async def test_run_task_uses_request_scoped_model_streaming_mode() -> None:
    engine = _ScriptedTaskEngine([_finish_turn(status="done", summary="Finished")])
    assert engine.settings.streaming_default is False

    await engine.run_task(
        task_prompt="Implement the change",
        model_config_override=SimpleNamespace(streaming_enabled=True),
        enable_events=False,
    )

    assert engine.streaming_flags == [True]
    assert engine.settings.streaming_default is False


@pytest.mark.asyncio
async def test_run_task_marks_generated_prompt_as_internal_when_requested() -> None:
    engine = _ScriptedTaskEngine([_finish_turn(status="done", summary="Finished")])

    await engine.run_task(
        task_prompt="Internal goal continuation",
        max_iterations=2,
        task_context={"internal_prompt": True},
        enable_events=False,
    )

    task_message = engine.test_conversation_manager.conversation.session.messages[0]
    assert task_message.role == "user"
    assert task_message.content == "Internal goal continuation"
    assert task_message.category is MessageCategory.INTERNAL
    assert task_message.metadata["internal_prompt"] is True
    assert task_message.metadata["visibility"] == "internal"


def test_internal_task_prompt_remains_visible_to_model_context() -> None:
    conversation = ConversationSystem()
    conversation.add_message(
        "user",
        "Internal goal continuation",
        MessageCategory.INTERNAL,
        {"visibility": "internal"},
    )

    assert conversation.get_formatted_messages() == [
        {"role": "user", "content": "Internal goal continuation"}
    ]
