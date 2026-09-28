# Sub-Agent Reliability Fixes

## Status

- State: investigation-backed task brief
- Created: 2026-08-14
- Owner: Penguin runtime
- Scope: sub-agent admission, execution, concurrency, provider lifecycle,
  result aggregation, context handling, and Link event projection
- Related: `context/tasks/sub-agents-v2.md`,
  `context/tasks/resolve-multi-agents.md`,
  `context/tasks/testing-pyramid.md`,
  `context/tasks/tool-call-runtime-architecture.md`, and Link's
  `context/todo/link-sub-agents.md`

## Problem

Penguin's sub-agent primitives now execute through native Responses tool calls,
but a real Link dogfood run exposed reliability, lifecycle, and efficiency
problems under nested delegation.

The recent change in `penguin/tools/runtime.py` accepts the standard
OpenAI-compatible nested function shape:

```json
{
  "id": "call_123",
  "type": "function",
  "function": {
    "name": "spawn_sub_agent",
    "arguments": "{...}"
  }
}
```

That normalization did not add or modify sub-agent scheduling. It allowed
previously discarded valid tool calls to reach the existing sub-agent runtime,
thereby exposing the failures below.

## Observed incident

One successful parent task produced an artifact after approximately 26 minutes
and 246 visible tool operations. Its trace contained:

- 863 runtime events and approximately 11.5 MB of Link SSE data;
- at least 32 distinct OAuth/Codex transport failures, primarily
  `RemoteProtocolError` and `ConnectError`;
- one separate OpenRouter `APIConnectionError` classified as
  `category=runtime`, `retryable=False`, with lifecycle `status=running`;
- five visible children ending in `provider_recoverable_error` and one in
  `provider_error`;
- one child, `orch-pm-audit`, reaching 106 iterations and 441 actions before a
  recoverable provider failure;
- duplicate spawn attempts for existing names such as `schema-auditor`,
  `backend-auditor`, `packages-auditor`, and `orch-pm-audit`;
- repeated child requests carrying roughly 50,000 input tokens;
- one OpenRouter audit carrying 94,616 input tokens and costing approximately
  $0.19 for one call;
- repeated tool outputs reaching the 24,000-character transport ceiling;
- a successful parent answer that did not clearly disclose failed child work.

The log excerpt begins after some requests had already started, so it cannot be
used to calculate a complete success rate. It is sufficient to establish the
failure classes and reproduce them deterministically.

## Root-cause assessment

### Confirmed defects

1. **Duplicate identity is not idempotent.** Existing child names cause failed
   spawn attempts instead of returning the existing compatible child or an
   explicit identity conflict.
2. **Provider classification is inconsistent.** At least one connection error
   crosses the OpenRouter/LiteLLM boundary as a fatal runtime error.
3. **Lifecycle state can contradict the terminal attempt.** A failed provider
   attempt can still report `running`.
4. **Parent aggregation is not truthful enough.** A parent can present a
   successful exhaustive result while child audits ended unsuccessfully.
5. **Logging multiplies failures.** The same exception is logged by adapter,
   API client, engine, and both Penguin and Uvicorn loggers.
6. **Context and evidence are repeatedly over-carried.** Large raw tool outputs
   and shared context are sent into successive child calls.

### Strong hypotheses to prove

1. The ten-agent `AgentExecutor` semaphore is not a single process-wide
   provider concurrency boundary for recursively created executors.
2. Nested spawning can create more provider pressure than the nominal executor
   limit suggests.
3. Provider connection pooling is sized independently from safe provider and
   account concurrency.
4. Recoverable provider failures do not have a durable continuation policy,
   leaving substantial completed child evidence stranded.
5. The parent consumes child results opportunistically rather than through a
   typed aggregation contract.

## Invariants

- Sub-agent work is unbounded by default. Do not terminate an active child due
  to an arbitrary iteration, duration, tool-call, token, or descendant limit.
- Bound concurrent infrastructure operations by queueing them. Waiting for a
  provider slot is not semantic failure.
- Observation loss is not execution failure. A provider or Link disconnect
  leaves work recoverable or outcome-uncertain until authoritative evidence is
  available.
