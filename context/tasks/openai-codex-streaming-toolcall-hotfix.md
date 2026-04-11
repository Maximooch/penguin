# OpenAI Codex Streaming Tool-Call Hotfix

## Goal

- Stop GPT-5.4 / Codex sessions from leaking raw internal-looking tool scaffolding into the UI.
- Execute structured Responses tool calls instead of treating them like empty or malformed assistant text.

## Problem

- Native OpenAI/Codex streaming only handled text and a narrow reasoning subset.
- Structured Responses tool-call events were not accumulated into executable tool calls.
- Engine retries on empty responses could interfere with valid tool-call turns.

## Immediate Changes

- Parse Responses/Codex function-call events during streaming and non-streaming flows.
- Add adapter-side tool-call accumulation plus `get_and_clear_last_tool_call()` / `has_pending_tool_call()`.
- Enable Responses tools for native OpenAI models in the engine.
- Skip empty-response retries when a pending structured tool call exists.

## Status

- [x] Parse Responses/Codex function-call events during streaming and non-streaming flows.
- [x] Add adapter-side tool-call accumulation plus `get_and_clear_last_tool_call()` / `has_pending_tool_call()`.
- [x] Enable Responses tools for native OpenAI models in the engine.
- [x] Skip empty-response retries when a pending structured tool call exists.
- [x] Preserve real Responses `call_id` values when persisting tool results.
- [x] Replay Codex tool history back into subsequent OAuth requests as Responses-style `function_call` / `function_call_output` items.
- [x] Prevent tool-only Codex iterations from being misclassified as trivial/empty loop failures.

Implemented in:

- `penguin/llm/adapters/openai.py`
- `penguin/llm/runtime.py`
- `penguin/system/conversation.py`
- `penguin/system/conversation_manager.py`
- `penguin/engine.py`
- `tests/llm/test_openai_oauth_subscription_flow.py`
- `tests/test_conversation_tool_call_ids.py`
- `tests/test_engine_responses_tool_calls.py`
- `tests/test_engine_responses_tool_action_results.py`
- `tests/test_engine_responses_tool_events.py`

## Files

- `penguin/llm/adapters/openai.py`
- `penguin/engine.py`
- `penguin/system/conversation.py`
- `penguin/system/conversation_manager.py`
- `tests/test_openai_adapter_streaming.py`
- `tests/test_engine_responses_tool_calls.py`

## Follow-Up

- Standardize stream event normalization, tool-call semantics, and retry rules across providers in `context/tasks/llm-provider-contract.md`.
- Remaining OpenAI/Codex work is now mostly about transcript/event presentation quality rather than tool-call transport correctness.
- A remaining separate issue is transcript/result presentation parity versus OpenRouter, especially for exploratory multi-tool turns.
