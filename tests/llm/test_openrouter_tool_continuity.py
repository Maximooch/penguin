from __future__ import annotations

import logging

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


def _gateway() -> OpenRouterGateway:
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    gateway.logger = logging.getLogger("test_openrouter_tool_continuity")
    gateway.model_config = ModelConfig(
        model="z-ai/glm-5.1",
        provider="openrouter",
        client_preference="openrouter",
    )
    return gateway


def test_clean_conversation_preserves_valid_assistant_tool_calls() -> None:
    gateway = _gateway()

    messages = [
        {
            "role": "assistant",
            "content": "Trying individual patch operations instead.",
            "tool_calls": [
                {
                    "id": "call_patch_123",
                    "type": "function",
                    "function": {
                        "name": "patch_files",
                        "arguments": '{"path":"a.ts","patch":"..."}',
                    },
                }
            ],
        }
    ]

    cleaned = gateway._clean_conversation_format(messages)

    assert cleaned == messages


def test_clean_conversation_preserves_valid_tool_result_messages() -> None:
    gateway = _gateway()

    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_patch_123",
            "content": '{"error":"permission_denied"}',
            "name": "patch_files",
            "tool_arguments": '{"path":"a.ts"}',
        }
    ]

    cleaned = gateway._clean_conversation_format(messages)

    assert cleaned == [
        {
            "role": "tool",
            "tool_call_id": "call_patch_123",
            "content": '{"error":"permission_denied"}',
        }
    ]


def test_clean_conversation_only_flattens_malformed_tool_messages() -> None:
    gateway = _gateway()

    messages = [
        {
            "role": "tool",
            "content": "tool result without id",
            "name": "patch_files",
        },
        {
            "role": "assistant",
            "content": "I should keep going",
            "tool_calls": [{"type": "function", "function": {"name": "patch_files"}}],
        },
    ]

    cleaned = gateway._clean_conversation_format(messages)

    assert cleaned == [
        {
            "role": "user",
            "content": "tool result without id",
            "name": "patch_files",
        },
        {
            "role": "assistant",
            "content": "I should keep going",
        },
    ]
