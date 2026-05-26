"""Core shim coverage for process runtime delegation."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.core import PenguinCore


@pytest.mark.asyncio
async def test_core_process_delegates_to_retry_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def _process_with_retry(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((args, kwargs))
        return {"assistant_response": "done", "action_results": []}

    facade_globals = PenguinCore.process.__globals__
    monkeypatch.setattr(
        facade_globals["core_process_runtime"],
        "process_with_retry",
        _process_with_retry,
    )

    result = await core.process(
        {"text": "hello"},
        context={"source": "test"},
        conversation_id="conversation-1",
        agent_id="agent-1",
        max_iterations=2,
        context_files=["ctx.py"],
        streaming=True,
        stream_callback=lambda chunk: None,
        multi_step=False,
        api_client_override="api-client",
        model_config_override="model-config",
    )

    assert result == {"assistant_response": "done", "action_results": []}
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (core,)
    assert kwargs["input_data"] == {"text": "hello"}
    assert kwargs["context"] == {"source": "test"}
    assert kwargs["conversation_id"] == "conversation-1"
    assert kwargs["agent_id"] == "agent-1"
    assert kwargs["max_iterations"] == 2
    assert kwargs["context_files"] == ["ctx.py"]
    assert kwargs["streaming"] is True
    assert kwargs["multi_step"] is False
    assert kwargs["api_client_override"] == "api-client"
    assert kwargs["model_config_override"] == "model-config"
    assert callable(kwargs["stream_callback"])
    assert callable(kwargs["trace_log_info"])
    assert callable(kwargs["log_error_fn"])
