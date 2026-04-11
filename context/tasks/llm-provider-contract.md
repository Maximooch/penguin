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
- `penguin/llm/provider_adapters.py`
- `penguin/llm/openrouter_gateway.py`
- `penguin/llm/litellm_gateway.py`
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

Important constraint:

- adopt the architecture, not the dependency; Penguin should remain provider-agnostic and local-inference-friendly rather than coupling itself to Vercel's AI SDK
- provider-specific behavior must live in `penguin/llm` provider modules and shared LLM runtime layers, not in `engine.py`, `core.py`, `web/routes.py`, or tool implementations

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
- [ ] Finish the unchecked Phase 2 item: keep provider-specific quirks at the adapter edge

### 4. Expand or consciously narrow coverage

- [x] Decide whether LiteLLM is part of the long-term first-class provider contract or a secondary compatibility path
- [ ] If LiteLLM remains in scope, add the same contract hooks and matrix coverage there
  Deferred until after Phase 5 structural cleanup.
- [ ] Add Link-specific runtime/integration verification on top of the shared provider runtime
  Deferred to Phase 6. Current focus is typical `openai` and `openrouter` behavior.

### 5. Structural cleanup after behavior stabilizes

- [ ] Retire `provider_adapters.py`
- [ ] Proceed with `context/tasks/llm-module-consolidation.md`
- [ ] Move OpenRouter and LiteLLM gateway implementations under `penguin/llm/adapters/`
- [ ] Create a single `penguin/llm/runtime.py` or equivalent orchestration layer that owns canonical provider execution behavior
- [ ] Reduce overlapping LLM entry points once semantic parity is in place

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
