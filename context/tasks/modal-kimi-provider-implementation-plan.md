# Modal / Kimi K3 Provider Implementation Plan

**Goal:** Add Modal as a first-class Penguin LLM provider, initially with a Kimi K3 preset, using Modal's OpenAI Chat Completions-compatible API without misrepresenting Modal as OpenRouter or routing it through OpenAI Responses.

**Architecture:** Separate the shared OpenAI Chat Completions wire protocol from OpenRouter-specific routing/authentication. Implement Modal as a thin route/provider configuration on that shared protocol: Modal owns endpoint selection, authentication headers, provider identity, capability defaults, configuration, and diagnostics; the shared protocol owns Chat Completions request construction, SSE parsing, tool-call fragment assembly, usage, finish reasons, and error normalization. Keep the first implementation scoped to Modal's documented Chat Completions behavior and do not advertise reasoning or native tool support until contract tests and an opt-in smoke test establish them.

**Constraints:**

- Modal Kimi K3 is not an OpenRouter model in this integration; never require OpenRouter model-spec lookup for it.
- Modal's documented endpoint protocol is OpenAI **Chat Completions** (`/v1/chat/completions`), not OpenAI Responses (`/v1/responses`).
- Modal authenticated Auto Endpoints require `Modal-Key` and `Modal-Secret` headers; do not reduce this pair to a generic single API key.
- Modal proxy-token IDs (`wk-…`) and secrets (`ws-…`) are not Modal API tokens and must not be sent as an `Authorization: Bearer …` value. Accept and emit only the documented two-header scheme for proxy-token endpoint mode.
- Provider-specific behavior stays under `penguin/llm` and provider web services—not `engine.py`, `core.py`, or `web/routes.py`.
- Default proof must be deterministic and offline. A live Modal test is opt-in only.
- Any local process smoke test must use `HOST=127.0.0.1 PORT=8080` (or another explicitly selected non-9000, non-5xxx port). Do not bind the documented/default port 9000.
- Avoid a Kimi-only abstraction. `modal` is the provider; `moonshotai/Kimi-K3` is an initial model preset.

**Relevant existing boundaries:**

- `penguin/llm/provider_registry.py` chooses native, OpenRouter, LiteLLM, and Link handlers.
- `penguin/llm/adapters/openai.py` is Responses API-specific even when used through `openai_compatible`; it is not suitable for Modal's Chat Completions route.
- `penguin/llm/adapters/openrouter.py` already implements much of the desired Chat Completions wire behavior, but currently combines that protocol with OpenRouter identity, credentials, request defaults, and diagnostics.
- `penguin/core_runtime/model_runtime.py` resolves models and currently fetches OpenRouter specs whenever the provider/client preference is OpenRouter.
- `penguin/web/services/provider_credentials.py` currently favors one-key API credential records and needs a safe structured record for Modal proxy-token credentials.
- `penguin/web/services/provider_catalog.py` supplies provider metadata, discovery, and configured model information to web/TUI clients.
- `tests/llm/test_provider_contract_matrix.py` is the main deterministic provider behavior gate and must remain authoritative over a single live request.

---

## Acceptance Criteria

1. A config entry with `provider: modal`, `client_preference: native`, and a Modal `/v1` `api_base` resolves without any OpenRouter spec fetch.
2. Modal requests use the OpenAI Chat Completions request family and never the Responses API.
3. Modal Auto Endpoint proxy credentials send exactly `Modal-Key` and `Modal-Secret`, never an OpenRouter authorization header.
4. Secrets are absent from prepared-request body/diagnostics, runtime event payloads, errors, and logs.
5. Streaming text, terminal finish reason, usage normalization, provider failures, and incomplete-stream behavior meet the existing provider contract.
6. Native tool support and reasoning are disabled/capability-gated until their Modal wire behavior is explicitly proven.
7. Kimi K3 is selectable through a documented config preset with Modal-appropriate context/vision defaults.
8. Unit and contract tests require no real provider, no credentials, and no local server. If a local smoke test is added, it runs on port 8080—not port 9000.
9. A first-time TUI user can choose **Modal**, enter the minimum connection details in the TUI, and select **Kimi K3** without editing YAML or manually constructing a model configuration.

---

## Required TUI Connection Experience

The product outcome is not merely that a Modal `model_config` works. A user
should be able to discover, connect, and select Modal/Kimi K3 entirely in the
Penguin TUI.

### Target flow

