# LLM Provider Contract Design Patterns

## Purpose

Capture the architectural patterns OpenCode gets right in its LLM stack that Penguin should adopt while keeping Penguin provider-agnostic and friendly to local inference backends.

## Key Point

The main lesson from OpenCode is architectural, not vendor-specific.

Penguin does not need Vercel's AI SDK to get the same benefits.
It needs:

- one internal provider contract
- one provider registry
- one normalization layer
- one canonical streaming event model

That structure works equally well for:

- native APIs
- OpenAI-compatible gateways
- OpenRouter
- LiteLLM
- local inference servers like vLLM, SGLANG, and llama.cpp

## What OpenCode Gets Right

### 1. One canonical runtime contract

OpenCode routes model execution through one core streaming path and one normalized event stream.

Penguin should adopt the same idea with native Python types such as:

- `LLMRequest`
- `LLMResult`
- `LLMStreamEvent`
- `LLMToolCall`
- `LLMUsage`
- `LLMError`

The rest of Penguin should consume those types rather than raw gateway payloads or per-provider callback conventions.

### 2. One provider registry

OpenCode resolves providers and models centrally, then returns a single model/runtime object.

Penguin should move toward a single registry or runtime resolver that owns:

- provider selection
- model resolution
- auth and base URL wiring
- header injection
- native vs gateway vs OpenAI-compatible adapter selection

This should replace overlapping routing logic currently split across `api_client.py`, `client.py`, `provider_adapters.py`, and individual gateways.

### 3. One shared transform layer for quirks

OpenCode centralizes request shaping and provider quirks in a shared transform layer instead of burying them inside every provider implementation.

Penguin should introduce a similar layer to own:

- message normalization
- tool-call history normalization
- reasoning option mapping
- multimodal normalization
- schema/tool payload normalization
- OpenAI-compatible server quirks

That is especially important for local inference because many local backends are close to OpenAI-compatible but differ in small, important ways.

### 4. One normalized stream and result grammar

OpenCode turns provider streams into one internal event model for text, reasoning, tools, finish, and errors.

Penguin should do the same so `Engine` and downstream state management only see canonical events like:

- `text_start`
- `text_delta`
- `text_end`
- `reasoning_start`
- `reasoning_delta`
- `reasoning_end`
- `tool_call`
- `tool_result`
- `finish`
- `error`

### 5. Centralized usage, error, and retry semantics

OpenCode normalizes usage accounting and error handling before retry logic runs.

Penguin should stop depending on provider-specific error strings and partial usage surfaces.
Instead, adapters should return or raise canonical structures for:

- usage/token accounting
- retryability
- rate limits and `Retry-After`
- timeouts
- auth failures
- provider unavailability

## What Penguin Should Not Copy Blindly

Penguin should not couple itself to an external SDK contract if that would limit local inference support or hide provider differences Penguin needs to control directly.

The goal is to copy the architecture, not the dependency.

## Recommended Translation Into Penguin

Suggested internal modules:

- `penguin/llm/contracts.py`
- `penguin/llm/provider_registry.py`
- `penguin/llm/provider_transform.py`
- `penguin/llm/runtime.py`

Suggested provider strategy:

- keep native adapters where the provider has unique capabilities worth exposing
- add a strong `openai_compatible` adapter path for local inference and compatible gateways
- keep provider-specific quirks at the adapter edge or in shared transforms, not in `Engine`

## Why This Matters

Penguin's current LLM stack has multiple overlapping contracts.
That makes new providers expensive to add and hard to test.

The target is not uniformity for its own sake.
It is one stable internal contract with explicit adapter-edge exceptions.
