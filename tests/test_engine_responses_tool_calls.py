from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.engine import Engine


def test_prepare_responses_tools_enables_openai_native_tools() -> None:
    engine_like = SimpleNamespace(
        model_config=SimpleNamespace(
            provider="openai",
            client_preference="native",
            use_responses_api=False,
            interrupt_on_tool_call=False,
        )
    )
    tool_manager = SimpleNamespace(
        get_responses_tools=lambda: [{"type": "function", "name": "read_file"}]
    )

    extra_kwargs = Engine._prepare_responses_tools(engine_like, tool_manager)

    assert extra_kwargs == {
        "tools": [{"type": "function", "name": "read_file"}],
        "tool_choice": "auto",
    }
    assert engine_like.model_config.interrupt_on_tool_call is True


@pytest.mark.asyncio
async def test_call_llm_with_retry_skips_retry_when_tool_call_pending() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls = 0
            self.client_handler = SimpleNamespace(has_pending_tool_call=lambda: True)

        async def get_response(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return ""

    api_client = _Client()
    engine_like = SimpleNamespace(
        _handler_has_pending_tool_call=lambda client: Engine._handler_has_pending_tool_call(
            engine_like,
            client,
        ),
        _build_empty_response_diagnostics=lambda *_args, **_kwargs: {},
    )

    result = await Engine._call_llm_with_retry(
        engine_like,
        api_client,
        [{"role": "user", "content": "hi"}],
        True,
        None,
        {},
    )

    assert result == ""
    assert api_client.calls == 1
