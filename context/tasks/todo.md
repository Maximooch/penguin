# Follow-Up PR Todo

## Purpose

This file is the **current status snapshot** for the major follow-up workstreams after the
RunMode / Project / ITUV core-systems push.

It is intentionally organized by execution reality, not by the original planned order.
The previous version of this file became stale once several follow-up threads started in
parallel.

---

## Done

### RunMode / Project / ITUV Core Truth
- [x] Restore core RunMode / Project / ITUV truth and verification path
- [x] Add clarification wait/resume proof path
- [x] Add CLI scripted surface verification
- [x] Add web/API scripted surface verification
- [x] Align public docs/checklists with current runtime truth
- [x] Archive PR summary for the merged core-systems branch

### Current PR / Docs Alignment
- [x] Update public docs for typed dependencies, diagnostics, and clarification handling
- [x] Review `context/process/blueprint.template.md` for typed dependency and diagnostics drift
- [x] Review `context/tasks/testing_scenarios.md` for stale scenarios after clarification, diagnostics, and dependency-policy changes
- [x] Final docs pass for README / architecture / surface docs so they match current branch truth
- [x] PR write-up: summarize what the core-systems branch fixed, what it verified, and what was explicitly deferred

### Release / Versioning
- [x] Bump version to `0.6.3`
- [x] Update README version highlights for OpenAI / Codex integration emphasis
- [x] Push `v0.6.3` git tag

---

## In Progress

### Program: Runtime Reliability and Performance Recovery

**Status:** diagnosis complete / implementation in progress on
`fix/runtime-reliability-recovery`

**Priority:** supersedes product-facing follow-up work until Penguin can run long
sessions without silent stalls, unbounded local persistence, or guessed manual
`resume` prompts.

#### Confirmed symptom and operating rules

- [x] During the common outage the TUI remains `running`, sometimes displaying
  `no events <duration> • running <duration>`.
- [x] Request existence and actual provider/runtime progress are separate liveness
  signals.
- [x] Port `9000` is the production backend and must not be used for verification.
- [x] Port `8080` is the test backend for this program and must use isolated mutable
  storage for workspace, logs, conversations, checkpoints, artifacts, backups, and
  the runtime-event ledger.
- [x] CWM v2 is a separate follow-up PR. This PR may repair native
  tool-call/tool-result adjacency because malformed provider history is a protocol
  correctness bug, but it must not implement CWM v2 budgeting, slimming,
  summarization, retrieval, or compaction.

#### Evidence baseline

- [x] A checkpoint worker emitted 96,998 cross-event-loop queue errors in roughly
  2.2 seconds without backoff before backend replacement.
- [x] Checkpoint storage reached roughly 13 GB / 41,000 files despite a configured
  1,000-auto-checkpoint maximum that was not enforced automatically.
- [x] The data volume reached 99% usage and recent operations failed with `ENOSPC`.
- [x] OpenAI/Codex used an unbounded active-stream read and produced multi-minute
  waits that ended only after user abort.
- [x] Provider replay was bounded to one safe retry, but exhausted recovery became a
  terminal result hidden by the TUI.
- [x] The chat route returned HTTP 200 for `max_iterations`, repeated empty/tool-only
  stalls, and recoverable provider failures while the TUI discarded structured
  status and treated any 2xx response as success.
- [x] The effective TUI request cap was 100 iterations; multiple 15–30 minute runs
  ended with partial work and required another `resume` turn.
- [x] Millisecond tools sometimes accumulated tens of seconds of Penguin-local
  orchestration and persistence latency.
- [x] The runtime-event ledger synchronously committed each event, stored cumulative
  part snapshots, repeated busy status, and ran SQLite cleanup on live delivery.
- [x] Production and test servers used different ports but shared the default runtime
  event database.
- [x] The TUI parsed but did not retain/send SSE event IDs and did not reconcile
  canonical session state after reconnect.
