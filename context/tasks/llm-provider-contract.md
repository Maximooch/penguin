# LLM Provider Contract TODO

## Objective

- Define one canonical provider contract for completions, streaming, retries, tool calls, and reasoning-token behavior.
- Reduce provider-specific drift between OpenRouter, LiteLLM, native adapters, and other gateways.
- Make new provider integrations cheaper to add and safer to test.

## Why This Exists

- Penguin’s LLM behavior is spread across multiple layers:
  - `api_client.py`
  - `client.py`
  - `provider_adapters.py`
  - `openrouter_gateway.py`
  - `litellm_gateway.py`
  - `openai_assistant.py`
- That usually means contract drift: similar concepts implemented differently in parallel.

## Audit Evidence

- `penguin/llm/api_client.py`
- `penguin/llm/client.py`
- `penguin/llm/contracts.py`
- `penguin/llm/reasoning_variants.py`
- `penguin/llm/runtime.py`
- `penguin/llm/provider_registry.py`
- `penguin/llm/provider_transform.py`
- `penguin/llm/adapters/openrouter.py`
- `penguin/llm/adapters/litellm.py`
- `penguin/llm/openrouter_gateway.py` (compatibility shim)
- `penguin/llm/litellm_gateway.py` (compatibility shim)
- `penguin/llm/stream_handler.py`
- `tests/llm/provider_contract_fixtures.py`
- `tests/llm/test_provider_contract_matrix.py`
- `tests/test_api_client.py`
- provider-specific test files under `tests/` and `penguin/llm/`

## Design Inputs

- `context/rationale/llm_provider_contract_design_patterns.md`
- `context/rationale/llm_provider_contract_audit.md`

Key architectural lessons to adopt from OpenCode:

- one internal provider contract
- one provider registry/resolver
- one shared normalization/transform layer
- one canonical stream/result grammar
- one centralized usage/error/retry model

Tool-runtime lessons from Codex/OpenCode are tracked in
`context/tasks/tool-call-runtime-architecture.md`. This provider-contract plan
should own wire-format normalization, provider-specific request shaping, stream
events, finish reasons, usage, and error semantics. It should not duplicate the
scheduler, permission, truncation, or process-runtime plan.

Testing strategy is tracked in `context/tasks/testing-pyramid.md`. Provider
contract work should use deterministic fake-provider and fault-injection tests
as the confidence gate; live provider tests are opt-in smoke tests only.

Provider reliability lessons from Codex/OpenCode should be adopted at the
contract level where they are provider-agnostic:

- a model turn should have a request lifecycle record, not just an awaited HTTP
  call
- stream completion must be explicit; a socket close without a provider
  completion event is an incomplete response, not a successful empty response
- provider errors must release the current turn so the next user turn can
  proceed
- retry/recovery decisions should use provider capability metadata and request
  identity, not ad hoc string matching
- provider-specific resumability, such as OpenAI background responses, should
  be a capability behind the common lifecycle record

Important constraint:

- adopt the architecture, not the dependency; Penguin should remain provider-agnostic and local-inference-friendly rather than coupling itself to Vercel's AI SDK
- provider-specific behavior must live in `penguin/llm` provider modules and shared LLM runtime layers, not in `engine.py`, `core.py`, `web/routes.py`, or tool implementations
- provider adapters may translate provider-native tool-call wire formats into
  canonical calls/results, but tool risk, permissions, scheduling, truncation,
  and process execution belong to the tool runtime

## Progress Snapshot

- [x] Document current provider contract drift
- [x] Define a canonical request/response/streaming abstraction
- [x] Standardize retry, timeout, and rate-limit handling semantics
- [x] Standardize tool-call and reasoning-token behavior across providers
- [x] Build a shared contract test matrix
- [x] Gate provider implementations against the same expectations

## Checklist

### Phase 1 - Contract Audit
- [x] Compare provider behavior for:
  - request shaping
  - streaming chunk assembly
  - tool call payloads
  - finish reasons
  - usage/token accounting
  - retry/failure handling
