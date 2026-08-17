# Sub-Agents v2

Date: 2026-08-07
Status: proposed version plan
Scope: Penguin's child-agent runtime, task lifecycle, delivery, isolation, and
cross-surface product contract

## Summary

Penguin has working sub-agent primitives, but ownership is split between
`ConversationManager`, `Engine`, `ToolManager`, `AgentExecutor`, `MessageBus`,
and presentation adapters. The immediate multi-agent runtime PR repairs several
truthfulness bugs: async tools remain on their owning event loop, child terminal
payloads are classified consistently, malformed admission fields fail closed,
and failed child creation rolls back lifecycle state.

Sub-Agents v2 should build on that foundation by making a child agent a
first-class runtime/session record owned by one tree-scoped controller. It
should then add durable tasks and delivery, enforced policy, explicit execution
environments, and one shared API/event contract for CLI, TUI, web, MCP, and
Python consumers.

This plan complements `context/tasks/multi-agent-v2.md`. That document remains
the audit of v1 truth gaps; this document defines the broader target
architecture and release sequence.

## Product Direction From `features.md`

The feature comparison changes the priority order. Penguin already has:

- canonical runtime events and durable replay;
- persistent sessions, goals, checkpoints, and project/task state;
- category-priority context-window trimming;
- OpenCode-compatible child-session navigation foundations;
- provider, tool, permission, MCP, and process-runtime foundations.

The missing product bar is therefore not “more ways to spawn helpers.” The
highest-value gaps are:

1. explicit execution-environment and worktree lifecycle;
2. durable unattended run ownership and recovery;
3. one enforceable per-agent policy model;
4. visible and truthful sub-agent task state;
5. delivery acknowledgement and durable inbox/history;
6. structured context products alongside CWM trimming.

Sub-Agents v2 should preserve Penguin's identity: truthful lifecycle state and
evidence-backed completion matter more than autonomous-agent spectacle.

## Reference Implementations

### Prime Agent

Use Prime as the reference for a child runtime that owns its session, selected
model, services, tools, and descendants. Important patterns:

- build and validate a complete child runtime before publishing it;
- dispose partially built runtimes on every failure path;
- keep the child's selected model stable across initial and follow-up turns;
- persist runtime selection and prove that rejected selections leave no child;
- make runtime disposal idempotent and await descendant cleanup.

Relevant files:

- `reference/prime-agent/packages/coding-agent/src/core/agent-session-runtime.ts`
- `reference/prime-agent/packages/coding-agent/test/suite/regressions/4649-subagent-model-selection.test.ts`
- `reference/prime-agent/packages/coding-agent/docs/long-running-agents.md`

### OpenAI Codex

Use Codex as the reference for tree-scoped control and atomic admission:

- reserve capacity, name, and canonical path atomically;
- commit the reservation only after the child thread is ready;
- release reservations automatically on failure;
- distinguish queue-only messages, follow-up turns, interruption, and waiting;
- share concurrency limits across the entire descendant tree;
- persist and restore parent/child graph edges.

Relevant files:

- `reference/codex/codex-rs/core/src/agent/control.rs`
- `reference/codex/codex-rs/core/src/agent/registry.rs`
- `reference/codex/codex-rs/core/src/agent/control/spawn.rs`
- `reference/codex/codex-rs/core/src/tools/handlers/multi_agents_v2/`

### OpenCode

Use OpenCode as the compatibility reference for child sessions and permissions:

- a task creates or resumes a first-class child session;
- parent cancellation propagates to the child session;
- permissions decide allow/deny/ask without changing execution substrate;
- child model, permissions, session id, and live summary are inspectable;
- child sessions remain directly navigable from the parent transcript.

Relevant files:

- `reference/opencode/packages/opencode/src/tool/task.ts`
- `reference/opencode/packages/opencode/src/permission/next.ts`
- `reference/opencode/packages/opencode/src/session/status.ts`

### Pi

Use Pi as the small-kernel reference:

- keep subprocess containment and event contracts simple;
- pass model and tool configuration explicitly;
- propagate abort signals and escalate termination after a grace period;
- clean temporary resources in `finally`;
- preserve full results while truncating only display output.

