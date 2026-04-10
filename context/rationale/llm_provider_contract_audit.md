# LLM Provider Contract Audit

## Purpose

Document the current provider-contract drift in Penguin before introducing a canonical LLM contract.

## Scope Assumptions

- `openai_assistant.py` is legacy and out of scope for the first contract pass.
- Link should be treated as a transport/platform integration layered on the runtime, not as a separate provider contract.
- First-class contract targets should be:
  - native `openai`
  - native `anthropic`
  - `openrouter`
  - a first-class `openai_compatible` path
  - a generic adapter template for new providers
- `litellm` still matters in the audit because it is an active source of contract drift even if it is not part of the first idealized target set.

## Active Entry Points Today

Penguin currently has multiple overlapping LLM entry points:

- `APIClient` dispatches requests and normalizes streaming callbacks to `(chunk, message_type)` in `penguin/llm/api_client.py:507-676`.
- `LLMClient` wraps gateways for Link/base-url/header injection in `penguin/llm/client.py:268-387`.
- native adapters sit under `penguin/llm/adapters/`.
- `OpenRouterGateway` is its own large runtime in `penguin/llm/openrouter_gateway.py`.
- `LiteLLMGateway` is another separate runtime in `penguin/llm/litellm_gateway.py`.
- `adapters/__init__.py` still falls back to legacy `provider_adapters.py` in `penguin/llm/adapters/__init__.py:12-52`.

That means Penguin does not currently have one provider contract. It has several partially overlapping ones.

## Current Provider Shapes

### OpenAI native

- Uses the Responses API in `penguin/llm/adapters/openai.py:60-70`.
- Supports custom `api_base`, which currently doubles as the closest thing to an `openai_compatible` path in `penguin/llm/adapters/openai.py:90-95`.
- Implements pending tool-call capture and retrieval in `penguin/llm/adapters/openai.py:111-123`.
- Uses direct Codex OAuth HTTP transport for ChatGPT Pro / OAuth sessions in `penguin/llm/adapters/openai.py:714-1047`.
- Has provider-specific reasoning shaping in `penguin/llm/adapters/openai.py:1504-1545`.

### Anthropic native

- Uses Anthropic's native `messages.create` flow in `penguin/llm/adapters/anthropic.py:45-113` and `133-215`.
- Streams text and thinking deltas directly in `penguin/llm/adapters/anthropic.py:260-493`.
- Applies provider-specific effort/thinking config in `penguin/llm/adapters/anthropic.py:524-556`.
- Does not expose the same pending tool-call or usage accessors that OpenAI/OpenRouter rely on.

### OpenRouter gateway

- Uses OpenAI-compatible chat payloads, not the OpenAI Responses model, in `penguin/llm/openrouter_gateway.py:763-881`.
- Has its own message cleanup and vision preprocessing path in `penguin/llm/openrouter_gateway.py:820-825`.
- Switches to a direct HTTP path for reasoning-enabled calls in `penguin/llm/openrouter_gateway.py:873-925`.
- Exposes normalized usage and pending tool-call accessors in `penguin/llm/openrouter_gateway.py:271-304`, `417-515`, and `1844-1864`.

### LiteLLM gateway

- Uses LiteLLM chat-completion-style params in `penguin/llm/litellm_gateway.py:59-200`.
- Returns plain strings for many errors instead of raising canonical exceptions in `penguin/llm/litellm_gateway.py:144-166`.
- Does not implement the same usage/tool-call contract expected by the stronger native paths.

### Link wrapper / transport path

- `LLMClient` injects `X-Link-*` headers and base URLs in `penguin/llm/client.py:248-366`.
- It wraps existing gateways instead of enforcing a separate provider contract.
- In practice it is a transport concern mixed into runtime dispatch.

### Legacy fallback path

- `provider_adapters.py` defines yet another adapter interface with an explicit `# TODO: implement streaming abstraction` in `penguin/llm/provider_adapters.py:46`.
- `adapters/__init__.py` still routes unsupported or non-native providers there in `penguin/llm/adapters/__init__.py:50-52`.

## Drift Matrix

### 1. Request shaping

- OpenAI native uses Responses-style `input` payloads and can split `instructions` from message history in `penguin/llm/adapters/openai.py:323-418` and `714-758`.
- Anthropic native uses `messages` plus top-level `system` in `penguin/llm/adapters/anthropic.py:148-178`.
- OpenRouter uses chat-completions-style `messages` and `max_tokens` in `penguin/llm/openrouter_gateway.py:838-881`.
- LiteLLM uses `messages` and `max_tokens` in `penguin/llm/litellm_gateway.py:168-200`.
- `openai_compatible` is not a first-class adapter today; it is implicitly split between `OpenAIAdapter(api_base=...)`, OpenRouter-compatible usage, and LiteLLM-compatible usage.

### 2. Streaming callback contract