- [x] Document mismatches and intentional exceptions

### Phase 2 - Canonical Contract
- [x] Define provider-agnostic types/interfaces
- [x] Define one canonical request/result/event/error contract for all providers
- [x] Add a single provider registry/resolver instead of overlapping entry points
- [x] Centralize normalization where possible
- [x] Add a shared transform layer for request shaping and provider quirks
- [ ] Keep provider-specific quirks at the adapter edge
- [x] Preserve a first-class `openai_compatible` path for local inference backends and compatible gateways

### Phase 3 - Validation
- [x] Add contract tests each provider must pass
- [x] Add explicit fixtures for streaming + tool-call edge cases
- [x] Add reasoning-token cases where relevant
- [x] Verify the same contract against native, gateway, and local-inference-compatible adapters
- [ ] Add incomplete-stream and turn-release contract cases for provider
      transports that stream

## Provider Request Lifecycle Contract

The provider contract should expose one lifecycle model for all model calls,
even when a specific provider has extra recovery features.

Canonical states:

- `pending`: Penguin has created the request record but has not sent traffic yet.
- `running`: the provider request has been sent.
- `streaming`: Penguin has received at least one stream event.
- `disconnected`: transport ended before the provider emitted a completion
  event or equivalent terminal signal.
- `retrying`: Penguin is retrying or reconnecting under the provider policy.
- `completed`: the provider emitted a terminal completion and Penguin recorded
  final content/tool calls/usage.
- `failed`: the provider request ended with a normalized failure.
- `cancelled`: Penguin or the user cancelled the request.

Minimum request-record fields:

- Penguin session/conversation id and turn id
- provider, adapter, model, and endpoint/transport family
- request payload hash and request-shape version
- attempt count, start time, last event time, and terminal time
- provider response id or equivalent continuation id when available
- last stream event type and provider finish reason when available
- canonical error category plus provider-native error metadata

Contract expectations:

- providers that stream must distinguish completed streams from incomplete
  streams
- incomplete streams must either retry/recover or surface a structured
  recoverable failure
- failures must emit a terminal lifecycle event so the engine/session is not
  left busy
- provider adapters should expose whether a request can be resumed, polled, or
  safely retried from canonical history
- incremental identifiers such as `previous_response_id` should only be reused
  when the adapter can prove the next request is a safe prefix extension of the
  prior request

OpenAI-specific notes:

- `background=true` and `store=true` are capabilities for server-side
  continuation/retrieval, not the general lifecycle model.
- Foreground stateless requests still need long-stream timeout/stall handling
  and explicit incomplete-stream detection.
- Stateless reasoning continuity still depends on the encrypted reasoning
  content path when Penguin is not using stored provider state.

## Verification Targets

- `tests/test_api_client.py`
- `tests/llm/test_llm_contracts.py`
- `tests/llm/test_provider_registry.py`
- `tests/llm/test_llm_client_contract.py`
- `tests/llm/test_link_runtime_contract.py`
- `tests/llm/provider_contract_fixtures.py`
- `tests/llm/test_provider_contract_matrix.py`
- `tests/llm/test_openai_oauth_subscription_flow.py`
- OpenRouter-specific tests
- LiteLLM cleanup/runtime tests
- streaming tests
- provider adapter tests

## Provider Reliability Test Matrix

Phase 2/3 provider work should add hermetic fixtures before tightening runtime
behavior. The fake-provider contract suite should cover:

- completed text streams
- completed native tool-call streams
- terminal empty responses
- stream closes before terminal event with no output
- stream closes before terminal event after text output
- stream closes before terminal event after a tool call
- provider errors before and during streaming
- timeout and idle-stream behavior
- retry succeeds and retry exhausted behavior
- next-turn release after failures
- request replay after CWM category-priority truncation

Provider-native tool replay tests should cover:

- completed, failed, cancelled, and interrupted tool results
- dangling tool calls repaired into explicit failed/cancelled outputs
- provider-specific id normalization and adjacency rules
- large tool outputs truncated before model replay with full output persisted