Relevant file:

- `reference/pi-mono/packages/coding-agent/examples/extensions/subagent/index.ts`

### Background Agents And Hermes

Use these only when adding detached, restart-safe execution:

- separate the durable control plane from the execution plane;
- queue prompts in order while a worker is busy or disconnected;
- acknowledge durable message ids instead of equating enqueue with processing;
- expose explicit cancellation endpoints and state conflicts;
- use leases, heartbeats, snapshots, and recovery for unattended work.

Relevant files:

- `reference/background-agents/docs/HOW_IT_WORKS.md`
- `reference/background-agents/packages/sandbox-runtime/src/sandbox_runtime/bridge.py`

## Canonical Vocabulary

| Term | Meaning |
|---|---|
| Agent | A configured reasoning identity that may own one or more sessions over time. |
| Child agent | An agent with a persisted parent edge in one agent tree. |
| Agent runtime | The live model, tool policy, session services, event scope, and cancellation ownership for an agent. |
| Agent session | Durable conversation state. A child runtime may resume an existing child session. |
| Agent task | One bounded execution attempt assigned to an agent. Tasks have ids independent of agent ids. |
| Admission | Validation and atomic publication of a child runtime into an agent tree. |
| Wait | Observe task or tree activity until a deadline. A wait timeout never cancels work. |
| Cancel | Request termination of one active task and await cleanup. |
| Pause | Reject new task admission for an agent without implying cancellation. |
| Resume | Make a paused agent available; it does not replay cancelled work. |
| Follow-up | Queue content and trigger a new turn when the agent can accept it. |
| Steer | Interrupt or redirect the active turn according to an explicit policy. |
| Message | Queue-only communication that does not implicitly start a turn. |
| Execution environment | The checkout/worktree, directory, sandbox/backend, credentials, and cleanup policy used by a task. |

## Target Architecture

### `AgentTreeController`

Introduce one root-tree-scoped controller under `penguin/multi/`. It is created
for a root session/runtime and shared by descendants, not stored as a
process-global singleton.

It owns:

- the live child runtime registry;
- admission reservations and tree budgets;
- parent/child edges;
- task creation, cancellation, waiting, and shutdown;
- runtime lookup and resume;
- delivery routing;
- environment leases;
- publication of canonical runtime events.

`PenguinCore` remains an orchestrator/facade. `ToolManager`, parser actions,
routes, CLI, and MCP call the controller through services; none owns an
executor or independently mutates the agent graph.

### Admission transaction

Admission follows one state transition:

```text
validate request
  -> reserve name/path/capacity
  -> resolve model + policy + environment
  -> create or resume child session
  -> construct child runtime
  -> persist runtime record + parent edge
  -> publish runtime
  -> commit reservation
```

Before commit, no public list/status endpoint may discover the child. Any
failure restores all registries, metadata, capacity, policies, environment
leases, engine registrations, and session artifacts owned by the transaction.

### Runtime records

Define typed records in focused schema modules:

```text
AgentRuntimeSpec
  agent_id
  parent_agent_id
  role
  model_config
  tool_policy
  permission_policy
  context_policy
  environment_policy
  depth

AgentTaskRecord
  task_id
  agent_id
  parent_task_id
  session_id
  environment_id
  state
  prompt_digest/title
  created_at/started_at/ended_at
  terminal_outcome
  usage/evidence references

MessageDeliveryRecord
  message_id
  sender/recipient
  mode
  accepted_at/delivered_at/processed_at
  state
  correlation ids
```

Persisted records and live runtime objects must be distinct. A restart can
reconstruct live ownership from durable state without serializing event-loop
objects or tasks.

### Terminal outcomes

Use one canonical outcome model across foreground and background work:

```text
completed | failed | aborted | cancelled | timed_out | unknown
```

Provider payloads, raised exceptions, explicit aborts, process exits, and
shutdown cancellation all map through one classifier. Presentation layers may
format outcomes but may not reinterpret them.

`timed_out` applies to a task's execution deadline. A wait deadline returns a
separate `wait_timed_out=true` observation and does not mutate task state.

## Version Workstreams

### V2.0 — Ownership And Atomic Admission

