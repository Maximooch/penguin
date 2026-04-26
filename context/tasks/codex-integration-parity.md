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
- Upstream Codex model metadata:
  `reference/codex/codex-rs/protocol/src/openai_models.rs`
- Penguin Codex OAuth request construction:
  `penguin/llm/adapters/openai.py`
- Penguin model catalog merge path:
  `penguin/web/services/provider_catalog.py`
  `penguin/web/services/opencode_provider.py`

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

## Non-Goals

- Do not make Penguin depend on Codex internals directly.
- Do not enable parallel tool calls before the tool runtime can safely support
  them.
- Do not mirror upstream client metadata unless it has a clear benefit.
- Do not hardcode latest model names where authenticated catalog metadata can
  answer the question.

## Open Questions

- Should fast mode be a global provider setting, a per-session setting, or a
  per-request variant?
- Should standard mode explicitly send a null/standard value, or simply omit
  `service_tier`?
- Should Penguin expose Codex-Spark as a separate model choice only, or also
  provide speed-oriented UI grouping?
- Which Penguin tools are safe candidates for eventual parallel tool calls?
- Should the repeated empty tool-only guard be configurable per mode?
