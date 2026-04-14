# ModelConfig Mutation State-Leak Investigation TODO

## Objective

- Eliminate hidden mutation of caller-owned `ModelConfig` instances during provider/runtime resolution.
- Prevent sticky transport state such as `api_base`, provider normalization, or model canonicalization from leaking across requests.
- Define a clear ownership rule: resolution may derive a normalized config, but it should not silently rewrite shared caller state.

## Why This Exists

- The new provider contract and registry work centralized resolution logic, which is good.
- It also appears to centralize mutation in a dangerous place: handler resolution currently mutates the passed `ModelConfig` in place.
- That creates cross-request state bleed, especially when the same config object is reused across calls, clients, sessions, or tests.
- These bugs are path-dependent and low-visibility: one earlier call can quietly poison later behavior.

## Audit Evidence

- `penguin/llm/provider_transform.py`
- `penguin/llm/provider_registry.py`
- `penguin/llm/api_client.py`
- `penguin/llm/client.py`
- `penguin/llm/model_config.py`
- `tests/test_llm_api_client_model_canonicalization.py`
- `tests/llm/test_provider_registry.py`

## Current Risk Shape

Observed behavior during branch review:

- `apply_model_config_transforms()` normalizes `provider`, `client_preference`, and `model` in place.
- `ProviderRegistry.create_handler()` then conditionally writes `model_config.api_base` in place.
- Reusing the same `ModelConfig` object across calls can preserve a prior proxy/base URL unexpectedly.
- A first request with `base_url="https://proxy-one.example/v1"` can affect a later request that did not ask for that base URL.

That is a real state leak, not a style nit.

## Desired Invariants

- Caller-owned `ModelConfig` should be treated as input, not scratch space.
- Resolution should be referentially safe:
  - same config in, same config out unless the caller explicitly mutates it
  - handler creation should not persist transport-specific state back onto shared config objects
- Canonicalization should be deterministic and testable without mutating the original object.
- Runtime-specific overrides (`api_base`, Link headers, provider aliases, native-model stripping) should remain scoped to the derived runtime instance.

## Progress Snapshot

- [ ] Confirm all in-place mutations along the provider/runtime path
- [ ] Decide whether `ModelConfig` should be immutable, copy-on-write, or selectively cloned in resolution
- [ ] Remove sticky `api_base` leakage across repeated handler creation
- [ ] Add regression coverage for config reuse across multiple calls/clients/providers
- [ ] Document the ownership semantics clearly

## Checklist

### Phase 1 - Full Mutation Audit
- [ ] Enumerate every place `ModelConfig` is mutated in `penguin/llm`
- [ ] Separate benign initialization-time mutation from dangerous runtime mutation
- [ ] Trace which call paths reuse the same config instance across requests
- [ ] Confirm whether any UI/core/session code depends on the current mutation side effects

### Phase 2 - Ownership Decision
- [ ] Choose one model explicitly:
  - immutable `ModelConfig`
  - copy-on-write normalization in registry/runtime
  - narrow derived runtime config object separate from `ModelConfig`
- [ ] Reject halfway fixes that leave shared-state ambiguity in place
- [ ] Prefer the smallest fix that restores sane ownership boundaries

### Phase 3 - Implementation
- [ ] Stop mutating caller-owned config inside shared transforms/resolvers
- [ ] Move `api_base` and related transport overrides onto derived runtime state
- [ ] Ensure canonical model-name normalization does not rewrite the caller object unexpectedly
- [ ] Preserve existing runtime behavior for handler selection and request shaping

### Phase 4 - Regression Coverage
- [ ] Add test: repeated `ProviderRegistry.create_handler()` calls with one shared config and different `base_url` values
- [ ] Add test: `APIClient` creation does not permanently rewrite shared config state
- [ ] Add test: `LLMClient.update_config()` changes transport without contaminating unrelated later requests
- [ ] Add test: native model canonicalization returns expected derived value without mutating original input unexpectedly
- [ ] Add test: mixed provider/client-preference resolution does not leak normalization across cases

## Verification Targets

- `tests/llm/test_provider_registry.py`
- `tests/test_llm_api_client_model_canonicalization.py`
- `tests/llm/test_llm_client_contract.py`
- new targeted regression tests for config reuse/state leakage
- targeted runtime smoke tests for OpenAI/OpenRouter/native-compatible resolution paths

## Likely Fix Directions

### Option A - Defensive Copy in Registry
- Copy `ModelConfig` before applying transforms or transport overrides.
- Lowest-risk surgical fix.
- Good default if the goal is fast stabilization.

### Option B - Pure Transform Functions
- Refactor shared normalization helpers to return derived values or a copied config.
- Better architecture than in-place rewriting.
- Slightly broader touch surface.

### Option C - Separate Runtime Request Config
- Keep `ModelConfig` as durable model metadata.
- Introduce a derived runtime config/request config for transport and provider-resolution state.
- Cleanest model long-term, but broader than a hotfix.

## Recommendation

Start with Option A or B, not C, unless adjacent refactors are already happening.

This problem is about ownership and side effects, not lack of abstraction. Do not build a cathedral to fix a leaking pipe.

## Notes

- The direct-use path can appear fine while this bug still exists because state leaks are path-dependent.
- That is exactly why regression coverage matters here.