- Child identity is immutable and distinct from its display name.
- A parent may finish with partial results only when the final aggregation says
  so explicitly.
- Provider retries must distinguish a retry of the same uncertain invocation
  from a logically new model call.
- Context reduction must preserve raw evidence outside the prompt packet and
  must not silently truncate the only copy of a result.
- Cancellation remains available regardless of how long work has run.

## Workstream 1 — Deterministic reproduction

- [ ] Add a fake Responses provider capable of successful text, successful
      tool calls, delayed first byte, disconnect-before-headers,
      disconnect-mid-stream, rate limit, and terminal failure.
- [ ] Reproduce one parent spawning multiple isolated background children.
- [ ] Reproduce nested child spawning with a process-wide concurrency probe.
- [ ] Reproduce duplicate display names and duplicate immutable request IDs.
- [ ] Reproduce child completion, recoverable failure, fatal failure,
      cancellation, and outcome-uncertain states.
- [ ] Reproduce a parent finalizing while one child is still running or failed.
- [ ] Assert provider attempt count, maximum simultaneous requests, child
      outcome, and parent aggregation without relying on live providers.
- [ ] Add one opt-in live smoke against OAuth Codex and one against OpenRouter;
      do not use either as the correctness proof.

## Workstream 2 — One scheduler and concurrency authority

- [ ] Confirm the lifecycle and scope of every `AgentExecutor` instance.
- [ ] Replace per-tool-manager or recursively independent concurrency limits
      with one runtime-owned scheduler for provider work.
- [ ] Queue excess child calls fairly; do not reject or settle them because the
      queue is full.
- [ ] Separate child execution concurrency from HTTP connection-pool capacity.
- [ ] Make provider/account concurrency configurable and observable.
- [ ] Preserve user stop and runtime shutdown behavior for queued and running
      children.
- [ ] Expose queued, running, waiting, and active provider-call counts.
- [ ] Prove nested spawning never exceeds the configured simultaneous provider
      request capacity.

## Workstream 3 — Identity and idempotent spawning

- [ ] Introduce an immutable child execution ID independent from `agent_id` or
      display name.
- [ ] Give each spawn request an idempotency identity scoped to its parent
      execution.
- [ ] Replaying a compatible spawn returns the existing child and current
      state.
- [ ] Reusing an idempotency identity with conflicting semantics fails closed.
- [ ] Allow duplicate human-readable child names without state collision.
- [ ] Preserve parent/child relationships across restart and reconnect.
- [ ] Remove create-then-fail behavior that can leave a conversation child
      without a corresponding executor task.

## Workstream 4 — Typed provider lifecycle

- [ ] Normalize `APIConnectionError`, `ConnectError`, and
      `RemoteProtocolError` as network failures at every adapter boundary.
- [ ] Make retryability and lifecycle status derive from the same canonical
      typed error.
- [ ] A completed provider attempt must never retain lifecycle `running`.
- [ ] Distinguish disconnected, failed, cancelled, completed, and
      outcome-uncertain.
- [ ] Preserve provider request/invocation identity through retries.
- [ ] Do not blindly retry a request whose dispatch outcome may be ambiguous.
- [ ] Add deterministic adapter contract tests for OpenRouter, OAuth Codex,
      and LinkProvider mappings.

## Workstream 5 — Child result and parent aggregation contract

- [ ] Define a typed `ChildExecutionOutcome` containing identity, terminal or
      uncertain state, result summary, artifact references, usage, error, and
      evidence cursor.
- [ ] Define a typed parent aggregation listing successful, partial, failed,
      cancelled, running, and unavailable children.
- [ ] Require the parent to wait, explicitly detach, or explicitly finalize
      with partial results. Silent omission is invalid.
- [ ] Preserve completed child evidence when a later provider continuation
      fails.
- [ ] Make `wait_for_agents` return stable structured outcomes rather than
      concatenated status strings.
- [ ] Ensure background completion is delivered exactly once to the owning
      parent/session.
- [ ] Propagate structured child outcomes through Link without exposing raw
      internal exceptions or secrets.

## Workstream 6 — Context and evidence efficiency

