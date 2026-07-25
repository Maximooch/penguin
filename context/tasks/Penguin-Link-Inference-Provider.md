# Penguin Link Inference Provider

Status: implemented on the current Link/Penguin working branches; live Sandbox smoke pending
Target repository: `/Users/maximusputnam/Code/Penguin/penguin`
Link counterpart: `apps/backend/src/inference/`

## Purpose

When Link resolves a model as Link-managed, every Penguin model call for that
turn must go through Link's inference broker. Penguin must not turn a Link
catalog selection into a direct OpenRouter call.

The required execution path is:

```text
Link session request
  -> Penguin reasoning/tool loop
  -> LinkProvider (one request per model invocation)
  -> Link /api/v1/responses (preferred) or /api/v1/chat/completions
  -> durable reservation
  -> provider dispatch intent
  -> meter_event + meter_outbox
  -> Polar
```

This is a provider transport concern, not an agent-loop concern. The Engine and
conversation manager should continue consuming Penguin's existing normalized
LLM contracts.

## Non-goals

- Do not put billing arithmetic, provider credentials, or OpenRouter policy in
  Penguin.
- Do not use Link's browser cookie from Penguin.
- Do not aggregate a multi-step agent turn into one inferred usage event. Each
  provider invocation is separately reserved and metered by Link.
- Do not route through LiteLLM. Penguin deliberately treats LiteLLM as an
  optional legacy path; it would add another policy/normalization layer without
  solving Link ownership or attribution.
- Do not silently fall back from Link to direct OpenRouter when Link-managed
  execution was selected.

## Personal ChatGPT subscription route

Penguin also exposes its locally authenticated ChatGPT subscription as a
provider capability for Link sessions. This is independent from the
Link-managed `LinkProvider`: Penguin remains the agent runtime in both cases,
but the subscription route keeps OAuth and provider quota custody inside the
local Penguin process.

- `GET /api/v1/link/capabilities` returns a versioned, credential-free catalog
  for the authenticated Codex Responses compatibility transport.
- Link binds that local runtime/provider capability to one Link user. User A's
  personal subscription cannot serve User B, a workspace, or unattributed
  scheduled/system work.
- Each request carries an immutable `external_subscription_execution`
  descriptor. Penguin validates the owner, selected model, transport, and
  local OAuth state before model dispatch and echoes the execution facts plus
  observed usage in its result.
- Fallback to Link-managed inference is false for the beta contract. Missing
  auth, quota exhaustion, model mismatch, or runtime disappearance fails
  explicitly rather than spending Link credits.
- Link records the echoed usage in its normal statistics pipeline as
  externally billed work. It creates no Link credit reservation and no Polar
  projection for this route.
- A User A-initiated run may finish after the browser disconnects because the
  captured descriptor remains attributed to User A; losing that attribution
  makes the route ineligible.

## Existing Penguin seams

Implement against these current abstractions:

| Concern                  | Existing seam                                                             | Required change                                                                                                     |
| ------------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Provider selection       | `penguin/llm/provider_registry.py`                                        | Add a first-class `link` preference/handler rather than recognizing Link by URL substring.                          |
| Runtime configuration    | `penguin/llm/client.py` (`LinkConfig`, `LLMClientConfig`)                 | Replace process-global-ish mutable attribution with an immutable request-scoped Link execution context.             |
| Canonical request/result | `penguin/llm/contracts.py` (`LLMRequest`, `LLMResult`, `ProviderRuntime`) | Preserve these contracts; add only the context fields needed for request identity and protocol capabilities.        |
| Streaming lifecycle      | `penguin/llm/stream_handler.py` and `APIClient` lifecycle state           | Map Link SSE events into the existing lifecycle and tool-call contracts.                                            |
| Current proof            | `tests/llm/test_link_runtime_contract.py`                                 | Expand from “headers reach an OpenRouter gateway” to “Link owns the transport and direct OpenRouter is impossible.” |

## Configuration contract

Add an explicit provider preference:

```yaml
model:
  provider: openrouter # model namespace; not credential ownership
  client_preference: link # transport and policy owner
  model: openai/gpt-5.6-luna
```

Static process configuration:

```text
LINK_INFERENCE_BASE_URL=http://localhost:3001/api/v1
LINK_INFERENCE_SERVICE_TOKEN=<service credential>
LINK_INFERENCE_PROTOCOL=responses  # responses | chat_completions
```

The service token authenticates Penguin as a Link runtime. It must not encode a
single workspace or user. Per-invocation attribution is request context.

Define an immutable context value (name may follow Penguin conventions):

```python
@dataclass(frozen=True)
class LinkInferenceContext:
    workspace_id: str
    user_id: str
    session_id: str
    agent_id: str
    run_id: str
    requested_model_id: str
    execution_source: Literal["link_gateway"]
    provider_state_owner: Literal["link_managed"]
    settlement_mode: Literal["debit_link_credits"]
```

`invocation_id` is unique for each model call, including follow-up calls after
tool results. Retrying the same uncertain HTTP attempt reuses the invocation ID;
a logically new model call gets a new ID.

## Transport contract

### Authentication and attribution

Every request sends:

```http
X-Link-Service-Name: penguin
X-Link-Service-Auth: <LINK_INFERENCE_SERVICE_TOKEN>
X-Link-Workspace-Id: <workspace_id>
X-Link-User-Id: <user_id>
X-Link-Session-Id: <session_id>
X-Link-Agent-Id: <agent_id>
X-Link-Run-Id: <run_id>
X-Link-Request-Id: <invocation_id>
```

Link must authenticate the service credential and verify that the asserted
workspace/run context is authorized. Penguin must never forward a provider key.