The contract suite should use real log/bug cases as minimized fixtures where
possible, especially `context/bugs/*` and `misc/web-server-logs-*`. Do not use
live provider requests as the proof that a contract path is correct.

## Phase 2 Notes

- Added canonical types in `penguin/llm/contracts.py` for request/result/event/error/usage/tool-call modeling.
- Added shared provider/model normalization in `penguin/llm/provider_transform.py`.
- Added `penguin/llm/provider_registry.py` and routed both `APIClient` and `LLMClient` through it.
- Added an explicit `openai_compatible` native adapter path backed by `OpenAIAdapter` semantics plus custom `api_base`.
- This is an architectural baseline, not the finished migration. Provider-specific streaming/tool/retry/usage behavior is still only partially normalized.

## Phase 3 Notes

- Added shared contract fixtures in `tests/llm/provider_contract_fixtures.py`.
- Added a provider contract matrix in `tests/llm/test_provider_contract_matrix.py`.
- The matrix currently gates the same core expectations across:
  - native `openai`
  - native `anthropic`
  - `openrouter`
  - native `openai_compatible`
- Added shared validation for:
  - normalized usage accessors
  - streaming callback contract
  - reasoning chunk handling
  - tool-call interrupt behavior where supported
- Added default contract hooks on `BaseAdapter` and normalized `get_last_usage()` on native OpenAI and Anthropic adapters so the matrix can assert one shared surface.

## Post-Phase 3 Implementation Notes

- Canonical error metadata now flows through `LLMError` / `LLMProviderError` plus handler `get_last_error()` hooks.
- Canonical provider request lifecycle metadata now lives in
  `ProviderRequestStatus`, `LLMRequestLifecycle`, and
  `RequestLifecycleRuntime`.
- OpenAI/Codex OAuth SSE is the first lifecycle adopter, including disconnected
  incomplete-stream handling and long-stream timeout policy.
- `APIClient` now prefers canonical handler error metadata over provider-specific placeholder strings when formatting user-visible failures.
- Retry, timeout, rate-limit, and upstream-unavailable cases now normalize onto canonical categories for active handler paths.
- `Retry-After` / retry timing is normalized where handlers expose it.
- Finish reasons and accumulated reasoning are now exposed via shared getter hooks on active providers.
- OpenAI Responses tool descriptors are normalized to the canonical top-level function schema.
- The Codex OAuth tool-schema mismatch tracked in `context/tasks/openai-codex-oauth-tool-schema-fix.md` is fixed.
- Added Link-specific runtime verification on top of the shared provider runtime path.
- Updated OpenRouter-routed fixture model IDs away from deprecated `gpt-4o` placeholders to current catalog examples such as `openai/gpt-4.1-mini`, `openai/gpt-5.4-nano`, and `arcee-ai/trinity-large-thinking`.
- Added `penguin/llm/runtime.py` to own shared provider/runtime orchestration helpers.
- `engine.py` now delegates Responses tool preparation, pending-tool execution, empty-response diagnostics, retry behavior, and reasoning fallback detection into `penguin/llm/runtime.py`.
- `web/routes.py` now delegates reasoning-note and reasoning-debug snapshot logic into `penguin/llm/runtime.py`.
- Native/provider reasoning variant support now lives under `penguin/llm/reasoning_variants.py`, with `web/routes.py` delegating override/restore behavior into `penguin/llm/runtime.py`.
- `tools/tool_manager.py` no longer imports provider-specific tool normalization helpers from `penguin/llm/provider_transform.py`.
- OpenRouter and LiteLLM gateway implementations now live under `penguin/llm/adapters/`, with top-level compatibility shims kept temporarily to avoid breaking imports.
- `LLMClient` now routes requests through `APIClient` instead of maintaining a fully separate runtime path, while keeping a compatibility `_get_gateway()` surface for older tests/callers.
- `provider_adapters.py` has been retired; unsupported native providers now fail explicitly instead of silently falling back to the legacy generic adapter path.

## Boundary Reality Check