1. In the model picker, choose **Connect provider**.
2. Select **Modal** from the provider list.
3. Select a connection type:
   - **Modal Shared API — Kimi K3** (preferred zero-endpoint-setup path, once
     its currently undocumented credential/base-URL contract is verified); or
   - **My Modal Auto Endpoint** (endpoint URL plus proxy token pair).
4. For an Auto Endpoint, enter:
   - endpoint URL (validated as an HTTPS URL and normalized to the `/v1` base);
   - proxy token ID (`Modal-Key`); and
   - proxy token secret (`Modal-Secret`).
5. Persist the structured credential record, apply it safely to the active
   runtime, refresh the catalog, then open Modal's model picker directly.
6. Show `Kimi K3` as the default bundled Modal model. Do not make the user
   know or type `moonshotai/Kimi-K3` merely to get started.

### Implementation boundary

`penguin-tui` already receives provider/auth metadata from Penguin and has a
generic one-field API-key dialog. That existing UI cannot correctly collect a
Modal proxy-token pair or an endpoint URL. Do **not** disguise the pair as one
API key or push that burden into YAML.

Add a narrow backend-described credential form contract, initially for Modal,
for example:

```json
{
  "modal": [
    {
      "type": "fields",
      "label": "Modal Auto Endpoint",
      "fields": [
        {"name": "endpoint_url", "label": "Endpoint URL", "secret": false},
        {"name": "proxy_token_id", "label": "Proxy token ID", "secret": true},
        {"name": "proxy_token_secret", "label": "Proxy token secret", "secret": true}
      ]
    }
  ]
}
```

The TUI should render this via one reusable multi-field dialog rather than a
Modal-only pile of conditional prompts. The backend remains authoritative for
field validation, credential persistence, redaction, connection state, default
models, and all provider behavior. This is intentionally a small extension of
the existing OpenCode-compatible provider-auth flow, not a copy of OpenCode's
provider runtime.

### Scope guard

Do not have Penguin create or bill for Modal endpoints in the first release.
The Auto Endpoint path accepts a user-owned endpoint. The Shared API path is
the preferred UX only after its exact current service URL and authentication
scheme are confirmed from Modal's primary documentation or a user-provided
account flow.

---

## Proposed Configuration Surface

Start with explicit configuration rather than endpoint discovery or automatic deployment provisioning:

```yaml
model_configs:
  modal/moonshotai-kimi-k3:
    model: moonshotai/Kimi-K3
    provider: modal
    client_preference: native
    api_base: https://<your-modal-endpoint>/v1
    max_context_window_tokens: 1000000
    vision_enabled: true
    streaming_enabled: true
    # Do not set reasoning_enabled or native-tool capability optimistically.
```

Use one of two documented credential modes, subject to final confirmation of the Modal Shared API auth scheme:

```bash
# Auto Endpoint / proxy-token mode
export MODAL_PROXY_TOKEN_ID="..."
export MODAL_PROXY_TOKEN_SECRET="..."

# Shared API mode (name/value only after Modal's current auth contract is verified)
export MODAL_API_KEY="..."
```

The implementation should select the mode explicitly (`auth_mode: proxy_token | shared_api`) or infer proxy-token mode only when both proxy environment variables are present. It must fail closed if a selected mode is missing part of its credential set.

---

## Step-by-Step Plan

### Task 1: Freeze Modal's actual wire contract before coding

**Objective:** Avoid designing against a stale or inferred Modal authentication/capability contract.

**Files:**
- Modify: `context/tasks/modal-kimi-provider-implementation-plan.md` only if confirmed facts differ materially.
- Reference: `https://modal.com/library/moonshot/kimi-k3`
- Reference: `https://modal.com/docs/guide/endpoints`

**Steps:**
1. Confirm the Modal Shared API base URL, exact authentication header/token scheme, Kimi K3 model ID, and whether it supports streaming, images, Chat Completions tools, and any reasoning control.
2. Confirm the Auto Endpoint route is `/v1/chat/completions` and proxy-token mode remains `Modal-Key` plus `Modal-Secret`.
3. Record only supported request parameters. Do not propagate OpenRouter's `reasoning` request object without Modal documentation or a recorded successful contract test.
4. Decide which auth mode is in scope for the first PR:
   - preferred: Auto Endpoint proxy-token mode plus config-defined `api_base`;
   - optional: Shared API when its exact auth contract is confirmed;
   - out of scope: deploying/managing Modal endpoints from Penguin.

