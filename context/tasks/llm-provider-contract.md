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
- `penguin/llm/provider_adapters.py`
- `penguin/llm/openrouter_gateway.py`
- `penguin/llm/litellm_gateway.py`
- `penguin/llm/stream_handler.py`
- `tests/test_api_client.py`
- provider-specific test files under `tests/` and `penguin/llm/`

## Progress Snapshot

- [ ] Document current provider contract drift
- [ ] Define a canonical request/response/streaming abstraction
- [ ] Standardize retry, timeout, and rate-limit handling semantics
- [ ] Standardize tool-call and reasoning-token behavior across providers
- [ ] Build a shared contract test matrix
- [ ] Gate provider implementations against the same expectations

## Checklist

### Phase 1 - Contract Audit
- [ ] Compare provider behavior for:
  - request shaping
  - streaming chunk assembly
  - tool call payloads
  - finish reasons
  - usage/token accounting
  - retry/failure handling
- [ ] Document mismatches and intentional exceptions

### Phase 2 - Canonical Contract
- [ ] Define provider-agnostic types/interfaces
- [ ] Centralize normalization where possible
- [ ] Keep provider-specific quirks at the adapter edge

### Phase 3 - Validation
- [ ] Add contract tests each provider must pass
- [ ] Add explicit fixtures for streaming + tool-call edge cases
- [ ] Add reasoning-token cases where relevant

## Verification Targets

- `tests/test_api_client.py`
- OpenRouter-specific tests
- LiteLLM cleanup/runtime tests
- streaming tests
- provider adapter tests

## Notes

- The enemy here is not diversity.
- It is invisible inconsistency.