- [x] Roughly 461 KB of canonical message text occupied a roughly 45 MB session plus
  a 45 MB backup, dominated by OpenCode transcript metadata and duplicated tool
  output.
- [x] Terminal tool events, engine iteration saves, and autosave rewrote the same
  session concurrently; fixed temp paths produced rename collisions.
- [x] Nominal prompt modes shared a roughly 53k-character / 12k-token system prompt
  before roughly 50 tool schemas.
- [x] Prompt instructions imposed a 5–12 analysis-tool minimum and serial
  one-action-per-response behavior.
- [x] Current CWM behavior is category-priority/recency trimming, not compaction or
  summarization.
- [x] Independent tool-result trimming orphaned native tool calls, forced large Codex
  replay-sanitization drops, shifted request prefixes, and correlated with reduced
  cache reads.

#### Phase 0 — Operational containment and measurement

- [x] Add a supported `127.0.0.1:8080` test configuration with a unique
  `PENGUIN_WORKSPACE` and ledger path; keep all mutable artifacts inside it.
- [x] Emit startup diagnostics for server role, host/port, PID, workspace, log,
  ledger, checkpoint, and conversation paths.
- [x] Warn or fail when two backends would unintentionally share mutable runtime
  storage; prove 8080 cannot contend with 9000 in deterministic two-server tests.
- [x] Add a read-only checkpoint inventory/cleanup planner reporting candidates,
  retained items, bytes, age buckets, ownership, active protection, policy reasons,
  and recovery/archive steps. Default to dry-run; do not execute destructive mode.
- [x] Add deterministic disk-space/checkpoint-growth safety floors that stop new
  background checkpoint work before `ENOSPC` while preserving active conversation
  behavior and visible errors.
- [x] Instrument provider, UI/event, ledger, tool, transcript, session-save,
  checkpoint, context, and request stages with monotonic progress timestamps and
  privacy-safe diagnostics.
- [x] Record reproducible isolated-8080 fake-provider baselines for fresh and large
  sessions before Phase 1.

Phase 0 evidence:

- Supported runner: `uv run python scripts/run_runtime_reliability_server.py`.
  Imports install isolation before configuration; `--describe` does not start a
  server. Cross-process leases fail promptly rather than contending.
- Real-writer isolation tests cover session, checkpoint, runtime-event SQLite,
  local-auth, provider-credential, and tool-artifact persistence while proving a
  production sentinel tree remains byte/stat identical.
- Cleanup remains a read-only plan by default. Confirmed execution archives rather
  than deletes and requires the exact resolved workspace; it was not executed during
  this goal.
- The local test volume was already below the configured critical free-fraction
  floor, and automatic checkpoint admission correctly stopped without preventing
  conversation/session persistence.
- Baseline evidence is retained at
  `context/tasks/evidence/runtime-reliability-phase0-baseline.json`. In the first
  deterministic run, fresh request processing was about 49 ms (including roughly
  12 ms ledger connection, 10 ms schema initialization, 12 ms ledger cleanup, and
  6 ms session save). The 202-message fixture spent about 8 ms assembling context
  and 22 ms saving the session. Provider and controlled tool execution were
  sub-millisecond; tool orchestration was about 0.7 ms.
- Baseline uncertainty remains explicit: this calls the production REST handler and
  real local components without socket overhead, uses a minimal core instead of the
  full PenguinCore/Engine loop, and does not yet exercise Phase 1/2 watchdog,
  reconnect, fault, or queued-writer behavior.
- Phase 0 gate: 71 focused tests plus 26 checkpoint compatibility tests and the full
  28-test Codex OAuth suite passed. No live provider or network server was used.

#### Phase 1 — Stop, retry, and visible-state correctness

- [x] Make checkpoint worker queues/tasks single-loop-owned, bounded, idempotent, and
  offload serialization/compression/file/index work from the event loop.
- [x] Add bounded checkpoint retry/backoff, rate-limited logging, a circuit breaker,
  and automatic count/age/size retention with active/manual/branch protection.