**Verification:** Link each implemented request/header behavior to a current Modal source or an opt-in recorded integration fixture. This research step is not a reason to add a network dependency to normal tests.

---

### Task 2: Add failing provider-resolution tests for Modal

**Objective:** Establish that Modal resolves as its own native provider without OpenRouter model lookup.

**Files:**
- Modify: `tests/llm/test_provider_registry.py`
- Modify: `tests/core_runtime/test_model_runtime.py` or the existing focused model-runtime test file discovered during implementation
- Reference: `penguin/llm/provider_registry.py`
- Reference: `penguin/core_runtime/model_runtime.py`

**Steps:**
1. Add a registry test mirroring the existing `openai_compatible` native-routing test:
   - configure `ModelConfig(model="moonshotai/Kimi-K3", provider="modal", client_preference="native")`;
   - monkeypatch the future `ModalAdapter`;
   - assert the adapter receives provider `modal`, the unmodified model ID, and config `api_base`.
2. Add a runtime-resolution test with a fake `fetch_specs` callback that raises if called.
3. Resolve a Modal K3 config and assert:
   - the callback was not called;
   - provider is `modal`;
   - client preference stays `native`;
   - context/output limits come from configured values, not remote OpenRouter metadata.
4. Run the two focused tests and confirm they fail before implementation for the expected missing route/provider behavior.

**Commands:**

```bash
pytest -q tests/llm/test_provider_registry.py -k modal
pytest -q tests/core_runtime/test_model_runtime.py -k modal
```

**Expected initially:** failure because `modal` is not mapped to a native adapter and/or lacks resolution coverage.

---

### Task 3: Extract the reusable OpenAI Chat Completions protocol from OpenRouter

**Objective:** Reuse the protocol behavior Modal needs without cloning or relabeling the OpenRouter adapter.

**Files:**
- Create: `penguin/llm/adapters/openai_chat_completions.py`
- Modify: `penguin/llm/adapters/openrouter.py`
- Modify: `tests/llm/test_provider_contract_matrix.py`
- Modify/Create: the smallest existing adapter-specific fixture/test module needed for protocol preparation tests

**Steps:**
1. Identify the portions of `OpenRouterGateway` that are transport/protocol-neutral:
   - message/vision conversion;
   - Chat Completions body creation;
   - normal and streamed completion parsing;
   - stream SSE handling;
   - tool-call fragment accumulation;
   - usage and finish-reason normalization;
   - request lifecycle updates.
2. Move only those elements into a narrowly named shared base/protocol class. Keep it independent of:
   - `OPENROUTER_API_KEY` lookup;
   - OpenRouter base URL defaults;
   - OpenRouter HTTP attribution headers;
   - `provider="openrouter"` diagnostics/routes/lifecycle IDs;
   - OpenRouter-specific reasoning fields and debug behavior.
3. Have the existing OpenRouter adapter subclass/configure the new protocol with its existing OpenRouter route/auth/body overlay. Preserve current public imports and compatibility shims.
4. Add preparation/stream fixtures that prove the extracted base preserves the current OpenRouter request body and normalized streamed result behavior byte-for-byte where intended.
5. Run the existing OpenRouter contract matrix before adding Modal. Extraction is incomplete if known provider behavior changes.

**Commands:**

```bash
pytest -q tests/llm/test_provider_contract_matrix.py -k openrouter
pytest -q tests/llm/test_provider_registry.py
ruff check penguin/llm/adapters/openai_chat_completions.py penguin/llm/adapters/openrouter.py
ruff format --check penguin/llm/adapters/openai_chat_completions.py penguin/llm/adapters/openrouter.py
```

**Expected:** all existing OpenRouter tests still pass. No duplicated full OpenRouter adapter should be created.

---

### Task 4: Define Modal credentials and header construction with redaction-first tests

**Objective:** Support Modal proxy-token authentication safely and make the multi-secret requirement explicit.

**Files:**
- Modify: `penguin/web/services/provider_credentials.py`
- Modify: `penguin/core_runtime/model_runtime.py`
- Create: `tests/web/services/test_provider_credentials_modal.py` if no appropriate provider-credential test module exists
- Modify: existing runtime credential tests discovered during implementation

**Steps:**
1. Extend the credential store sanitizer/validator with a Modal proxy record shape such as:

```python
{
    "type": "modal_proxy",
    "token_id": "...",
    "token_secret": "...",
}
```

   Do not represent this record as a generic `{"type": "api", "key": ...}` record.
