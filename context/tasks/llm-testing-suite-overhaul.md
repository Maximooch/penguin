# LLM Testing Suite Overhaul TODO

## Objective

- Turn `penguin/llm` testing into a layered, trustworthy suite instead of a pile of partially overlapping checks.
- Separate mocked contract tests, transport integration tests, and opt-in live provider smoke tests.
- Make it obvious which failures indicate real runtime regressions versus outdated fixtures, shim breakage, or provider-catalog drift.

## Why This Exists

- The recent provider-contract work added meaningful coverage, but the suite still mixes concerns.
- Some tests are true unit/contract tests with stubs and monkeypatching.
- Some are runtime integration tests.
- Some files inside `penguin/llm/` are ad hoc or historical and blur the line between package code and test code.
- When the suite is not clearly stratified, confidence drops and people stop trusting failures.

## Branch Review Reality Check

A few things became clear during review:

- The failing OpenRouter compatibility tests are mocked shim/interface tests, not live network failures.
- Model deprecation is not the cause of those failures; the break is a missing compatibility symbol on the shim module.
- Several test fixture model IDs are just identifiers used in mocked paths, not proof of live model selection.
- Live-model coverage should exist, but it should be explicit, env-gated, and cheap.

## Audit Evidence

- `tests/llm/provider_contract_fixtures.py`
- `tests/llm/test_provider_contract_matrix.py`
- `tests/llm/test_provider_registry.py`
- `tests/llm/test_llm_client_contract.py`
- `tests/llm/test_link_runtime_contract.py`
- `tests/llm/test_openrouter_base_url_isolation.py`
- `tests/test_engine_responses_tool_calls.py`
- `tests/test_engine_responses_tool_action_results.py`
- `tests/test_engine_reasoning_fallback.py`
- `penguin/llm/test_openrouter_gateway.py`
- `penguin/llm/test_litellm_gateway.py`
- `context/tasks/llm-provider-contract.md`
- `context/tasks/llm-runtime-package-hygiene.md`

## Current Problems

- Test boundaries are fuzzy.
- Legacy compatibility shims are not consistently covered as public API surfaces.
- Some model IDs in tests are stale or arbitrary, which is fine for mocks but confusing when not labeled clearly.
- Runtime package directories still contain test-like files, making ownership murkier.
- There is no crisp contract for what must pass offline versus what is allowed to depend on credentials/network/provider availability.

## Suite Design Goal

Define three explicit layers.

### Layer 1 - Offline Contract Tests
These should run in CI with no credentials and no network.

Scope:
- provider contract matrix
- request/response normalization
- finish reasons, usage accessors, retry metadata
- tool-call replay behavior
- reasoning extraction/visibility behavior
- compatibility shim surface where monkeypatching/import compatibility matters

Properties:
- deterministic
- fast
- no external dependencies except installed Python packages
- failing here means Penguin changed, not the internet

### Layer 2 - Local Integration Tests
These validate Penguin runtime composition without calling live providers.

Scope:
- `APIClient` + `ProviderRegistry` + adapters under mocked SDK clients
- `LLMClient` runtime reconfiguration behavior
- Link header injection
- OpenRouter/OpenAI-compatible base URL isolation
- engine/runtime orchestration around tool calls and empty-response fallback

Properties:
- still offline
- broader than unit tests
- focused on cross-module behavior

### Layer 3 - Live Smoke Tests
These are opt-in and env-gated.

Scope:
- one or two cheap real requests per provider path
- verify credentials, transport wiring, and minimally sane streaming/tool behavior
- confirm current catalog model IDs actually work

Properties:
- never required for basic local development
- not part of the default unit suite
- clearly marked, rate-limited, and cost-conscious

## Model Strategy

The suite currently mixes three kinds of model identifiers:

1. **Mock fixture identifiers**
   - fine to use stable fake-ish IDs if behavior is mocked
   - must be labeled clearly as mocked

2. **Canonical example IDs**
   - useful for parser/provider normalization tests
   - should be current enough to represent real naming patterns

3. **Live smoke IDs**
   - must be curated and periodically refreshed
   - should prefer cheap, currently available models

Recommended default live-smoke candidates:
- OpenRouter cheap default: `z-ai/glm-5.1`
- Anthropic cheap default: `anthropic/claude-haiku-4.5`
- OpenAI/OpenAI-compatible: one current inexpensive GPT path if actually exercised in live mode

Do not use live-provider availability as a reason to contaminate offline tests.

## Progress Snapshot

- [ ] Inventory all `penguin/llm` and `tests/llm` test files by layer
- [ ] Mark offline versus live tests explicitly
- [ ] Add coverage for compatibility shims as public import surfaces
- [ ] Reduce ambiguity around fixture model IDs
- [ ] Define a cheap, curated live-smoke matrix
- [ ] Move stray package-internal tests or artifacts to consistent locations

## Checklist

### Phase 1 - Inventory and Classification
- [ ] List every LLM-related test file under `tests/` and `penguin/llm/`
- [ ] Tag each as unit/contract, local integration, live smoke, manual debug, or dead weight
- [ ] Identify duplicated coverage and missing coverage
- [ ] Identify tests that should move out of runtime packages into `tests/`

### Phase 2 - Suite Boundaries
- [ ] Define pytest markers such as:
  - `llm_contract`
  - `llm_integration`
  - `llm_live`
  - `llm_manual`
- [ ] Document what each marker means and when it should run
- [ ] Ensure default CI path excludes live tests unless explicitly enabled

### Phase 3 - Contract Hardening
- [ ] Keep the provider contract matrix fully offline and deterministic
- [ ] Add explicit tests for compatibility shims (`openrouter_gateway`, `litellm_gateway`) if those modules remain public
- [ ] Add regression tests for model-config ownership and state leakage
- [ ] Add tests that pin canonical runtime events consumed by higher layers

### Phase 4 - Live Smoke Matrix
- [ ] Add env-gated live smoke tests for:
  - native Anthropic
  - native OpenAI or OpenAI-compatible
  - OpenRouter
- [ ] Pick cheap, current models and centralize them in one config/helper
- [ ] Add one command/doc path for running live smoke tests locally
- [ ] Track expected cost and failure modes explicitly

### Phase 5 - Hygiene and Trust
- [ ] Move ad hoc package-internal test files into `tests/` or `misc/` as appropriate
- [ ] Delete fossils that no longer serve a purpose
- [ ] Make the suite output explain what kind of failure occurred: contract, integration, or live-provider
- [ ] Update contributor docs so people know which suite to trust for what

## Verification Targets

- `tests/llm/test_provider_contract_matrix.py`
- `tests/llm/test_provider_registry.py`
- `tests/llm/test_llm_client_contract.py`
- `tests/llm/test_link_runtime_contract.py`
- `tests/llm/test_openrouter_base_url_isolation.py`
- `tests/test_engine_responses_tool_calls.py`
- `tests/test_engine_responses_tool_action_results.py`
- `tests/test_engine_reasoning_fallback.py`
- any new live smoke entrypoint/tests added for curated providers

## Concrete Deliverables

- a written test taxonomy for `penguin/llm`
- pytest markers and docs for offline/integration/live classes
- centralized live-smoke model selection
- shim compatibility tests for any public compatibility modules
- cleanup plan for `penguin/llm/test_*.py` files living inside the runtime package

## Notes

- A flaky or ambiguous test suite is not neutral; it actively trains people to ignore failures.
- The goal is not maximal test count. The goal is believable signal.
