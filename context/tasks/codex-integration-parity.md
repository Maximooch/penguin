# Codex Integration Parity

## Purpose

This document tracks the remaining parity gaps between Penguin's
ChatGPT-backed OpenAI/Codex integration and the upstream Codex client.

The goal is not to clone Codex wholesale. The goal is to identify the request
parameters, catalog metadata, and runtime behaviors that materially improve
model access, latency, reliability, and tool-call behavior in Penguin.

## Current State

Penguin can authenticate against ChatGPT-backed Codex OAuth and route requests
to the Codex responses endpoint.

Recent fixes made the integration usable with the authenticated Codex model
catalog, including latest model discovery and lowercase model IDs such as
`gpt-5.5`.

Penguin now threads OpenAI `service_tier` through the main request path and
supports a TUI `/fast` toggle that maps to `service_tier: "priority"`.

The remaining gaps are mostly catalog-gated request shaping and runtime/tool
behavior.

## Reference Points

- Upstream Codex request construction:
  `reference/codex/codex-rs/core/src/client.rs`
- Upstream Codex turn-scoped client/session state:
  `reference/codex/codex-rs/core/src/client.rs`
  `reference/codex/codex-rs/core/src/client_common.rs`
- Upstream Codex model metadata:
  `reference/codex/codex-rs/protocol/src/openai_models.rs`
- Upstream Codex stream recovery tests:
  `reference/codex/codex-rs/core/tests/suite/stream_no_completed.rs`
  `reference/codex/codex-rs/core/tests/suite/stream_error_allows_next_turn.rs`
- Upstream Codex tool replay/truncation references:
  `reference/codex/codex-rs/core/src/tools/parallel.rs`
  `reference/codex/codex-rs/core/src/tools/handlers/shell.rs`
  `reference/codex/codex-rs/core/tests/suite/shell_serialization.rs`
- Penguin Codex OAuth request construction:
  `penguin/llm/adapters/openai.py`
- Penguin model catalog merge path:
  `penguin/web/services/provider_catalog.py`
  `penguin/web/services/opencode_provider.py`
- Penguin testing strategy:
  `context/tasks/testing-pyramid.md`

## Parity Gaps

### 1. Service Tier / Fast Mode

Codex supports Fast mode for supported ChatGPT-backed models. In the upstream
client, the local `ServiceTier::Fast` setting is sent to the Responses payload
as:

```json
{"service_tier": "priority"}
```

Penguin now passes `service_tier` through OpenAI/Codex request payloads and the
TUI can toggle fast mode with `/fast`, `/fast on`, `/fast off`, and
`/fast status`.

Remaining Penguin behavior:

- only offer fast when the selected model advertises a fast speed tier
- make the higher credit consumption clear in UI copy
- decide whether OpenAI provider defaults should opt into priority service

### 2. Prompt Cache Key

Codex sends a stable `prompt_cache_key` based on the conversation id.

Penguin currently does not send `prompt_cache_key` for ChatGPT-backed Codex
requests.

Expected Penguin behavior:

- use a stable session/conversation id as `prompt_cache_key`
- preserve the same key across a conversation
- avoid leaking filesystem paths or sensitive local details into the key

This is likely a low-risk latency/cache efficiency improvement.

### 3. Model Capability Gating

Codex model metadata includes capabilities such as:

- supported reasoning efforts
- support for reasoning summaries
- support for verbosity
- default verbosity
- support for parallel tool calls
- additional speed tiers

Penguin currently consumes enough catalog data to show and select models, but
does not fully use these model capabilities to shape every request.

Expected Penguin behavior:

- preserve capability metadata from the authenticated Codex catalog
- gate request parameters by model capability
- avoid sending unsupported parameters
- surface unavailable controls as disabled rather than silently ignoring them

### 4. Verbosity / Text Options

Codex can build a Responses `text` parameter from model verbosity and output
schema settings when the selected model supports it.

Penguin supports response-format style options in some paths, but does not
currently expose Codex-style model verbosity for ChatGPT-backed Codex requests.