- `APIClient` normalizes to async `(chunk, message_type)` callbacks in `penguin/llm/api_client.py:615-672`.
- `BaseAdapter` still types `stream_callback` as single-arg in `penguin/llm/adapters/base.py:37-58`.
- OpenAI and Anthropic actually emit two semantic channels, assistant and reasoning, in `penguin/llm/adapters/openai.py:957-992` and `penguin/llm/adapters/anthropic.py:307-323`.
- OpenRouter also emits `(chunk, message_type)` semantics in both SDK and direct-stream paths.
- LiteLLM still types a single-arg callback in `penguin/llm/litellm_gateway.py:59-67`.

### 3. Tool-call contract

- OpenAI native has the strongest tool-call interrupt contract via `has_pending_tool_call()` and `get_and_clear_last_tool_call()` in `penguin/llm/adapters/openai.py:111-123`.
- OpenRouter exposes the same style of accessors in `penguin/llm/openrouter_gateway.py:1850-1864`.
- Anthropic has no equivalent adapter-level tool-call contract.
- LiteLLM has no equivalent adapter-level tool-call contract.
- Tool schema expectations are already drifting. `Engine._prepare_responses_tools()` assumes one Responses tool payload in `penguin/engine.py:2046-2077`, while `ToolManager.get_responses_tools()` currently emits nested Chat Completions-style function descriptors in `penguin/tools/tool_manager.py:1939-1965`.

### 4. Finish reasons and stop semantics

- OpenRouter tracks finish reasons during streaming and direct calls in `penguin/llm/openrouter_gateway.py:1531-1599` and surrounding logic.
- Anthropic captures `stop_reason` during streaming and non-streaming parsing in `penguin/llm/adapters/anthropic.py:338-343` and `585-625`.
- OpenAI native uses Responses completion events but does not surface a shared normalized finish-reason interface to the rest of Penguin.
- `Engine` still has to reason about empty responses and pending tool calls instead of consuming a canonical finish/result object in `penguin/engine.py:2208-2293`.

### 5. Usage and token accounting

- OpenRouter normalizes usage into a stable dict and exposes `get_last_usage()` in `penguin/llm/openrouter_gateway.py:271-304`, `375-415`, `417-515`, and `1844-1848`.
- Anthropic logs usage internally during stream handling, but does not expose a shared `get_last_usage()` contract in `penguin/llm/adapters/anthropic.py:272-493`.
- OpenAI native does not expose a matching `get_last_usage()` surface either.
- `Engine` already probes handlers for `get_last_usage` in `penguin/engine.py:903`.
- This means only some providers participate in structured usage reporting.

### 6. Retry, timeout, and failure semantics

- OpenRouter encodes timeout and upstream failures as returned error strings like `[Error: ...]` in `penguin/llm/openrouter_gateway.py:1498-1511` and stream handlers.
- LiteLLM also returns plain error strings in `penguin/llm/litellm_gateway.py:144-166`.
- Anthropic mostly raises exceptions.
- OpenAI Codex OAuth raises `RuntimeError` with rich diagnostics in `penguin/llm/adapters/openai.py:1112-1175`.
- `Engine` applies one retry-on-empty-response policy across these mixed behaviors in `penguin/engine.py:2227-2293`.

### 7. Provider registry and resolution

- Native adapter selection lives in `penguin/llm/adapters/__init__.py:19-52`.
- `APIClient` has its own handler-selection logic.
- `LLMClient` has a separate gateway-selection path in `penguin/llm/client.py:268-315`.
- This means provider resolution and runtime construction are not centralized.

## Intentional Exceptions Worth Preserving

- `OpenRouterGateway` intentionally ignores `OPENAI_BASE_URL` so OpenRouter auth/header semantics are not accidentally broken. That is correct and should be preserved in a future registry/transform model. See `tests/llm/test_openrouter_base_url_isolation.py` and `penguin/llm/openrouter_gateway.py:91-102`.
- Link should remain a transport/header integration concern rather than forcing a distinct provider abstraction.
- Native adapters should still exist when they expose capabilities that generic OpenAI-compatible paths cannot model well enough.

## Explicit Gaps To Close

- there is no first-class `openai_compatible` adapter today
- there is no single canonical `LLMResult` / `LLMStreamEvent` / `LLMError` shape
- there is no single provider registry/resolver
- tool schema handling is already split across incompatible assumptions
- usage accessors are only implemented by some handlers
- retryability is inferred from mixed strings, exceptions, and partial adapter hooks

## Recommended First Contract Baseline

The first canonical contract should be small and explicit:

- `LLMRequest`
- `LLMResult`
- `LLMStreamEvent`
- `LLMToolCall`
- `LLMUsage`
- `LLMError`
- `FinishReason`

The first providers to make conform should be:

- native `openai`
- native `anthropic`
- `openrouter`
- a new explicit `openai_compatible`

Link should then consume that runtime as a transport/config wrapper rather than remaining a partially separate LLM path.