- [x] Add OpenAI/Codex chunk-idle and total-attempt watchdogs with typed timeout,
  disconnect, incomplete-stream, and retry-exhaustion failures.
- [x] Keep provider replay bounded and partial-output/native-tool safe; guarantee
  provider, request, session, and tool-state release on every terminal path.
- [x] Preserve structured API outcome truth in the TUI: status, recoverability,
  details, iteration/action counts, partial output, abort, and cancellation.
- [x] Distinguish running, reconnecting, stalled/degraded, max-iterations, provider
  exhaustion, repeated empty/tool-only loops, aborted, cancelled, completed, and
  failed states.
- [x] Base healthy liveness on real progress, add bounded POST/gate waits, and expose
  Interrupt/Retry/Resume actions for stalled runs.
- [x] Define and test one explicit iteration/continuation contract rather than hiding
  loops behind a larger cap.

Phase 1 evidence is retained at
`context/tasks/evidence/runtime-reliability-phase1-gate.json`. The gate covers
checkpoint lifecycle/retention, typed provider watchdogs and bounded replay,
structured REST/WebSocket/TUI terminal state, continuation leases, and native
tool adjacency. No live provider or port `9000` was used.

#### Phase 2 — Event, transcript, checkpoint, and session persistence

Phase 2 design audit (before implementation): the current live recorder still
waits on synchronous SQLite append/cleanup, stores cumulative text projections,
and has no writer lifecycle. Runtime event IDs are process-counter based, so
restart-safe identity and conflict reporting are prerequisites. `server.connected`
and `server.replay_gap` are control frames and must not advance a durable cursor.
The TUI must retain only committed, scope-matching event IDs and reconcile
canonical state after replay. See the read-only audit recorded in this task's
working notes; these constraints remain open until Phase 2 lands.

- [x] Move ledger writes behind a bounded single-writer queue with batched
  transactions and explicit durability/backpressure/overflow/shutdown semantics.
- [x] Persist event envelopes through the bounded writer, coalesce unchanged busy
  heartbeats, preserve real progress telemetry, and move cleanup/WAL checkpoint work
  off live delivery.
- [x] Retain/send `Last-Event-ID`, replay/deduplicate from the durable cursor, surface
  replay gaps, reconcile canonical status, and preserve newer live events over stale
  hydration.
- [x] Bound connection history and include replay decisions in debug exports.
- [x] Bound OpenCode transcript metadata and store full tool output once with artifact
  references through the existing canonical tool-result record path; migration of
  legacy duplicated output remains an explicit follow-up fixture.
- [x] Coalesce durable saves; serialize each session's writes with unique temp files,
  atomic replacement, and protection from autosave/request-save stale writers.
- [x] Avoid repeated global index rewrites for unchanged saves.
- [x] Preserve native tool-call/tool-result units atomically through existing trim,
  transcript, replay, and provider sanitation boundaries without implementing wider
  CWM v2 behavior.
- [x] Add production-path ledger burst, multi-server isolation, ledger fault,
  reconnect, save-concurrency, adjacency, storage-growth, and latency coverage.

Phase 2 evidence is retained at
`context/tasks/evidence/runtime-reliability-phase2-gate.json`. The gate covers 98
focused backend tests, the independent read-only scheduler characterization, and 28
focused Bun/TUI tests with typechecking. Legacy duplicated transcript migration is
explicitly retained as a CWM-adjacent follow-up fixture rather than silently rewritten.

#### Phase 3 — Tool-loop, request, and cache performance

- [x] Parallelize independent read-only inspection while serializing mutation, Git,
  process control, installs, tests, and order-dependent tools.
- [x] Measure queue/schedule/event/persistence separately from tool execution and use
  ordered native batching where required.
- [x] Replace the silent 100-iteration mismatch with the existing documented
  cap/continuation contract and visible stale/repeated-tool-loop detection.