Expected Penguin behavior:

- add optional `verbosity` support only for models that advertise it
- avoid applying verbosity globally to providers that do not support it
- keep structured output behavior separate from verbosity controls

### 5. Parallel Tool Calls

Codex passes `parallel_tool_calls` when the model and tool runtime can support
it.

Penguin currently does not request parallel tool calls for Codex OAuth traffic.
This should not be enabled blindly. It depends on Penguin's tool runtime being
able to execute, stream, order, persist, and recover from concurrent tool calls.

Expected Penguin behavior:

- first harden tool execution and result persistence
- then enable `parallel_tool_calls` only for safe tool subsets
- gate by model capability and Penguin runtime capability
- keep a conservative default until the tool loop is proven stable

### 6. Client Metadata / Installation Identity

Codex sends client metadata such as `x-codex-installation-id`.

Penguin sends its own lightweight headers, including `originator: penguin`, but
does not mirror the upstream client metadata.

Expected Penguin behavior:

- decide whether Penguin needs a stable local installation id
- avoid adding identifiers unless they provide diagnostics or upstream behavior
  benefits
- keep any identifier non-sensitive and resettable

This is lower priority than service tier, caching, and tool-loop correctness.

### 7. WebSocket / Incremental Request Path

Codex has a WebSocket path with incremental request reuse. Penguin currently
uses HTTP SSE for ChatGPT-backed Codex responses.

Expected Penguin behavior:

- keep SSE as the correctness baseline
- consider WebSocket/incremental transport only after request parity and tool
  runtime stability are addressed
- treat this as a performance optimization, not a first-order feature gap

### 8. Tool Runtime Parity

Codex's model integration is tightly coupled to its tool contracts, tool output
shaping, truncation behavior, diff tracking, approval flow, and loop control.

Penguin currently has a separate tool/runtime stack. Recent observed behavior
shows a useful but over-aggressive guard:

- the model made repeated empty tool-only turns
- the tool output began with the same content
- Penguin classified the sequence as a repeated stale loop
- the task stopped after the empty tool-only threshold

This appears to be a Penguin runtime/tool-loop issue rather than an OpenAI
Codex model issue.

Expected Penguin behavior:

- fix any read-tool bugs first
- include tool name, arguments, path, range, and output identity in repeated
  tool-only loop signatures
- distinguish legitimate exploration from stale repeated output
- tune thresholds by mode when needed
- surface continuation affordances when the guard stops a run

### 9. Provider Request Lifecycle / Abrupt Stop Recovery

The recurring abrupt-stop reports look more like provider transport lifecycle
problems than context-window-management truncation. The observed logs show
large request histories, `store=False`, fixed HTTP client timeouts, and
timeout-style failures. Penguin's CWM can still affect stability indirectly by
changing tool replay pressure, but it is unlikely to be the direct cause of
network `ReadTimeout` failures.

Codex's reference client is useful here because it treats a model turn as a
tracked provider request, not just a synchronous HTTP call. It keeps per-turn
state, records incomplete streams, releases the turn after stream errors, and
only reuses incremental `previous_response_id`-style state when the request is
known to be a safe prefix extension.

Expected Penguin behavior:

- create a provider request record before sending OpenAI/Codex traffic
- track lifecycle states such as pending, running, streaming, disconnected,
  retrying, completed, failed, and cancelled
- record request payload hash, provider/model, session/turn id, attempt count,
  provider response id when available, and last received stream event
- distinguish no-completion stream drops from completed responses with no text
- retry or recover incomplete streams without leaving the engine/session stuck
- emit a structured failure and turn-complete signal when recovery is not
  possible, so the next user turn can proceed normally
- gate `previous_response_id` reuse on a payload-prefix/hash contract; fall
  back to a full request after errors, shape changes, or non-prefix history
  changes

### 10. OpenAI Background / Stored Response Capability

OpenAI background mode and `store=true` are provider-specific recovery tools,
not the provider-agnostic foundation. They are useful when Penguin wants
OpenAI to keep a long-running response alive server-side so Penguin can poll or
reconnect after a client/network interruption.

