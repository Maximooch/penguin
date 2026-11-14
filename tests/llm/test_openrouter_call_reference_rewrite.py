"""Only call ids are rewritten in plain OpenRouter messages, not code (SM-34)."""

from __future__ import annotations

import logging

import pytest

from penguin.llm.adapters.openrouter import OpenRouterGateway


def _clean(content: str) -> str:
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    gateway.logger = logging.getLogger("test_gateway")
    cleaned = gateway._clean_conversation_format([{"role": "user", "content": content}])
    return cleaned[0]["content"]


@pytest.mark.parametrize(
    "content",
    [
        "result = call_api(url)",
        "the call_count went up and call_handler ran",
        "def function_call_handler(): ...",
        "use on_call_end and call_ as a prefix",
    ],
)
def test_code_that_mentions_call_names_is_untouched(content: str) -> None:
    assert _clean(content) == content


@pytest.mark.parametrize(
    "call_id",
    ["call_abcd123", "call_1a2b3c4d", "call_1794550444611", "call_9f02fa16abcd"],
)
def test_orphaned_call_ids_are_still_replaced(call_id: str) -> None:
    cleaned = _clean(f"see {call_id} for the result")

    assert cleaned == "see [tool-call-reference] for the result"
