---
sidebar_position: 1
---

# Core Runtime Boundary

`PenguinCore` constructs the runtime, keeps references to long-lived
collaborators, and preserves public method names for existing CLI, web/API,
TUI/OpenCode, and Python callers. It should not be treated as the owner of
provider behavior, action mapping, checkpoint lineage, token accounting, or
project orchestration rules.

## Runtime Ownership

| Area | Runtime owner |
|------|---------------|
| Construction and dependency wiring | `penguin.core_runtime.startup` |
| Public `process(...)` entrypoint | `penguin.core_runtime.process_runtime` |
| Single-message helper | `penguin.core_runtime.message_processing` |
| Direct response/action helper | `penguin.core_runtime.response_generation` |
| Provider/model runtime behavior | `penguin.core_runtime.model_runtime`, `penguin.llm` |
| Token/context-window telemetry | `penguin.core_runtime.token_usage_runtime` |
| Checkpoint, fork, rollback, retention | `penguin.core_runtime.checkpoint_runtime` |
| Tool/action payload mapping | `penguin.core_runtime.action_mapping` |
| OpenCode/TUI event bridge | `penguin.core_runtime.opencode_bridge`, `penguin.core_runtime.stream_events`, `penguin.core_runtime.action_events` |
| Runtime event envelope and durable replay | `penguin.system.runtime_events`, `penguin.system.runtime_event_ledger`, `penguin.web.sse_events` |
| Session lookup and ownership | `penguin.core_runtime.session_lookup` |
| Status and startup diagnostics | `penguin.core_runtime.system_diagnostics` |
| Reasoning and tool loop | `penguin.engine` |
| Autonomous task lifecycle | `penguin.run_mode` |
| HTTP payload/business services | `penguin.web.services.*` |

The compatibility modules keep methods such as `core.process(...)`,
`core.load_model(...)`, `core.get_token_usage(...)`, and
`core.create_checkpoint(...)` available on `PenguinCore` while delegating to the
modules above.

## Design Contract

- New runtime behavior belongs in the module that owns the behavior, not in
  `penguin/core.py`.
- `PenguinCore` can expose a narrow shim when public API compatibility requires
  it.
- Web routes should stay thin; route-specific business logic belongs in
  `penguin.web.services`.
- Provider, streaming, OAuth, and prepared-request behavior should be covered by
  deterministic fake-provider contract tests before relying on live smoke tests.
- Checkpoint/fork/revert behavior must preserve source-session immutability,
  parent/child lineage, and session/agent ID isolation.
- OpenCode/SSE-compatible event payloads should derive from Penguin's
  canonical `RuntimeEvent` envelope and durable ledger. `PenguinCore` owns the
  shared event-bus reference, not the envelope schema or replay policy.
- Penguin's context window manager trims by category priority and recency; it
  does not summarize or compact conversation content.

## Runtime Event Boundary

`RuntimeEvent` envelopes live in `penguin.system.runtime_events`. They provide
stable event ids, per-stream sequence numbers, normalized session/agent/task
scope, redacted payloads, and privacy metadata. OpenCode-shaped payloads are
compatibility projections of those envelopes.

Durable replay lives in `penguin.system.runtime_event_ledger` and is wired into
the SSE endpoint by `penguin.web.sse_events`. The ledger stores redacted public
runtime events only; it is not the transcript or a private diagnostics store.
See [Runtime Events and Durable Replay](runtime-events.md) for the public
contract.

## Testing Implication

Default tests should exercise these runtime modules directly where possible.
`PenguinCore` tests should mostly prove construction, delegation, and
compatibility behavior. This keeps the default suite useful as a refactor gate:
when a runtime module changes, tests fail at the actual ownership boundary
instead of through a large `core.py` integration tangle.