2. Extend environment credential loading to accept a proxy credential only when *both* `MODAL_PROXY_TOKEN_ID` and `MODAL_PROXY_TOKEN_SECRET` are non-empty.
3. Extend runtime credential availability so `provider="modal"` succeeds only for a configured API key mode or complete proxy-token pair. A single proxy half must produce an actionable missing-credential message.
4. Add one helper owned by the Modal provider/adapter that converts the credential record into request headers:

```python
{
    "Modal-Key": token_id,
    "Modal-Secret": token_secret,
}
```

5. Ensure `LLMPreparedRequest.headers`, lifecycle `provider_data`, generic error formatting, and runtime event redaction do not expose either header value. Header names may be visible; values may not.
6. If Shared API auth is included, implement it as a separately named credential subtype with a separately tested header builder, after its exact contract is verified.

**Tests:**
- complete proxy pair loads and is available;
- missing token ID or secret fails closed;
- credential removal clears only values injected by Penguin;
- prepared request has expected header names but no secret in sanitized diagnostics;
- serialized/replayed runtime events redact both values.

**Commands:**

```bash
pytest -q tests/web/services/test_provider_credentials_modal.py
pytest -q tests/core_runtime -k "modal or credential"
pytest -q tests -k "runtime_event and redact"
```

**Expected:** deterministic pass with no Modal account, endpoint, or server process.

---

### Task 5: Implement `ModalAdapter` as a Chat Completions route

**Objective:** Add the minimal first-class Modal adapter on the extracted shared transport.

**Files:**
- Create: `penguin/llm/adapters/modal.py`
- Modify: `penguin/llm/adapters/__init__.py`
- Modify: `penguin/llm/provider_registry.py`
- Modify: `penguin/llm/model_config.py` only if model config validation/type narrowing prevents `modal` use
- Modify: `tests/llm/test_provider_registry.py`
- Modify/Create: `tests/llm/test_modal_adapter.py`

**Steps:**
1. Implement `ModalAdapter` by configuring the shared Chat Completions protocol with:
   - `provider == "modal"`;
   - a Modal-specific lifecycle request ID prefix such as `modal-...`;
   - the configured `/v1` base URL;
   - Modal credential headers;
   - a provider route diagnostic such as `modal.chat_completions`;
   - no OpenRouter attribution headers or API-key fallback.
2. Require `api_base` and normalize it once so it cannot accidentally duplicate `/v1` or `/chat/completions` during request dispatch.
3. Preserve the configured model name exactly. Do not strip `moonshotai/` or replace it with an OpenRouter-style catalog ID.
4. Default capability metadata conservatively:
   - streaming: true only if Modal's confirmed contract supports it;
   - vision: true for the Kimi K3 preset only;
   - reasoning: false until request format is confirmed;
   - native tools: false until streamed function-call and tool-result continuation contracts are confirmed.
5. Register `modal` in `get_adapter()` / `ProviderRegistry` so `client_preference="native"` selects this adapter.
6. Add adapter preparation tests asserting:
   - protocol is `openai_chat_completions`;
   - route is `modal.chat_completions`;
   - generated body has `model`, `messages`, `stream`, and portable generation fields;
   - generated body excludes `reasoning` by default;
   - headers use Modal names, not `Authorization`/OpenRouter-only names;
   - requests do not use the Responses API.

**Commands:**

```bash
pytest -q tests/llm/test_modal_adapter.py tests/llm/test_provider_registry.py -k modal
ruff check penguin/llm/adapters/modal.py penguin/llm/provider_registry.py
ruff format --check penguin/llm/adapters/modal.py penguin/llm/provider_registry.py
```

**Expected:** new tests pass without external HTTP.

---

### Task 6: Extend the provider contract matrix for Modal

**Objective:** Ensure Modal satisfies Penguin's canonical provider behaviors instead of merely producing a valid request body.

**Files:**
- Modify: `tests/llm/provider_contract_fixtures.py`
- Modify: `tests/llm/test_provider_contract_matrix.py`
- Modify: `tests/llm/test_modal_adapter.py`

**Steps:**
1. Add Modal to the contract-matrix provider parametrization only after the adapter has deterministic fixture support.
2. Reuse/extend fake Chat Completions responses for:
   - non-streaming completion;
   - streaming content chunks followed by terminal finish reason;
   - usage parsing;
   - provider error before stream;
   - SSE error during stream;
   - transport disconnect without a terminal event;
   - cancellation/release semantics;
   - malformed chunks that fail with a normalized error rather than hanging.