- [x] Measure system prompt, messages, tool schemas, provider framing, input/cached
  input/output/reasoning, and service-tier/model-variant boundaries per request.
- [x] Add a bounded stable session-scoped OpenAI `prompt_cache_key`, distinct between
  sessions, while preserving prefix stability and explicit cache-boundary events.
- [x] Reuse provider clients/connections where safe rather than recreating them every
  iteration; native adapters already own reusable clients and HTTP fallbacks use the
  shared connection pool.

Phase 3 evidence is retained at
`context/tasks/evidence/runtime-reliability-phase3-baseline.json`; the focused gate
also covers 147 provider/tool/cache tests. The deterministic fresh and large-session
8080 harness records separate tool queue, schedule, execution, persistence, provider,
session-save, ledger, and request timings without starting a network server.

#### Phase 3.5 — Prompt and immediate-context engineering

**PR placement:** Phase 3.5 follows Phase 3 and remains in this
runtime-reliability PR. It must be testable without changing historical conversation
selection.

**Boundary:** this phase owns instructions, task/mode routing, tool
descriptions/exposure, and the compact active-turn envelope. Conversation-history
selection, global budgets, historical tool-output slimming, summarization, retrieval,
and compaction remain CWM v2.

Ponytail is a useful input to this phase, not a dependency to install: apply its
YAGNI ladder after tracing the real request path, prefer existing/native mechanisms,
and make implementation mode stop at the first sufficient solution. Preserve
Penguin's trust-boundary validation, data-loss handling, safety, accessibility,
repository instructions, and proportionate verification. See
<https://github.com/DietrichGebert/ponytail>.

- [x] Wire the mode-aware prompt builder into the real request path and prove
  `direct`, `implement`, `review`, `explain`, and compatibility modes materially
  differ.
- [x] Make implementation lean and implementation-first; remove the blanket 5–12
  analysis-tool minimum and legacy one-tool-action-per-turn rules.
- [x] Resolve contradictory completion/continuation/stopping instructions against the
  actual engine contract.
- [x] Inventory instructions/tool schemas by tokens and purpose; remove duplication
  and stale guidance without weakening safety, user/repository instructions, or tool
  contracts.
- [x] Use task/mode-aware tool exposure or concise descriptions where compatible and
  explicitly allow safe parallel read-only inspection.
- [x] Separate a stable cacheable instruction prefix from a compact structured
  active-turn envelope; fingerprint composition and report each overhead section.
- [x] Add prompt snapshot/contract and behavioral fixtures; do not implement deferred
  CWM history or compaction work.

Phase 3.5 evidence is retained at
`context/tasks/evidence/runtime-reliability-phase35-prompt-metrics.json`. The active
implementation path now uses a mode-aware static prefix plus a compact request-local
envelope; compatibility mode retains the legacy full surface for callers that need it.

#### Phase 4 — CWM v2 separate-PR readiness and handoff

- [x] Treat Phase 4 in this branch as documentation/evidence handoff only. Begin CWM
  v2 implementation only after this PR is independently verified, preferably from
  its merged result, so the two change sets can be tested in isolation.
- [x] Lock the PR boundary: this branch owns reliability, persistence, reconnect,
  request/tool-loop/cache performance, prompt engineering, accounting, and the
  native-adjacency exception only.
- [x] Keep CWM v2 final-packet assembly, elastic budgets, historical tool-output
  slimming, optional summarization, retrieval, compaction lifecycle, policies, and
  persisted-session migration in a separate follow-up PR.
- [x] Update `context/tasks/CWM-v2.md` with verified post-fix evidence and retain
  repeatable fresh/large/tool-heavy baselines plus request/adjacency/transcript/tool
  output/attachment/replay fixtures.
- [x] Produce a `/goal`-ready follow-up brief with entry criteria, phases, tests,
  migration/rollback plan, metrics, and exit criteria. Use branch `feat/CWM-v2` or
  `Penguin-Context-Window-Manager-v2` when that follow-up begins.