Expected Penguin behavior:

- implement provider request lifecycle tracking before relying on background
  mode
- keep background mode opt-in per provider/model/task until costs and UX are
  clear
- use `store=true` only when Penguin intentionally needs provider-side
  resumability or response retrieval
- keep stateless encrypted reasoning handling intact for non-stored requests
- fall back to canonical conversation/tool replay for providers that do not
  offer stored response recovery

Pros:

- better recovery from long-running requests and local network interruptions
- clearer polling/reconnect semantics for OpenAI Responses requests
- less need to repeat expensive long-running model work after a disconnect

Cons:

- provider-specific behavior that should not leak into the general contract
- potential persistence/privacy implications because the provider stores the
  response
- more lifecycle states to expose and test
- not a replacement for timeout policy, stream completion checks, or tool
  replay correctness

## Suggested Implementation Order

### Phase 1: Low-Risk Request Parity

1. Add `service_tier` config plumbing for ChatGPT-backed Codex.
2. Gate fast mode by authenticated model metadata.
3. Add stable `prompt_cache_key` based on session/conversation id.
4. Add focused tests for payload construction.

### Phase 2: Catalog Capability Propagation

1. Preserve Codex model capability fields in Penguin's provider catalog.
2. Expose speed-tier and verbosity metadata to the UI/TUI provider surface.
3. Gate unavailable controls from the catalog rather than hardcoded model names.

### Phase 3: Tool Loop Hardening

1. Audit the read tool for repeated/range/limit behavior.
2. Fix repeated empty tool-only detection to account for arguments and file
   ranges.
3. Add regression tests for repeated file reads with different limits/ranges.
4. Improve user-facing continuation behavior after guarded stops.

### Phase 4: Advanced Runtime Parity

1. Add verbosity support for models that advertise it.
2. Evaluate `parallel_tool_calls` with a restricted safe tool set.
3. Consider WebSocket/incremental transport only if SSE latency remains a real
   bottleneck.

### Phase 5: OpenAI/Codex Request Lifecycle Stability

1. Add a provider request record around Codex OAuth Responses calls.
2. Replace fixed read timeouts with an explicit streaming timeout/stall policy:
   bounded connect/write/pool timeouts, long or disabled read timeout for active
   streams, and a Penguin-owned cancellation/stall watchdog.
3. Add incomplete-stream detection for streams that end without
   `response.completed`.
4. Retry safe incomplete streams or return a structured recoverable failure
   without leaving the current turn locked.
5. Add regression tests mirroring Codex's stream closes before completion and
   stream error allows next turn cases.
6. Gate `previous_response_id` reuse on payload-prefix/hash safety.

Phase 5 implementation note:

- `penguin.llm.contracts` now exposes `ProviderRequestStatus`,
  `LLMRequestLifecycle`, and `RequestLifecycleRuntime` as the shared lifecycle
  contract.
- OpenAI/Codex OAuth SSE requests now record pending, running, streaming,
  completed, disconnected, and failed states with request id, payload hash,
  provider/model, stream transport, last event, provider response id when
  available, finish reason, and canonical error metadata.
- Codex OAuth HTTP clients now use bounded connect/write/pool timeouts without
  a fixed active-stream read timeout.
- Empty Codex streams that end before `response.completed` without text or a
  tool call now raise a retryable provider error and record a disconnected
  lifecycle instead of returning a silent empty response.
- Streams that produce text or native tool-call bytes but end before
  `response.completed` now fail as disconnected incomplete streams rather than
  being treated as successful partial responses.
- Regression coverage verifies incomplete empty streams, incomplete partial
  text streams, incomplete partial native tool-call streams, mid-stream
  provider error events, and a later turn succeeding after a disconnected
  request.

### Phase 5.5: Codex Reliability Test Harness

1. Build a deterministic fake Codex Responses/SSE fixture layer inspired by
   Codex's Rust `core/tests/common/responses.rs` helpers.