Despite the contract and validation progress, Penguin still has provider-specific runtime behavior leaking outside `penguin/llm`.

Current examples:

- `penguin/engine.py`
  - Responses/OpenAI-specific tool-call handling in `_prepare_responses_tools()` and `_handle_responses_tool_call()`
  - reasoning fallback injection tied to provider behavior
  - loop continuation logic coupled to provider tool-interrupt semantics
- `penguin/web/routes.py`
  - reasoning display policy, fallback-note policy, and reasoning debug shaping tied to provider response behavior
- `penguin/core.py`
  - action-to-tool and action-result mapping compensating for provider/runtime-specific event shapes
- `penguin/tools/tool_manager.py`
  - OpenAI Responses tool descriptor shaping imported from `penguin.llm.provider_transform`

This is the main reason recent fixes have felt like one-off patches instead of the system settling cleanly.

## Architectural Direction

Provider-specific behavior should be owned by provider modules under `penguin/llm`, for example:

- OpenAI-specific behavior in `penguin/llm/adapters/openai.py`
- Anthropic-specific behavior in `penguin/llm/adapters/anthropic.py`
- OpenRouter-specific behavior in `penguin/llm/openrouter_gateway.py` until it is moved under `adapters/`
- LiteLLM-specific behavior in `penguin/llm/litellm_gateway.py` until it is moved under `adapters/`

Higher layers should consume only canonical results/events/errors/tool-call interrupts.

That means:

- `engine.py` should orchestrate generic iteration and tool execution only
- `core.py` should translate canonical runtime events to UI/OpenCode events only
- `web/routes.py` should expose already-normalized response payloads only
- tool implementations should not know or care about provider-specific tool schema quirks

## Scope Decision

- LiteLLM is currently treated as a secondary compatibility path, not a first-class provider in the contract matrix.
- It now exposes canonical error/usage/finish-reason hooks, but it is not yet gated by the same full matrix as `openai`, `anthropic`, `openrouter`, and `openai_compatible`.
- LiteLLM follow-up work is deferred until after Phase 5 structural cleanup.
- Link integration is not part of the current verification target.
- The current priority is making typical `openai` and `openrouter` behavior solid before touching Link-specific end-to-end behavior.
- Link-specific verification should be treated as Phase 6 work after the provider contract and module consolidation work are in a healthier state.

## Phase 3 Wrap-Up

- Phase 3 validation is complete for the current in-scope provider set:
  - native `openai`
  - native `anthropic`
  - `openrouter`
  - native `openai_compatible`
- The contract matrix now guards the baseline runtime surface Penguin expects from those handlers.
- Remaining work is no longer about whether the contract can be tested.
- It is about finishing semantic normalization so all providers behave consistently behind that tested surface.

Phase 3 follow-up items that are useful but not required to consider the validation phase complete:

- add Link transport/integration coverage against the shared runtime path
- decide whether LiteLLM should be upgraded to the same contract matrix or remain outside the first-class contract set
- add Codex OAuth regression coverage after `context/tasks/openai-codex-oauth-tool-schema-fix.md` is implemented

## Overall Remaining Plan

### 1. Finish semantic normalization

- [x] Standardize retry, timeout, and rate-limit handling semantics behind canonical error categories
- [x] Normalize `Retry-After` and retryability metadata where providers expose them
- [x] Stop relying on provider-specific returned error strings as the main failure contract
- [ ] Add provider request lifecycle records for model calls so retries,
      disconnects, completions, cancellations, and failures share one
      observable state machine
- [ ] Replace fixed streaming read-timeout behavior with provider-aware
      timeout/stall policy: bounded connect/write/pool timeouts, long or
      disabled read timeout for active streams, and Penguin-owned cancellation
      watchdogs
- [ ] Normalize incomplete stream handling so a transport close without a
      provider completion event is retryable/disconnected rather than a
      successful empty response

### 2. Finish tool-call and reasoning normalization