- [x] Confirm this diff contains no CWM v2 implementation beyond native adjacency.

Phase 4 handoff is complete as documentation/evidence only. The executable brief is
`context/tasks/CWM-v2-followup-goal.md`; CWM v2 implementation remains deferred to
its own branch and PR.

#### Program exit criteria

- [ ] No backend worker/provider path can wait or error-loop without a bound.
- [ ] `no events` becomes a truthful stalled/degraded state with bounded visible
  recovery; all non-completed reasons remain visible to the TUI.
- [ ] 8080 verification cannot read as active state, lock, mutate, or contend with
  9000 production runtime storage.
- [ ] Checkpoint, ledger, transcript, session, backup, artifact, and log growth are
  bounded; disk safety prevents another `ENOSPC` cascade.
- [ ] Live UI delivery does not synchronously wait on per-event commits or large
  session rewrites; local overhead is separately measured.
- [ ] Durable cursor replay, canonical reconnect status, serialized atomic saves, and
  canonical tool output pass concurrency/stress tests.
- [ ] Native tool adjacency survives trimming/replay/provider sanitation.
- [ ] Tool concurrency safety, iteration continuation, prompt cache affinity, prompt
  modes, stable-prefix/active-turn composition, and full request accounting are
  implemented and verified.
- [ ] Public docs describe shipped runtime truth; focused fault/concurrency/TUI/stress
  tests, relevant Bun suites, Ruff/format, and core pytest verification pass.
- [ ] Record before/after evidence, commands, storage behavior, residual risks, and
  the executable CWM v2 handoff before completing the goal.

### PR: CLI Workspace Semantics and Ergonomics

**Status:** materially underway / first implementation slice exists

Completed in this thread:
- [x] Resolve the `project create --workspace` honesty gap
- [x] Clarify execution root vs project workspace behavior in command output
- [x] Improve project creation output so location semantics are obvious
- [x] Add/update regression coverage for explicit/default workspace behavior
- [x] Refresh relevant docs for project-create workspace semantics

Still remaining in this PR/workstream:
- [ ] Improve help/discoverability for project/task workflows more broadly
- [ ] Reduce safe CLI duplication only where tests protect behavior

Reference:
- `context/tasks/cli-interface-ergonomics-plan.md`
- `context/tasks/cli-refactor-and-bootstrap-audit.md`
- `context/tasks/cli-workspace-semantics-pr1-checklist.md`

### PR: RunMode Commands and Loop Ownership Audit / Command Truth

**Status:** audit done, Phases 1/2/3/5/6 materially done, closeout decision pending

Completed in this thread:
- [x] Audit `--run`, `--247`, and `--continuous` semantics for current truth and usability
- [x] Decide `--247` remains a public alias / product-language flag
- [x] Clarify the current no-task continuous-mode behavior in the audit and checklist
- [x] Audit loop ownership boundaries between `RunMode` and `Engine`
- [x] Record completed findings, open questions, and recommended first PR scope
- [x] Create exact PR1 checklist for command-truth cleanup
- [x] Complete Phase 1 contract-definition pass
- [x] Land Phase 2 CLI help/output truth changes materially
- [x] Complete Phase 3 time-limit truth investigation
- [x] Complete Phase 5 docs alignment for RunMode truth
- [x] Complete Phase 6 web/API truth slice
  - explicit route-shape coverage for `waiting_input`, `time_limit_reached`, and `idle_no_ready_tasks`
  - SSE/session-status coverage for clarification, time-limit, and idle/no-ready-work truth
  - `PenguinCore.emit_ui_event(...)` bridge widened for those statuses

Still remaining in this workstream:
- [ ] Clean up the one non-critical brittle CLI help-text assertion or explicitly defer it
- [ ] Decide whether any tiny `Engine.run_task(...)` cleanup belongs in this PR or should be deferred
- [ ] Decide whether a full auth-bootstrap end-to-end confirmation is needed now or can be deferred
- [ ] Commit/push the remaining Phase 6 + checklist changes if not already bundled