2. Add captured-request assertions for input items, instructions, native tool
   calls, function-call outputs, reasoning includes, service tier, and
   `previous_response_id` safety.
3. Add fault injection for incomplete streams, early close after text, early
   close after tool call, provider error mid-stream, timeout/stall, malformed
   event, duplicate event, and partial function-call arguments.
4. Convert representative `context/bugs/*` and `misc/web-server-logs-*` cases
   into minimized deterministic fixtures.
5. Keep live OpenAI/Codex checks opt-in and cheap; they prove credentials and
   transport, not correctness of the lifecycle contract.

Acceptance criteria:

- Phase 6 replay work starts only after fake-provider fixtures can express the
  failure modes being enforced.
- No incomplete stream is treated as completed merely because it emitted some
  text or tool bytes.
- Provider errors and incomplete streams always release the current turn.
- CWM category-priority truncation does not create malformed OpenAI Responses
  tool-call adjacency.

Phase 5.5 implementation note:

- `tests/llm/test_openai_oauth_subscription_flow.py` now has reusable fake
  Codex SSE helpers and request-capturing transport fixtures factored through
  `tests/llm/codex_oauth_fixtures.py` for deterministic OpenAI/Codex OAuth
  tests.
- Successful Codex OAuth fixtures now emit explicit `response.completed`
  events instead of relying on text plus `[DONE]`.
- Incomplete streams after partial text or partial native tool calls now record
  disconnected lifecycle failures instead of being treated as completed
  responses.
- Partial native tool calls from incomplete streams are cleared so they cannot
  be executed as replay-safe pending tools.
- Completed native tool-call streams still preserve pending tool calls for the
  runtime to execute.
- Mid-stream provider error events now produce failed lifecycle records.
- Request-shape coverage now verifies CWM-truncated tool history does not send
  unresolved Codex `function_call` items, complete tool pairs replay in order,
  and tool-result-only records with enough metadata can synthesize a valid
  replay pair.

### Phase 6: OpenAI/Codex Tool Replay Stability

1. Persist native tool calls as canonical runtime records before executing the
   tools.
2. Persist completed, failed, denied, cancelled, and interrupted tool results
   with provider call ids.
3. Reconstruct OpenAI Responses `function_call` / `function_call_output`
   adjacency from persisted records instead of loose message text.
4. Synthesize explicit failed/cancelled tool outputs for dangling historical
   calls during replay.
5. Apply universal model-visible tool-output truncation before replay, with
   full output stored locally.
6. Retry empty non-tool continuations after tool-heavy turns once with bounded
   recent tool output before returning a structured diagnostic.

### Phase 7: Optional OpenAI Background Recovery

1. Add capability-gated `background=true` / `store=true` support for
   OpenAI/Codex only after request lifecycle tracking exists.
2. Record provider response ids and polling/reconnect state in the request
   record.
3. Prefer background mode for long-running Codex tasks where replay would be
   expensive or unsafe.
4. Keep foreground stateless mode as the default until the UX and privacy trade
   offs are settled.

## Non-Goals

- Do not make Penguin depend on Codex internals directly.
- Do not enable parallel tool calls before the tool runtime can safely support
  them.
- Do not mirror upstream client metadata unless it has a clear benefit.
- Do not hardcode latest model names where authenticated catalog metadata can
  answer the question.
- Do not treat OpenAI background mode as the general solution for provider
  reliability.
- Do not reuse `previous_response_id` after ambiguous failures unless the next
  request is provably a safe prefix extension.

## Open Questions

- Should fast mode be a global provider setting, a per-session setting, or a
  per-request variant?
- Should standard mode explicitly send a null/standard value, or simply omit
  `service_tier`?
- Should Penguin expose Codex-Spark as a separate model choice only, or also
  provide speed-oriented UI grouping?
- Which Penguin tools are safe candidates for eventual parallel tool calls?
- Should the repeated empty tool-only guard be configurable per mode?
- Which request lifecycle fields should be persisted in conversation/session
  storage versus transient diagnostics?
- What tasks should opt into OpenAI background recovery by default, if any?