### Protocol selection

Implement a small protocol strategy inside `LinkProvider`:

1. Prefer `POST {base_url}/responses` when configured and supported.
2. Use `POST {base_url}/chat/completions` for models/features not yet covered by
   the Responses adapter.
3. Protocol selection is explicit capability negotiation, never retry-based
   guessing after a provider effect may have occurred.

The implementation supports:

- text input/output;
- streaming text and reasoning deltas;
- tool definitions, tool choice, tool-call deltas, and tool results;
- bounded maximum output tokens;
- temperature and provider-neutral reasoning effort where supported;
- cancellation and idle timeout;
- normalized usage and provider request ID capture.

Multimodal requests must fail before dispatch until Link advertises a metered
multimodal capability.

### Request identity

Send `X-Link-Request-Id` on both protocols. The same invocation ID is used for
reservation idempotency, provider dispatch intent, meter event, and Polar
idempotency. Penguin may retry only when Link explicitly reports a pre-dispatch
failure. A disconnect/timeout after dispatch is an uncertain outcome and must
not be automatically replayed under a new ID.

### Response/error semantics

Map Link responses into existing Penguin errors:

| Link result                     | Penguin behavior                                                       |
| ------------------------------- | ---------------------------------------------------------------------- |
| 400 policy/unsupported input    | non-retryable `LLMProviderError`                                       |
| 401/403 service or context auth | non-retryable configuration/security error                             |
| 402 insufficient credits        | non-retryable quota/billing error surfaced to Link                     |
| 409 idempotency conflict        | non-retryable invariant error                                          |
| 429                             | retry only when Link supplies a safe retry signal                      |
| 5xx before-dispatch marker      | bounded retry with same invocation ID                                  |
| disconnect or ambiguous 5xx     | mark lifecycle disconnected/uncertain; do not call OpenRouter directly |

Preserve Link response headers (`X-Link-Inference-Request-Id`, execution source,
settlement mode, meter key) in `LLMResult.provider_data` for diagnostics. Usage
reported to Penguin is observational only; Link's durable meter is authoritative.

## Provider registry changes

`ProviderRegistry.create_handler()` accepts `client_preference="link"`
and construct `LinkProvider`. Do not route Link through
`OpenRouterGateway(base_url=...)`; that is the current defect because the
gateway still owns OpenRouter-specific assumptions and makes Link support look
like a URL override.

`LinkProvider` implements Penguin's normalized provider surface for:

- `ProviderRuntime`;
- `UsageReportingRuntime`;
- `ToolCallRuntime`;
- `ErrorReportingRuntime`;
- `RequestLifecycleRuntime`.

It should use Penguin's shared connection pool and stream lifecycle helpers.
Keep request/response translation in protocol-specific modules, for example:

```text
penguin/llm/providers/link/
  __init__.py
  provider.py
  context.py
  responses_protocol.py
  chat_completions_protocol.py
  errors.py
```

The exact directory can follow the ongoing provider consolidation, but protocol
translation and orchestration must remain separate.

## Runtime propagation

Link's agent route knows workspace, user, session, agent, and run and carries
an immutable `LinkInferenceContext` through the A2A/runtime request into each
Engine model invocation. Do not mutate a singleton client through
`/system/config/llm` between requests; concurrent workspaces would race.

At the provider boundary:

```python
if execution.provider_state_owner == "link_managed":
    assert client_preference == "link"
    assert link_context is not None
```

Conversely, a `link` client preference without a complete Link-managed
descriptor must fail closed.

## Tests And Evidence

Follow Penguin's deterministic provider testing pyramid.

1. Registry tests

   - `client_preference="link"` creates `LinkProvider`.
   - Link-managed selection cannot instantiate `OpenRouterGateway` or
     `LiteLLMGateway`.

2. Request contract tests

   - all attribution and request-ID headers are present;
   - service token is present but provider credentials are absent;
   - Responses and Chat Completions translations preserve tools/reasoning;
   - every follow-up model invocation gets its own ID.

3. Stream fixtures

   - text, reasoning, tools, usage, incomplete stream, error event, cancellation;
   - native tool-call adjacency remains valid after translation.

4. Reliability/state-machine tests

   - safe pre-dispatch failure retries with the same ID;
   - ambiguous disconnect is not replayed and never falls back direct;
   - concurrent workspaces retain distinct immutable context;
   - cancellation closes the Link response and reports the correct lifecycle.

5. Link integration test

   - run a fake Link broker and assert the sequence
     `reserve -> dispatch intent -> meter -> outbox` for every Penguin model
     invocation.

6. Opt-in sandbox smoke
   - one real Link workspace prompt produces a matching Link meter event and
     Polar Sandbox event with the same request identity.

The registry, request translation, streaming/tool/usage, immutable-context, and
ambiguous-transport tests are implemented under `tests/llm` and `tests/web`.
The live smoke remains gated by the Polar customer/refund scopes, webhook
secret, approved product id, and provider spend cap documented in Track 8.

## Acceptance criteria

- A Link UI Penguin turn using a Link-managed model creates at least one Link
  `meter_event`; a multi-step/tool turn creates one per provider invocation.
- No direct request reaches OpenRouter from Penguin for that execution mode.
- The model, user, workspace, session, agent, run, and invocation are
  attributable on every request.
- The runtime supports both Responses and Chat Completions without coupling the
  provider abstraction to either wire format.
- Policy, pricing, credentials, reservation, settlement, reconciliation, and
  Polar delivery remain entirely Link-owned.
- Concurrent Link workspaces cannot overwrite each other's routing context.
- LiteLLM is neither required nor involved.