3. For tool calls, add two explicit paths:
   - Modal default capability is disabled: prove Penguin does not emit a false native-tools claim;
   - later, only if supported: add fragmented streamed tool-call plus tool-result continuation fixtures before enabling native tools.
4. Add a test ensuring Modal never applies OpenRouter `reasoning` overlays by default.
5. Run Modal and full provider-matrix subsets. Fix the shared protocol rather than adding Modal-only behavior if the same wire condition affects OpenRouter or another Chat Completions route.

**Commands:**

```bash
pytest -q tests/llm/test_provider_contract_matrix.py -k modal
pytest -q tests/llm/test_provider_contract_matrix.py
```

**Expected:** Modal has the same canonical lifecycle guarantees as existing providers; a stream socket closing without terminal completion is not reported as success.

---

### Task 7: Integrate Modal into model resolution and the provider catalog

**Objective:** Make configured Modal models selectable through Penguin without fake OpenRouter metadata or misleading provider UI.

**Files:**
- Modify: `penguin/core_runtime/model_runtime.py`
- Modify: `penguin/web/services/provider_catalog.py`
- Modify: `tests/core_runtime/test_model_runtime.py` or the actual focused counterpart
- Modify/Create: `tests/web/services/test_provider_catalog.py`

**Steps:**
1. Confirm `resolve_model_provider()` preserves an explicitly configured `provider: modal` and `client_preference: native`.
2. Ensure `build_model_config_for_model()` fetches model specs only for actual OpenRouter routes. Modal configuration must rely on its supplied/preset limits, not `fetch_model_specs()`.
3. Add `_PROVIDER_METADATA["modal"]` with only verified public details:
   - display name `Modal`;
   - expected environment hints;
   - no guessed NPM package;
   - avoid a hard-coded endpoint URL if Modal uses user-specific endpoint URLs.
4. Make `provider_ids()` / configured-model collection discover `modal` from config even before credentials are present.
5. Ensure web/TUI current-model payload reports `provider: modal`, configured base URL as appropriate, and no credential value.
6. Add tests for discovery with a Kimi K3 config and for selecting it without a network fetch.

**Commands:**

```bash
pytest -q tests/core_runtime -k modal
pytest -q tests/web/services -k "modal or provider_catalog"
```

**Expected:** the config-defined Kimi K3 model appears as Modal and can be selected entirely offline.

---

### Task 8: Add Kimi K3 documentation and config guidance

**Objective:** Give users a correct, copyable setup path without turning a provider feature into a hard-coded personal endpoint.

**Files:**
- Modify: `README.md`
- Modify: the active configuration documentation discovered under `docs/docs/`
- Modify: the appropriate example config file if one exists and is maintained
- Modify: `context/tasks/modal-kimi-provider-implementation-plan.md` to mark completed decisions if useful

**Steps:**
1. Document Modal as a provider and Kimi K3 as an example/preset.
2. Show separate examples for:
   - a user-owned Auto Endpoint URL and proxy-token credentials;
   - Shared API, only if included and verified.
3. Explain that the endpoint URL must end in `/v1` (or document the exact accepted normalization behavior).
4. State the current capability boundary plainly:
   - streaming and vision status;
   - no promised native tool calling until validated;
   - no claimed reasoning-control field until validated;
   - no Penguin-managed endpoint deployment.
5. Keep README and docs synchronized, per `AGENTS.md`.

**Verification:** manually compare the docs snippets against the actual config parser and prepared-request tests. A documentation sample that selects OpenRouter would be a regression.

---

### Task 9: Run focused verification, then optional local and live smoke tests

**Objective:** Prove the implementation with the narrowest meaningful checks, then optional assembled checks without occupying port 9000.

**Files:**
- Modify only if an existing test harness needs a bounded fake endpoint fixture.
- Do not add production dependencies merely to run a smoke test.

**Steps:**
1. Run focused unit/contract suites:

```bash
pytest -q tests/llm/test_provider_registry.py
pytest -q tests/llm/test_modal_adapter.py
pytest -q tests/llm/test_provider_contract_matrix.py -k "modal or openrouter"
pytest -q tests/core_runtime -k "modal or model_runtime"
pytest -q tests/web/services -k "modal or provider"
ruff check penguin/llm penguin/core_runtime/model_runtime.py penguin/web/services/provider_credentials.py penguin/web/services/provider_catalog.py
ruff format --check penguin/llm penguin/core_runtime/model_runtime.py penguin/web/services/provider_credentials.py penguin/web/services/provider_catalog.py
```

