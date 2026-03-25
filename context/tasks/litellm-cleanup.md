# LiteLLM Cleanup TODO

## Objective

- Remove LiteLLM from Penguin's default install path.
- Keep LiteLLM support available only as an explicit opt-in extra.
- Switch Penguin's default remote client path to OpenRouter instead of LiteLLM.
- Preserve backward compatibility for existing `client_preference: litellm` users with clear runtime guidance.

## Progress Snapshot

- [x] Capture the phased LiteLLM removal plan
- [x] Phase A - make LiteLLM an optional dependency extra
- [x] Phase B - switch defaults from LiteLLM to OpenRouter
- [x] Phase C - make missing LiteLLM fail cleanly at runtime
- [x] Phase D - remove LiteLLM as a normal/default path from docs and UX copy
- [ ] Phase E - decide long-term support vs deprecation/removal timeline

## Decisions Locked In

- Penguin's default remote client path should be `openrouter`, not `litellm`.
- LiteLLM should require explicit opt-in via an extra even for broad installs.
- `all` should not include LiteLLM implicitly.
- Existing `client_preference: litellm` configs should continue to parse, but missing-extra failures must be explicit and actionable.

## Checklist

### Phase A - Packaging Split

- [x] Remove `litellm` from base `dependencies`
- [x] Remove `litellm` from `minimal`
- [x] Add `llm_litellm` optional dependency extra
- [x] Ensure `all` does not install LiteLLM implicitly
- [x] Validate that a clean base install can still import Penguin and launch default entrypoints

### Phase B - Default Client Preference

- [x] Change config fallbacks from `litellm` to `openrouter`
- [x] Update setup/wizard defaults to prefer `openrouter`
- [x] Update CLI/interface helper defaults that still assume `litellm`
- [x] Keep `native` for explicit local-provider cases where appropriate

### Phase C - Optional Runtime Support

- [x] Guard LiteLLM imports so missing package errors happen only on use
- [x] Add explicit runtime error messaging for `client_preference: litellm` without the extra installed
- [x] Ensure `import penguin` and default launcher startup do not require LiteLLM
- [x] Keep LiteLLM gateway/tests isolated as optional support paths

### Phase D - Docs and UX Cleanup

- [x] Update README/install docs so LiteLLM is not presented as the normal path
- [x] Update release/install guidance to mention `llm_litellm` only as opt-in
- [x] Update prompt/help/setup messaging that still frames LiteLLM as the default backend

### Phase E - Long-Term Policy

- [ ] Decide whether LiteLLM remains supported indefinitely as an optional extra
- [ ] Or define a timed deprecation/removal policy after one or more stable releases
- [ ] Record the policy in task docs and release notes

## Primary File Map

- `pyproject.toml`
- `penguin/config.py`
- `penguin/config.yml`
- `penguin/setup/wizard.py`
- `penguin/cli/interface.py`
- `penguin/cli/cli.py`
- `penguin/llm/api_client.py`
- `penguin/llm/client.py`
- `penguin/llm/litellm_gateway.py`
- `penguin/core.py`
- `README.md`

## Verification Targets

- `tests/test_opencode_launcher.py`
- `tests/test_cli_entrypoint_dispatcher.py`
- clean install/import smoke test without LiteLLM
- targeted LiteLLM optional-path tests after runtime guards land

## Change Log

### 2026-03-24

- Created phased LiteLLM cleanup checklist.
- Locked the direction that OpenRouter becomes the default remote client path and LiteLLM becomes explicit opt-in only.
- Completed Phase A packaging split.
- Removed LiteLLM from base and `minimal` installs.
- Added explicit `llm_litellm` extra and kept LiteLLM out of `all`.
- Added `tiktoken` to base and `minimal` because clean installs without LiteLLM still require it for import-time token utilities.
- Completed Phase B defaults cleanup.
- Switched config/env/UI fallbacks from LiteLLM to OpenRouter while keeping `native` for explicit local-provider cases.
- Completed Phase C runtime guardrails.
- Added lazy LiteLLM loading helpers and explicit install-hint errors for `client_preference: litellm` when the optional extra is missing.
- Completed most of Phase D docs/help cleanup.
- Updated README and CLI/help-adjacent copy so LiteLLM is framed as an optional extra rather than the default path.

## Implementation Log

- Updated `pyproject.toml` so:
  - base install no longer includes `litellm`
  - `minimal` no longer includes `litellm`
  - `llm_litellm` is the explicit opt-in extra
  - `all` does not pull LiteLLM transitively
- Confirmed a clean base install into a fresh virtualenv has no LiteLLM installed and still supports:
  - `import penguin`
  - `penguin --help`
  - `penguin-web --help`
- Updated default client preference fallbacks in:
  - `penguin/config.py`
  - `penguin/llm/model_config.py`
  - `penguin/setup/wizard.py`
  - `penguin/cli/interface.py`
  - `penguin/cli/cli.py`
- Added `penguin/llm/litellm_support.py` to centralize optional LiteLLM import helpers and install-hint messaging.
- Updated:
  - `penguin/llm/api_client.py`
  - `penguin/llm/client.py`
  - `penguin/llm/litellm_gateway.py`
  - `penguin/llm/openai_assistant.py`
  so missing LiteLLM now fails only on explicit use with a clear opt-in install hint.
- Updated README guidance so LiteLLM is described as an optional extra (`llm_litellm`) instead of a default dependency.
- Added explicit release/install runbook guidance for optional LiteLLM installs via `penguin-ai[llm_litellm]`.

## Verification Log

- `python -m pytest -q tests/test_opencode_launcher.py tests/test_cli_entrypoint_dispatcher.py`
  - result: `23 passed`
- Clean install smoke test:
  - `python3 -m venv /tmp/penguin-litellm-phasea`
  - `/tmp/penguin-litellm-phasea/bin/pip install -e .`
  - `importlib.util.find_spec("litellm") -> None`
  - `import penguin` succeeded
  - `/tmp/penguin-litellm-phasea/bin/penguin --help` succeeded
  - `/tmp/penguin-litellm-phasea/bin/penguin-web --help` booted successfully
- `python -m pytest -q tests/test_litellm_cleanup.py tests/test_opencode_launcher.py tests/test_cli_entrypoint_dispatcher.py`
  - result: `27 passed`
- Real clean-install runtime check without LiteLLM:
  - explicit `client_preference='litellm'` now raises a clear runtime error with `penguin-ai[llm_litellm]` install guidance instead of an import-time crash
