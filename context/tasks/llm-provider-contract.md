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

## Progress Snapshot

- [x] Document current provider contract drift
- [x] Define a canonical request/response/streaming abstraction
- [ ] Standardize retry, timeout, and rate-limit handling semantics
- [ ] Standardize tool-call and reasoning-token behavior across providers
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
- `tests/llm/provider_contract_fixtures.py`
- `tests/llm/test_provider_contract_matrix.py`
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

- [ ] Standardize retry, timeout, and rate-limit handling semantics behind canonical error categories
- [ ] Normalize `Retry-After` and retryability metadata where providers expose them
- [ ] Stop relying on provider-specific returned error strings as the main failure contract

### 2. Finish tool-call and reasoning normalization

- [ ] Standardize tool-call payload and interrupt behavior across providers
- [ ] Fix the OpenAI/Codex OAuth Responses tool schema mismatch tracked in `context/tasks/openai-codex-oauth-tool-schema-fix.md`
- [ ] Normalize reasoning output handling so providers expose the same internal meaning even when wire formats differ
- [ ] Normalize finish-reason reporting where it still leaks provider-specific semantics

### 3. Keep quirks at the adapter edge

- [ ] Move provider-specific request shaping and response quirks out of shared call sites where possible
- [ ] Keep `Engine` and higher-level runtime code ignorant of provider-specific branching
- [ ] Finish the unchecked Phase 2 item: keep provider-specific quirks at the adapter edge

### 4. Expand or consciously narrow coverage

- [ ] Decide whether LiteLLM is part of the long-term first-class provider contract or a secondary compatibility path
- [ ] If LiteLLM remains in scope, add the same contract hooks and matrix coverage there
- [ ] Add Link-specific runtime/integration verification on top of the shared provider runtime

### 5. Structural cleanup after behavior stabilizes

- [ ] Retire `provider_adapters.py`
- [ ] Proceed with `context/tasks/llm-module-consolidation.md`
- [ ] Reduce overlapping LLM entry points once semantic parity is in place

## Notes

- The enemy here is not diversity.
- It is invisible inconsistency.
- OpenCode is a useful reference because it centralizes provider execution, transforms, streaming semantics, and retry handling.
- Penguin should copy those structural ideas without inheriting an external SDK lock-in.
