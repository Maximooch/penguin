# ChatGPT Subscription OAuth Checklist

## Goal
Ship reliable ChatGPT Plus/Pro subscription auth for Penguin OpenCode mode using
the currently available Codex-compatible OAuth flow, while keeping migration
paths open if OpenAI later exposes third-party OAuth app registration.

## Baseline Assumptions
- [x] Use compatibility OpenAI OAuth client id by default (`app_EMoamEEZ73f0CkXaXp7hrann`).
- [x] Keep `PENGUIN_OPENAI_OAUTH_CLIENT_ID` env override for future migration.
- [x] Do not block delivery on a Penguin-owned OAuth client id (no public
  self-serve app registration path is currently documented).
- [x] Track OpenAI announcements for third-party OAuth client registration and
  migrate when officially supported.

## Auth Contract Alignment (2026-03-11)

### OpenCode ordering + explicit diagnostics (pre-refactor gate)
- [x] Match OpenCode OpenAI auth method ordering immediately:
  1) `ChatGPT Pro/Plus (browser)`
  2) `ChatGPT Pro/Plus (headless)`
  3) `API key`
- [x] Treat prior Penguin behavior (`method=0 => headless`) as intentionally
  breaking for parity and document migration impact in route/service tests.
- [x] Refactor provider OAuth orchestration to an OpenCode-style
  authorize->pending->callback state machine keyed by provider+method.
- [x] Remove implicit fallback semantics that hide method selection mistakes
  (favor explicit method validation errors).
- [x] Add loud, stage-specific OAuth diagnostics (`authorize`, `poll`,
  `token_exchange`, `callback`) with status codes and provider/method context.
- [x] Lock the behavior with focused tests before layering additional OAuth
  subscription routing work.

## Ship-First Implementation Checklist (Top 5)

### 1) Harden OAuth authorize/callback using compatibility client id
- [x] Keep compatibility client id default and improve observability for which
  client id path is active (default vs env override).
- [x] Add explicit error messages for device auth start/poll/token failures.
- [x] Preserve current provider auth contract and route shapes.

Files:
- `penguin/web/services/provider_auth.py`
- `penguin/web/services/opencode_provider.py`
- `penguin/web/routes.py`

Acceptance:
- OAuth authorize/callback works in Penguin mode without any external app
  registration step.
- Failure modes return actionable diagnostics (status + stage).

### 2) Add refresh-token lifecycle in provider auth service
- [x] Implement refresh exchange helper (`grant_type=refresh_token`) against
  `https://auth.openai.com/oauth/token`.
- [x] Persist refreshed `access`, `refresh`, `expires`, and `accountId` when
  returned.
- [x] Add safe retry/backoff boundaries (no infinite refresh loops).

Files:
- `penguin/web/services/provider_auth.py`
- `penguin/web/services/provider_credentials.py`

Acceptance:
- Expired OAuth sessions can be refreshed without requiring re-login.
- Refreshed tokens are stored and survive restart.

### 3) Wire auto-refresh into OpenAI request path
- [x] Before OpenAI requests, detect OAuth credentials that are expired or near
  expiry and refresh proactively.
- [x] If refresh fails, return a clear "reauth required" error to the UI.
- [x] Ensure API-key path remains unchanged.
- [x] Apply OAuth callback credentials to runtime state immediately so OAuth
  request-path precedence is active without restart.

Files:
- `penguin/llm/adapters/openai.py`
- `penguin/web/services/provider_credentials.py`

Acceptance:
- Long-running Penguin sessions continue across token-expiry boundaries.
- API-key users see no behavior change.

### 4) Route OAuth sessions for subscription-tier behavior
- [x] For OAuth-mode OpenAI sessions, use Codex-compatible backend routing.
- [x] Propagate `Authorization: Bearer <access>` and `ChatGPT-Account-Id` when
  available.
- [x] Keep API-key traffic on standard OpenAI API path.
- [x] Ensure Codex-targeted requests always include top-level `instructions`
  fallback even when system messages are absent.
- [x] Add safe request-shape/error diagnostics for OAuth/Codex 400 debugging.
- [x] Add Codex allowlist model fallback for OAuth sessions so unsupported
  OpenAI models degrade to a known-compatible model instead of failing with
  opaque 400s.
- [x] Make duplicate OAuth callback submissions idempotent when credentials are
  already persisted.
- [x] Serialize OAuth callback processing per provider to prevent concurrent
  token-exchange races from duplicate callback submissions.
- [x] Force list-structured `input` payloads for Codex-routed OpenAI requests,
  matching Codex backend request contract.
- [x] Set `store=false` for Codex-routed OpenAI requests (mirrors OpenCode
  provider transform defaults for OpenAI/OpenAI-compatible providers).
- [x] Enforce explicit OAuth-method payload selection in route requests to avoid
  implicit fallback masking ordering/regression issues.

Files:
- `penguin/llm/adapters/openai.py`
- `penguin/web/services/provider_credentials.py`

Acceptance:
- OAuth mode behaves as subscription-backed access path.
- Account-scoped routing works for org/workspace subscriptions.
- Runtime auth precedence is deterministic: OpenAI OAuth sessions override
  process-level OpenAI API key values in server runtime after OAuth callback.

### 5) Lock correctness with tests + smoke matrix
- [x] Add/expand unit tests for authorize/callback/refresh and account id
  extraction.
- [x] Add adapter tests for route selection (OAuth vs API key) and refresh
  before request.
- [ ] Run manual smoke matrix: fresh login, restart, expiry rollover, logout,
  re-login.

Files:
- `tests/api/test_opencode_provider_service.py`
- `tests/api/test_provider_credentials_service.py`
- `tests/test_openai_adapter_streaming.py`
- (new) `tests/llm/test_openai_oauth_subscription_flow.py`

Acceptance:
- Automated tests cover success + failure branches for refresh and routing.
- Manual smoke pass confirms stable end-to-end behavior.

## OpenCode Reference Points
- OAuth flow + compatibility client id:
  `reference/opencode/packages/opencode/src/plugin/codex.ts`
- Auth storage schema:
  `reference/opencode/packages/opencode/src/auth/index.ts`
- Provider auth route contract:
  `reference/opencode/packages/opencode/src/server/routes/provider.ts`

## External Monitoring / Follow-up
- [ ] Watch for official OpenAI guidance on third-party OAuth client
  registration for Codex/ChatGPT sign-in flows.
- [ ] When available: register Penguin-owned client id, switch default from
  compatibility id, keep compatibility id only as explicit fallback during
  migration window.

## Source Links
- `https://developers.openai.com/codex/auth/`
- `https://developers.openai.com/codex/app-server/`
- `https://github.com/numman-ali/opencode-openai-codex-auth`
- `https://github.com/openai/codex/issues/8338`