Reference:
- `context/tasks/runmode-command-loop-audit.md`
- `context/tasks/runmode-command-truth-pr1-checklist.md`

---

## Next

### PR: Project Bootstrap Workflow MVP

**Why next:** high leverage once workspace semantics and runmode command truth are stable enough

- [ ] Add `penguin project init "name" --blueprint ./blueprint.md`
- [ ] Add `penguin project start <project-id|name>`
- [ ] Make project selection deterministic and honest
- [ ] Preserve orchestration/runtime truth in bootstrap commands
- [ ] Surface clarification / pending-review outcomes clearly in the high-level workflow

Reference:
- `context/tasks/project-bootstrap-workflow.md`
- `context/tasks/cli-refactor-and-bootstrap-audit.md`

### PR: RunMode Command Truth Cleanup Closeout

**Why next:** if the current runmode truth branch/PR is left half-finished, the audit loses value

- [ ] Finish remaining Phase 2 cleanup/tests
- [ ] Decide whether to execute Phase 6 web/API truth pass now
- [ ] Merge the runmode command-truth work or intentionally split remaining pieces

Reference:
- `context/tasks/runmode-command-truth-pr1-checklist.md`

---

## Deferred

### PR: PenguinAPI Surface Refresh

**Reason deferred:** lower immediate leverage than CLI/web/runtime truth; still important, but not the bottleneck this week

- [ ] Audit `PenguinAPI` method contracts against current runtime truth
- [ ] Verify clarification-flow parity through the Python API surface
- [ ] Review/normalize result shapes where needed
- [ ] Refresh Python API docs/examples
- [ ] Add a dedicated library-surface verification trail

Reference:
- `context/tasks/penguinapi-surface-refresh-plan.md`

### PR: Reliability Pass 2

**Reason deferred:** valuable hardening, but not the immediate unlock for product-facing flow

- [ ] Extend Hypothesis/property-based coverage for dependency-policy semantics
- [ ] Add stateful transition tests for `TaskStatus` and `TaskPhase`
- [ ] Add clarification lifecycle invariants for waiting/resume behavior
- [ ] Decide whether waiting tasks should release execution slots for other ready tasks
- [ ] Keep verification-planning docs aligned without pulling in premature TLA+ v2 scope

Reference:
- `context/tasks/runmode-project-ituv-checklist.md`
- `context/tasks/penguin_tla.md`

### Later / Larger Runtime Cleanup

**Reason deferred:** architecture cleanup should follow explicit contract truth, not race ahead of it

- [ ] Broader `cli.py` decomposition/refactor
- [ ] Larger `RunMode` / `Engine` loop cleanup beyond the surgical command-truth slice
- [ ] Unify time-limit semantics across RunMode, task/project budgets, and ITUV phase timeouts
- [ ] Deeper web/API surface truth pass if not included in the current runmode truth PR
- [ ] `penguin/llm` Responses/Codex follow-up refactor: preserve more structured Responses semantics end-to-end so OpenAI/Codex tool-only turns rely less on engine-side empty-loop heuristics and more on first-class tool/result/response state

Reference:
- `context/tasks/web-and-tui-bugfix.md`
- `context/tasks/tui-opencode-fork-alignment-plan.md`

### PR: Core Runtime Decomposition Pass

**Reason deferred:** high leverage for long-term reliability, but too invasive to mix with current command/bootstrap work

- [ ] Extract RunMode/session-status bridging concerns out of `core.py`
- [ ] Isolate streaming finalization / UI event normalization from general core orchestration
- [ ] Reduce `current_runmode_status_summary` / `_handle_run_mode_event` coupling where tests protect behavior
- [ ] Identify a stable services/helpers split for `core.py` before moving larger blocks
- [ ] Add regression coverage around any extracted event/status bridge behavior

Reference:
- `penguin/core.py`
- `context/tasks/runmode-command-loop-audit.md`

