# LLM Module Consolidation

## Goal

- Reduce the active top-level surface area of `penguin/llm/`.
- Remove overlapping entry points and legacy compatibility layers after the provider contract is stabilized.
- Keep Link as a first-class integration with its own dedicated module/file.

## Why This Exists

- `penguin/llm/` currently has too many active top-level runtime files.
- The problem is not just file count.
- It is overlapping responsibilities:
  - runtime entry points
  - provider resolution
  - provider normalization
  - legacy fallbacks
  - transport/platform integration
  - provider implementations
  - streaming state management

That makes the package harder to reason about, harder to extend, and easier to break.

## Relationship To `llm-provider-contract.md`

This is a follow-on task to `context/tasks/llm-provider-contract.md`.

It should happen after the provider contract behavior is stabilized enough that consolidation is moving settled logic rather than shuffling active drift.

Practical sequencing:

1. finish contract behavior normalization
2. add/lock contract tests
3. consolidate top-level module structure
4. retire legacy paths

## Important Constraint

- Link should retain a dedicated module/file.
- It should not be collapsed into a generic runtime file if that makes the Link integration harder to understand or evolve.
- `client.py` may be the wrong name long-term, but a Link-focused module is justified.

Possible future names:

- `link_runtime.py`
- `link_client.py`
- `link_transport.py`

## Current Problematic Top-Level Files

Active or semi-active files currently include:

- `api_client.py`
- `client.py`
- `contracts.py`
- `litellm_gateway.py`
- `litellm_support.py`
- `model_config.py`
- `openrouter_gateway.py`
- `provider_adapters.py`
- `provider_registry.py`
- `provider_transform.py`
- `stream_handler.py`

The package currently exposes too many top-level concepts that should either be:

- consolidated
- moved under `adapters/`
- or retired

## Likely Consolidation Targets

### Keep at top level

- `model_config.py`
- `contracts.py`
- one main runtime/public entrypoint module
- one streaming/state module if it remains clearly separate
- one Link-focused integration module
- `litellm_support.py` only if LiteLLM remains an optional extra

### Move under `adapters/` or equivalent

- `openrouter_gateway.py`
- `litellm_gateway.py`

These are provider implementations more than top-level package concepts.

### Retire

- `provider_adapters.py`

This is legacy drift in code form and should be a strong deletion target.

### Reevaluate after contract work settles

- `api_client.py`
- `provider_registry.py`
- `provider_transform.py`
- `client.py`

The goal is not to delete these blindly.
The goal is to end with one obvious runtime path, one obvious provider-resolution path, and one clear Link integration path.

## Preferred End State

Illustrative target layout:

```text
penguin/llm/
  __init__.py
  contracts.py
  model_config.py
  runtime.py
  stream_handler.py
  link_runtime.py        # or similar Link-focused name
  litellm_support.py
  adapters/
    __init__.py
    base.py
    openai.py
    openai_compatible.py
    anthropic.py
    openrouter.py
    litellm.py
    ollama.py
```

This is directionally correct, not a mandatory exact tree.

## Consolidation Principles

- one obvious public runtime path
- one obvious provider registry/resolver path
- provider-specific implementations live at the adapter edge
- Link remains a dedicated integration concern
- legacy compatibility code should be removed, not preserved forever
- avoid moving files before behavior is covered by contract tests

## Suggested Phases

### Phase 1 - Preconditions

- [ ] Finish canonical provider contract behavior work
- [ ] Add/lock provider contract tests
- [ ] Confirm which current files are still actively used versus compatibility-only

### Phase 2 - Structural Cleanup

- [ ] Retire `provider_adapters.py`
- [ ] Move gateway-style provider implementations under `adapters/`
- [ ] Decide whether `api_client.py` survives as the main runtime or becomes a compatibility shim
- [ ] Decide final Link-focused module name and responsibility boundary
- [ ] Merge or remove thin wrapper layers that no longer add distinct value

### Phase 3 - Public Surface Cleanup

- [ ] Reduce top-level `penguin/llm` exports to the core public API
- [ ] Update imports across the codebase
- [ ] Delete dead compatibility paths
- [ ] Update docs and architecture references

## Verification Targets

- provider contract tests
- streaming tests
- Link integration tests
- model/provider resolution tests
- API/web integration paths that instantiate LLM runtimes

## Notes

- This should not become a broad rename exercise with no architectural payoff.
- The target is fewer overlapping concepts, not fewer files at any cost.
- Link is important enough to justify its own dedicated module even in a more consolidated LLM package.
