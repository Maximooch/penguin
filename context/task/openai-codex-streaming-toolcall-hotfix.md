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

## Files

- `penguin/llm/adapters/openai.py`
- `penguin/engine.py`
- `tests/test_openai_adapter_streaming.py`
- `tests/test_engine_responses_tool_calls.py`

## Follow-Up

- Standardize stream event normalization, tool-call semantics, and retry rules across providers in `context/tasks/llm-provider-contract.md`.
