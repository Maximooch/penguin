# OpenRouter Auth Runtime Hotfix

## Goal

- Ensure `penguin-web` can use persisted OpenRouter credentials immediately at startup.
- Prevent stale or unrelated runtime client state from causing missing auth headers.
- Isolate OpenRouter base URL resolution from native OpenAI/Codex configuration.

## Problem

- Persisted provider credentials were applied after core/API client creation.
- Active runtime clients were not rebuilt after auth changes.
- OpenRouter inherited `OPENAI_BASE_URL`, which could contaminate gateway routing.
- A placeholder stored OpenRouter key could overwrite a real env-backed key during rehydration.

## Immediate Changes

- Prime persisted provider credentials into environment variables before `Config.load_config()` and API client creation.
- Rebuild the active runtime API client after auth writes or OAuth completion when the current model depends on that provider.
- Restrict OpenRouter base URL resolution to explicit OpenRouter inputs and defaults.
- Ignore known placeholder/test OpenRouter credentials so they do not shadow real runtime auth.

## Files

- `penguin/web/app.py`
- `penguin/web/routes.py`
- `penguin/web/services/provider_credentials.py`
- `penguin/core.py`
- `penguin/llm/openrouter_gateway.py`

## Follow-Up

- Fold provider bootstrapping and client refresh semantics into the shared provider contract work in `context/tasks/llm-provider-contract.md`.