- [ ] Default isolated audit children to narrow task context rather than a
      shared full conversation window.
- [ ] Carry stable references to files and artifacts instead of repeated raw
      24,000-character outputs.
- [ ] Integrate with CWM v2's cache-stable packet and append-only active tail.
- [ ] Preserve raw child evidence in storage while returning a deterministic
      summary packet to the parent.
- [ ] Track input tokens, cache reads, tool-output bytes, and context source by
      child and parent.
- [ ] Detect repeated identical tool evidence and reuse its reference.
- [ ] Prove prompt slimming does not reduce task quality below the accepted
      baseline.

## Workstream 7 — Observability without log storms

- [ ] Emit one canonical error record per provider attempt diagnostic ID.
- [ ] Attach layer-specific context without printing the full traceback at
      every layer.
- [ ] Keep one traceback at the owning boundary and reference it elsewhere.
- [ ] Record parent ID, child execution ID, provider invocation ID, lifecycle
      status, retryability, and scheduler state on every relevant record.
- [ ] Add aggregate metrics for queued/running children, provider disconnects,
      retries, partial parents, context size, and event bytes.
- [ ] Sanitize provider payloads, credentials, account identifiers, and child
      prompts in production logs.

## Workstream 8 — Link projection

- [ ] Emit compact child announced, queued, running, waiting, checkpoint,
      terminal, and uncertain events.
- [ ] Keep raw tactical tool/reasoning events out of Link's primary stream by
      default.
- [ ] Make detailed evidence retrievable by reference.
- [ ] Include immutable parent, provider execution, and child execution IDs.
- [ ] Support Link reconnect and replay without duplicating child outcomes.
- [ ] Ensure provider-internal helpers do not become first-class Link workspace
      agents merely because they were observed.

## Test matrix

| Scenario | Required assertion |
| --- | --- |
| Ten children with scheduler capacity three | At most three provider calls run; the rest remain queued and later execute |
| Nested children | The same process-wide capacity still applies |
| Duplicate display name | Both children remain distinct |
| Replayed spawn request | Existing compatible execution is returned |
| Conflicting replay | Conflict fails closed before new execution |
| Disconnect before headers | Network/recoverable or uncertain as appropriate; never `running` after attempt end |
| Disconnect mid-stream | Prior evidence remains; no false completion |
| Child fatal failure | Parent aggregation names the failed child |
| Parent partial completion | Final result explicitly declares partial evidence |
| Parent reconnect | Child outcomes replay exactly once |
| Cancellation while queued | Child never dispatches and becomes authoritatively cancelled |
| Cancellation while running | Provider cancellation is attempted and reconciled |
| Large tool evidence | Parent receives a reference/summary; raw evidence remains retrievable |
| Long-running child | Continues beyond former incidental limits until authoritative completion or explicit cancellation |

## Suggested implementation order

1. Fake-provider reproduction and lifecycle assertions.
2. Canonical provider error classification.
3. Runtime-owned global scheduler and queue.
4. Immutable child execution and spawn idempotency.
5. Typed child outcome and parent aggregation.
6. Compact Link event projection.
7. Context/evidence slimming and observability cleanup.
8. Opt-in live provider and Link end-to-end smoke tests.

## Non-goals

- Replacing the entire multi-agent architecture in one change.
- Moving Penguin's internal scheduler into Link.
- Treating provider transport retry as a semantic agent retry.
- Adding arbitrary semantic execution budgets to contain runaway behavior.
- Relying on a live provider to prove concurrency, replay, or lifecycle
  correctness.
- Returning raw child prompts, credentials, or provider error payloads to Link.

## Exit criteria

The repair is complete when:

1. Nested sub-agents obey one observable concurrency scheduler without losing
   or prematurely terminating work.
2. Every provider failure has consistent category, retryability, and terminal
   attempt state.
3. Spawn replay is idempotent and duplicate display names cannot collide.
4. Parent output truthfully accounts for every attached child.
5. Link receives a compact, replayable child projection instead of a tactical
   event flood.
6. Deterministic fault-injection tests pass for success, disconnect, retry,
   partial aggregation, cancellation, restart, and long-running work.