### PR: Project Orchestration Hardening

**Reason deferred:** high-value reliability work, especially in `penguin/project`, but should follow the current truth/UX passes

- [ ] Audit `workflow_orchestrator.py` against current RunMode / ITUV truth and remove stale assumptions
- [ ] Replace `print()`-based orchestrator debug paths with logging / structured diagnostics
- [ ] Harden `ProjectTaskExecutor` so it does not collapse nuanced RunMode outcomes into generic executor success
- [ ] Re-check status/phase transitions through `manager.py`, `workflow_orchestrator.py`, and `models.py` for contradictions
- [ ] Add explicit regression tests for pending-review handoff, orchestration failure paths, and recipe/use gating

Reference:
- `penguin/project/workflow_orchestrator.py`
- `penguin/project/task_executor.py`
- `penguin/project/manager.py`
- `penguin/project/models.py`

### PR: Validation / VERIFY Maturity Pass

**Reason deferred:** current validation is improved but still pytest-centric and too narrow for higher-trust project automation

- [ ] Expand `ValidationManager` evidence beyond pytest exit codes and loose acceptance-criteria coverage
- [ ] Distinguish test evidence, usage-recipe evidence, and explicit verification artifacts more cleanly
- [ ] Tighten acceptance-criteria evaluation so "covered_by_test_evidence" is not the only meaningful success mode
- [ ] Add tests for no-tests-found, timeout, missing-pytest, and mixed evidence scenarios at the orchestration layer
- [ ] Decide which VERIFY semantics should stay MVP-simple vs move into a later TLA+/formal verification track

Reference:
- `penguin/project/validation_manager.py`
- `context/tasks/penguin_tla.md`

### PR: Legacy Workflow Surface Cleanup

**Reason deferred:** stale or parallel execution surfaces can quietly undermine the newer runtime truth if left unaudited

- [ ] Audit `dream_workflow.py` and any remaining alternate task/workflow entry points for stale constructor/runtime assumptions
- [ ] Deprecate or remove dead workflow surfaces that are no longer the real execution path
- [ ] Add a short architecture note documenting the authoritative runtime/orchestration paths

Reference:
- `penguin/project/dream_workflow.py`
- `architecture.md`

### PR: Engine Loop Cleanup Follow-On

**Reason deferred:** `run_task()` thin-wrapper refactor reduces risk, but broader engine-loop cleanup still remains

- [ ] Review remaining divergence between `run_response(...)` and `_iteration_loop(...)`
- [ ] Identify whether any task-mode result shaping should move fully into `LoopConfig` or helper functions
- [ ] Add coverage around message-callback/tool-output semantics and completion callbacks if further cleanup lands
- [ ] Remove any now-dead task-loop code left behind by the thin-wrapper refactor

Reference:
- `penguin/engine.py`
- `tests/test_engine_run_task_thin_wrapper.py`

---

## Strategic Read (April 17, 2026)

Current state:
- We are **behind on the original April feature timeline** in visible product terms.
- We are **ahead of where the repo was** on runtime truth, clarification handling, and public-surface verification.
- The last ~3 days produced the majority of the meaningful structural progress after ~2 weeks that were more dominated by bug-fixing and recovery work.

That means the correct interpretation is:
- not "everything is off the rails"
- not "the plan is on track"
- but rather: **the substrate is finally getting trustworthy enough that the next visible product steps can land on something real**.

---

## Suggested Immediate Order

1. Finish / close the RunMode command-truth PR cleanly
2. Finish / merge the CLI workspace semantics PR cleanly
3. Move to Project Bootstrap Workflow MVP
4. Revisit PenguinAPI Surface Refresh
5. Do Reliability Pass 2 after the product-facing path is less mushy

---

## Notes

- This file should be updated when work actually moves between buckets.
- Do not treat the original PR ordering as sacred if the real dependency graph changes.
- Track capabilities shipped, not just number of PRs opened.