- [x] Standardize tool-call payload and interrupt behavior across providers
- [x] Fix the OpenAI/Codex OAuth Responses tool schema mismatch tracked in `context/tasks/openai-codex-oauth-tool-schema-fix.md`
- [x] Normalize reasoning output handling so providers expose the same internal meaning even when wire formats differ
- [x] Normalize finish-reason reporting where it still leaks provider-specific semantics

### 3. Keep quirks at the adapter edge

- [x] Move OpenAI/Responses-specific tool-call orchestration out of `penguin/engine.py`
- [x] Move provider-specific reasoning fallback/debug shaping out of `penguin/web/routes.py`
- [x] Stop using `penguin/core.py` to compensate for provider/runtime-specific tool event naming or metadata gaps
- [ ] Move provider-specific request shaping and response quirks out of shared call sites where possible
- [ ] Keep `Engine` and higher-level runtime code ignorant of provider-specific branching
- [ ] Keep provider-specific native tool replay at the adapter edge while
  consuming canonical `ToolCall` / `ToolResult` records from the tool runtime
- [ ] Add provider-contract coverage for completed, failed, cancelled, and
  interrupted tool-call replay, including provider-specific id normalization
- [ ] Add provider-contract coverage for incomplete stream recovery and
  stream-error turn release
- [ ] Finish the unchecked Phase 2 item: keep provider-specific quirks at the adapter edge

### 4. Expand or consciously narrow coverage

- [x] Decide whether LiteLLM is part of the long-term first-class provider contract or a secondary compatibility path
- [ ] If LiteLLM remains in scope, add the same contract hooks and matrix coverage there
  Deferred until after Phase 5 structural cleanup.
- [ ] Add Link-specific runtime/integration verification on top of the shared provider runtime
  Deferred to Phase 6. Current focus is typical `openai` and `openrouter` behavior.

### 5. Structural cleanup after behavior stabilizes

- [x] Retire `provider_adapters.py`
- [ ] Proceed with `context/tasks/llm-module-consolidation.md`
- [x] Move OpenRouter and LiteLLM gateway implementations under `penguin/llm/adapters/`
- [x] Create a single `penguin/llm/runtime.py` or equivalent orchestration layer that owns canonical provider execution behavior
- [x] Reduce overlapping LLM entry points once semantic parity is in place

### 6. Link Verification

- [ ] Verify Link integration end-to-end on top of the stabilized provider/runtime contract
- [ ] Add Link-specific regression coverage only after typical `openai` and `openrouter` paths are behaving well
- [ ] Validate that Link-specific transport/header behavior does not reintroduce provider contract drift

## Boundary Cleanup Notes

- The first runtime-boundary extraction is now in place, but it is not the end state yet.
- `penguin/llm/runtime.py` currently acts as the transition home for provider/runtime orchestration that previously leaked into `engine.py` and `web/routes.py`.
- `penguin/llm/reasoning_variants.py` now owns provider-aware native reasoning effort support that previously lived under `web/services/`.
- UI/tool presentation mapping should not live in `penguin/llm`; `ui_runtime.py` was an exploratory detour and has been discarded.
- `core.py` still owns UI/OpenCode tool mapping for now.
- OpenRouter/LiteLLM implementations have moved under `penguin/llm/adapters/`, but old import paths remain as temporary compatibility shims.
- `APIClient` is now the primary runtime entry point. `LLMClient` is reduced to a thin Link/config wrapper over `APIClient` rather than a second runtime implementation.
- This should reduce symptom-chasing, but the package is still mid-migration until gateway implementations and remaining helper paths are consolidated under `penguin/llm`.

## Priority Shift

Before more behavior tweaks, the next high-value step is boundary cleanup:

1. move provider-specific orchestration back into `penguin/llm`
2. make higher layers consume only canonical runtime events/results
3. then continue module consolidation from `context/tasks/llm-module-consolidation.md`

## Notes

- The enemy here is not diversity.
- It is invisible inconsistency.
- OpenCode is a useful reference because it centralizes provider execution, transforms, streaming semantics, and retry handling.
- Penguin should copy those structural ideas without inheriting an external SDK lock-in.
