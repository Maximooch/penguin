# OpenAI Codex OAuth Tool Schema Fix

## Goal

- Fix native OpenAI OAuth/Codex sessions failing when Penguin sends tool-enabled Responses requests.
- Standardize the OpenAI Responses tool payload shape used by native OpenAI paths.
- Prevent further drift between SDK Responses usage, direct Codex OAuth HTTP usage, engine expectations, and tests.

## Problem

OpenAI OAuth/Codex requests are currently failing with:

```text
Missing required parameter: 'tools[0].name'.
```

Observed runtime failure:

- `OpenAIAdapter._create_oauth_codex_completion()` forwards `tools` directly into the Codex Responses payload.
- `Engine._prepare_responses_tools()` sources those tools from `ToolManager.get_responses_tools()`.
- `ToolManager.get_responses_tools()` currently emits Chat Completions-style function tools:

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "...",
    "parameters": {"type": "object", "properties": {}}
  }
}
```

- The Codex OAuth Responses endpoint expects function tools with top-level `name` rather than nested `function.name`.

That means Penguin is currently mixing at least two incompatible tool schemas under the label "Responses tools".

## Confirmed Evidence

- Runtime error log: `Missing required parameter: 'tools[0].name'`
- `penguin/engine.py:2046-2077`
- `penguin/tools/tool_manager.py:1939-1965`
- `penguin/llm/adapters/openai.py:323-347`
- `penguin/llm/adapters/openai.py:741-758`

## Additional Drift Evidence

Current tests already disagree about the expected shape:

- `tests/test_engine_responses_tool_calls.py` expects:

```python
[{"type": "function", "name": "read_file"}]
```

- `tests/test_parser_and_tools.py` currently inspects:

```python
t["function"]["name"]
```

That mismatch is a concrete example of the broader provider-contract drift tracked in `context/tasks/llm-provider-contract.md`.

## Desired Outcome

- Penguin has one canonical internal tool schema for OpenAI Responses-style function tools.
- Native OpenAI SDK calls and direct Codex OAuth HTTP calls both use the same normalized payload.
- `ToolManager.get_responses_tools()` no longer returns a shape that is ambiguous between Chat Completions and Responses APIs.

## Proposed Fix Shape

### Phase 1 - Lock Down Failing Behavior

- Add a regression test for OAuth/Codex requests with function tools.
- Assert the outgoing payload contains top-level `name`, `description`, and `parameters` for function tools.
- Add a regression test for the current failure mode if useful.

Suggested targets:

- `tests/llm/test_openai_oauth_subscription_flow.py`
- `tests/test_engine_responses_tool_calls.py`
- `tests/test_parser_and_tools.py`

### Phase 2 - Normalize Tool Shape

- Introduce one canonical builder for OpenAI Responses tools.
- Either:
  - make `ToolManager.get_responses_tools()` return canonical Responses tool descriptors, or
  - add an explicit adapter-side normalization step before native OpenAI/Codex requests are sent.

Preferred direction:

- centralize the schema conversion in the LLM layer, not in multiple call sites
- avoid leaving one shape for SDK paths and a different one for OAuth/Codex paths

### Phase 3 - Verify Adjacent Cases

- confirm `tool_choice="auto"` still works with the normalized schema
- verify built-in non-function tools like `web_search` still serialize correctly
- verify tool-call capture still works in streaming and non-streaming native OpenAI flows

## Relationship To Provider Contract Work

This should likely be treated as a focused follow-up task adjacent to, or immediately after, `context/tasks/llm-provider-contract.md`.

Reason:

- the bug is specific and actionable now
- the root cause is the same larger issue: Penguin currently has no single canonical provider/tool contract across all LLM paths

## Verification Targets

- `tests/llm/test_openai_oauth_subscription_flow.py`
- `tests/test_openai_adapter_streaming.py`
- `tests/test_engine_responses_tool_calls.py`
- `tests/test_parser_and_tools.py`

## Notes

- This is not just an OAuth/Codex bug.
- It exposes a contract mismatch between engine, tool manager, native OpenAI adapter logic, and tests.