2. If adding an assembled local smoke check, use a mock/fake endpoint process or existing hermetic test client. If a real local server process is necessary, run only:

```bash
HOST=127.0.0.1 PORT=8080 PENGUIN_WEB_LOG_ENABLED=false uv run penguin-web
```

   Verify it responds, then stop it. Do not use port 9000. Do not use 5xxx ports.
3. Keep the local server test optional and scoped to startup/routing; do not make it foundational proof of Modal provider correctness.
4. If the user supplies real Modal credentials and explicitly asks for a live smoke test, run a single opt-in Kimi K3 call against their configured target. Use the user's endpoint and do not print/log headers or response content beyond a concise success/failure summary.
5. Run the full relevant LLM suite only after focused checks pass:

```bash
pytest -q tests/llm
```

**Expected:** normal CI proof remains offline and deterministic. Live Modal validation adds confidence but never substitutes for the contract suite.

---

## Files Likely to Change

```text
penguin/llm/adapters/openai_chat_completions.py      # new shared protocol transport
penguin/llm/adapters/modal.py                        # new Modal provider route
penguin/llm/adapters/openrouter.py                   # delegated/refactored shared protocol use
penguin/llm/adapters/__init__.py                     # adapter exports/registration
penguin/llm/provider_registry.py                     # native modal routing
penguin/llm/model_config.py                          # only if needed for modal config validation
penguin/core_runtime/model_runtime.py                # Modal resolution + credential availability
penguin/web/services/provider_credentials.py         # proxy-token credential schema/env application
penguin/web/services/provider_catalog.py             # Modal discovery metadata
penguin/web/services/provider_auth.py                # Modal multi-field auth descriptor + validation
penguin/web/services/opencode_provider.py            # preserve/extend OpenCode-compatible auth payloads
penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-provider.tsx
                                                     # reusable backend-described multi-field auth dialog
README.md                                             # user setup
/docs/docs/...                                       # matching configuration/provider documentation
tests/llm/test_provider_registry.py
tests/llm/test_modal_adapter.py                       # new
tests/llm/provider_contract_fixtures.py
tests/llm/test_provider_contract_matrix.py
tests/core_runtime/...                                # selected existing model-runtime tests
tests/web/services/test_provider_credentials_modal.py # new or equivalent existing module
```

---

## Risks and Deliberate Non-Goals

### Risks

- Modal Shared API authentication may differ from Auto Endpoint proxy-token authentication. Do not unify them speculatively.
- Extracting the Chat Completions protocol from OpenRouter can regress OpenRouter streaming/tool behavior if the boundary is too broad. Preserve the existing contract matrix before moving onward.
- Kimi K3's documented model capabilities may not imply every OpenAI-compatible extension, especially tools and reasoning controls.
- A 1M-token model context setting is not a reason to increase global CWM assumptions or default output caps. Respect configured limits and existing safety-window logic.

### Non-goals for the initial implementation

- Automatically deploy, scale, or delete Modal Endpoints.
- Add a new Kimi/Moonshot provider for APIs unrelated to Modal.
- Add arbitrary raw header/body escape hatches to generic model config.
- Advertise native function calling or reasoning merely because another OpenAI-compatible provider offers them.
- Replace OpenRouter or rewrite all existing provider adapters in this change.

---

## Decisions Needed Before Implementation

1. **Shared API onboarding:** Modal’s public K3 page confirms the Shared API exists and is OpenAI-compatible, but its currently published public docs did not disclose enough connection detail to implement its setup safely. Do you have access to its dashboard/API onboarding instructions or credentials that establish the base URL and auth scheme? If not, should v1 expose the polished Auto Endpoint flow and label Shared API as pending rather than guessing?
2. **Endpoint provisioning:** Should Penguin remain connect-only for a user-owned endpoint in v1, or should we later offer a guided `modal endpoint create --model moonshotai/Kimi-K3` handoff? I recommend connect-only initially: creation needs account credentials, environment/region choices, billing clarity, and lifecycle controls that do not belong in the TUI's first provider integration.
3. **Capability rollout:** I recommend shipping streaming plus verified vision, with native tool calls and reasoning disabled until a recorded/live Modal compatibility check proves their actual wire semantics. Are you comfortable with that conservative first release?
4. **Live smoke access:** Do you have a Modal endpoint and proxy credentials you want to use for an opt-in final smoke test, or should implementation stop at deterministic mocks/fixtures? The latter is fully sufficient for CI.