- Add `AgentTreeController` and `AgentAdmissionService`.
- Replace process-global `get_executor()` usage on production paths.
- Move graph mutation out of tools, parsers, routes, and `PenguinCore`.
- Add atomic name/path/capacity reservations.
- Persist parent edges and runtime specs before publication.
- Make runtime disposal idempotent and tree-aware.
- Reject every unknown or unsupported spawn option.

Exit criteria:

- failure injected after every admission step leaves no observable residue;
- simultaneous duplicate names produce exactly one child;
- capacity is shared across descendants and released after every failure;
- restored sessions reconstruct the same tree and runtime configuration.

### V2.1 — Task And Lifecycle Contract

- Separate `task_id` from `agent_id`.
- Replace ambiguous stop semantics with pause, cancel, resume, restart, delete.
- Support task history while limiting active tasks per policy.
- Make cancellation propagate through provider calls, tools, subprocesses, and
  descendants, with bounded escalation for processes.
- Make shutdown await all owned runtime disposal.

Exit criteria:

- wait timeout never cancels a task;
- cancellation is idempotent and leaves no live owned task;
- resume cannot imply restart;
- foreground and background paths produce the same terminal outcome.

### V2.2 — Enforced Runtime Configuration And Policy

- Replace metadata-only `default_tools` with an enforced `ToolPolicy`.
- Resolve model selection once at admission and keep it stable until an
  explicit runtime reconfiguration event.
- Inherit permissions by narrowing parent policy; child policy cannot silently
  broaden authority.
- Apply policy to built-in tools, shell patterns, MCP tools, skills, external
  directories, background execution, and environment credentials.
- Keep allow/deny/ask authorization independent from sync/async execution.

Exit criteria:

- unavailable tools are absent from schemas and denied at dispatch;
- initial, follow-up, and resumed child turns use the persisted selected model;
- malformed or unauthorized runtime configuration leaves no child;
- preapproved async tools execute on the caller's owning loop.

### V2.3 — Delivery And Durable Inbox

- Define message modes: `message`, `follow_up`, and `steer`.
- Return acceptance records instead of a delivery boolean.
- Add a durable per-agent inbox and ordered pending queue.
- Track accepted, delivered, processed, rejected, and expired states.
- Resume recipients on demand according to policy.
- Correlate completion events back to parent tasks and sessions.

Exit criteria:

- missing/dead recipients reject deterministically;
- accepted-but-not-yet-processed work is visible after restart;
- duplicate delivery ids are idempotent;
- late/stale child events cannot overwrite newer parent state.

### V2.4 — Execution Environments And Worktrees

- Introduce `ExecutionEnvironment` as durable state.
- Support current checkout and isolated git worktree backends first.
- Define inheritance, branch naming, dirty-tree policy, cleanup, and handoff.
- Bind directory, project/workspace roots, credentials, and tool policy to the
  environment rather than ambient process state.
- Leave container, SSH, and remote sandboxes behind the same interface for
  later implementations.

Exit criteria:

- parallel write-capable children can run in separate worktrees;
- no child can accidentally resolve tools against another environment root;
- cleanup never deletes an uncommitted user worktree;
- TUI/web surfaces show the active environment and diff/handoff state.

### V2.5 — Cross-Surface Product Contract

- Add typed service APIs for tree, runtime, task, delivery, and environment.
- Project canonical events into OpenCode task/session cards without making the
  TUI contract the runtime source of truth.
- Show tree depth, role, model, state, usage, environment, and terminal outcome.
- Expose identical semantics through CLI, web, Python API, MCP, and TUI.
- Add parent-to-child and child-to-parent navigation.

Exit criteria:

- every surface reports the same persisted task and lifecycle state;
- failed and aborted children never render as successful task cards;
- reconnect/replay reconstructs current tree state without a live-process
  side channel.

### V2.6 — Bounded Work Units And Context Products

Do not hard-code planner/implementer/reviewer as the architecture. Treat roles
as execution policies that compile to the same task primitives.

- Add bounded work-unit result artifacts (“episodes” in the Slate comparison).
- Preserve goal, decisions, files, commands, evidence, failures, and open
  questions without copying the full transcript.
- Allow parent tasks and later sessions to consume these context products.
- Keep structured context products complementary to CWM category-priority
  trimming; do not describe current CWM behavior as compaction.
- Add orchestration recipes only after the lower-level contract is stable.

## Assurance Plan

Follow `context/tasks/testing-pyramid.md`. Live-provider checks are opt-in smoke
tests, never the proof of correctness.

### Deterministic unit and contract tests

- strict spawn schema, including unknown fields and type confusion;
- terminal-outcome classifier matrix;
- policy inheritance and tool visibility;
- message-mode semantics;
- persistence round trips for runtime/task/delivery records.

### Fault-injection admission tests

Inject failure after each step:

- model/policy resolution;
- provider client construction;
- session creation and metadata save;
- context initialization;
- environment acquisition;
- engine/runtime registration;
- parent-edge persistence;
- public registry publication;
- initial task creation.

After every failure assert no registry entry, edge, task, policy, slot,
environment lease, engine registration, or owned session artifact remains.

### State-machine tests

Model transitions for:

- admission reservation and commit/rollback;
- task pending/running/terminal states;
- pause/cancel/resume/restart/delete;
- message accepted/delivered/processed/rejected;
- worker disconnect, lease expiry, and recovery;
- parent/child shutdown ordering.

Generate long randomized transition sequences and assert invariants after every
step.

### Concurrency tests

- simultaneous duplicate spawn;
- tree-wide capacity under competing descendants;
- cancel racing completion;
- wait racing shutdown;
- follow-up racing recipient completion;
- restart recovery racing stale worker acknowledgement.

Use barriers/events rather than timing sleeps wherever possible.

### Fake-provider integration tests

- selected child model handles initial, follow-up, and resumed turns;
- parent model changes do not mutate an existing child;
- incomplete streams and provider errors become truthful terminal outcomes;
- native tool replay remains adjacent within each child session;
- cancellation releases provider/tool resources;
- child CWM priority/recency trimming remains session-scoped.

### Cross-surface contract tests

Freeze shared response/event fixtures and verify CLI services, web routes, MCP,
Python API, and the TUI projection against the same records.

## Migration Sequence

Keep reviewable vertical slices:

1. Controller and atomic admission behind the existing spawn facade.
2. Durable task ids and canonical outcomes behind existing status/wait tools.
3. Explicit lifecycle operations with `stop_sub_agent` as a deprecated alias.
4. Enforced model/tool/permission configuration.
5. Delivery records and inbox; retain MessageBus for event fan-out only.
6. Worktree execution environment.
7. Cross-surface UX and removal of compatibility shims.
8. Context products and optional orchestration recipes.

Each slice must include schema, persistence, service, runtime, failure tests,
and one presentation projection. Avoid a second large PR that changes every
layer without an independently testable contract.

## Explicit Non-Goals

- No distributed actor framework in the first v2 release.
- No durable remote workers before leases and recovery are specified.
- No signed execution receipts until work crosses a real trust boundary.
- No forced planner/implementer/reviewer pipeline.
- No claim that metadata-only tool lists are security policy.
- No replacement of canonical runtime events with TUI-specific events.
- No replacement of CWM trimming with opaque summarization.

## Open Decisions

1. Should one agent allow one active task or a configurable number?
2. Which agent/session/task records belong in the existing SQLite runtime
   ledger versus a dedicated control-plane store?
3. Does child policy inheritance permit explicit escalation with approval, or
   only narrowing?
4. When is a child session owned by an admission transaction and therefore safe
   to delete during rollback?
5. What is the worktree handoff contract: patch, merge, commit, or user choice?
6. Which execution modes may use `steer`, and what happens to interrupted tool
   calls?
7. When should a completed work unit be promoted into a reusable context
   product, and which evidence gate validates it?

## Definition Of Done

Sub-Agents v2 is complete when Penguin can create, run, observe, message,
cancel, resume, recover, and clean up a child agent without any surface lying
about its configuration or state; parallel write-capable children can use
isolated environments; and deterministic tests prove rollback, concurrency,
policy, provider-fault, delivery, and restart invariants.
