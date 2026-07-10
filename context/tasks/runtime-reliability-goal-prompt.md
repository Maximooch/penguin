/goal Deliver the Runtime Reliability and Performance Recovery PR and prepare the
separate CWM v2 follow-up described below in the isolated worktree
/Users/maximusputnam/Code/Penguin/penguin-runtime-reliability on branch
fix/runtime-reliability-recovery.

Continue across bounded goal turns until Phases 0 through 3.5, the Phase 4 CWM v2
handoff, and every current-PR exit criterion are genuinely complete. CWM v2 itself is
not implemented in this branch; it is a separate follow-up PR. A plan, diagnosis,
partial phase, green narrow test, or local mitigation is not completion. Preserve
progress between turns and resume from verified state without repeating completed
work.

## Authoritative scope

Treat this prompt as the authoritative task brief. The worktree was created from main
before the July 9 reliability findings were added to the original worktree's
context/tasks/todo.md. At the start of Phase 0, update this branch's
context/tasks/todo.md with the phase structure, findings, decisions, and exit criteria
from this prompt. Check off an item only after its implementation and required evidence
exist.

Before changing code, read:

- AGENTS.md
- README.md
- architecture.md
- context/tasks/testing-pyramid.md
- context/tasks/CWM-v2.md
- context/tasks/core-acbra-testing-refactor.md
- context/tasks/tui-opencode-fork-alignment-plan.md

Reconcile documentation against runtime truth. Do not trust stale claims in
architecture.md when code, tests, and captured logs disagree.

## Worktree and operational boundaries

- Work only in
  /Users/maximusputnam/Code/Penguin/penguin-runtime-reliability.
- Do not edit /Users/maximusputnam/Code/Penguin/penguin or any other worktree.
- Preserve unrelated changes and artifacts.
- Use uv for installs and Penguin execution.
- Port 9000 is the production Penguin backend. Never start, stop, probe destructively,
  interrupt, or repurpose it.
- Port 8080 is the required test-server port for this program.
- Every 8080 run must use isolated mutable storage, including an isolated
  PENGUIN_WORKSPACE, server-log directory, conversation store, checkpoint store, and
  runtime-event ledger. It must not share mutable state with the production backend.
- Before starting 8080, inspect its current owner. Do not kill an existing process
  unless it is demonstrably this worktree's disposable test server.
- Prefer deterministic fake-provider, contract, state-machine, concurrency, and
  fault-injection tests. Live-provider tests are opt-in smoke checks, not correctness
  proof.
- Do not delete, move, vacuum, or rewrite production checkpoints, conversations,
  logs, ledgers, or user data. Phase 0 may build and run a read-only cleanup dry run.
  Destructive cleanup requires separate explicit user approval after the dry-run
  report.
- Do not push, merge, open a PR, or modify production configuration unless explicitly
  requested. Make logically scoped local commits at verified phase boundaries so the
  long-running goal has durable recovery points.

## User-visible symptom to solve

During the common outage the TUI remains running. It may show:

no events <elapsed> • running <elapsed>

Treat request existence and real provider/runtime progress as different signals.
Request-count heartbeats must not make a stalled provider stream look healthy.

## Known evidence baseline

Reproduce or characterize these with deterministic probes before changing their
behavior. Refresh counts where the live workspace has changed, but preserve the
original evidence in the task notes.

- One checkpoint worker emitted 96,998 cross-event-loop queue errors in roughly
  2.2 seconds without backoff, followed by backend replacement.
- Checkpoint storage had grown to roughly 13 GB and 41,000 files even though the
  configured maximum was 1,000 automatic checkpoints.
- The data volume was 99 percent full, and recent runs hit ENOSPC during session save
  and apply_patch.
- OpenAI/Codex configured an unbounded active-stream read and produced multi-minute
  waits that ended only after user abort.
- A single safe provider replay explains why some failures resume automatically.
  Exhausted replay becomes a terminal provider result.
- The chat route returned HTTP 200 for max_iterations, repeated empty/tool-only
  stalls, and recoverable provider failures. The TUI discarded the structured body
  and treated any 2xx response as success.
- The effective TUI request cap was 100 iterations. Multiple 15 to 30 minute runs
  ended at the cap with partial output and required a new resume turn.
- Millisecond tools sometimes incurred tens of seconds of Penguin orchestration
  overhead before or after execution.
- The runtime-event ledger synchronously serialized and committed every event,
  persisted growing cumulative part snapshots, repeated busy projections, and ran
  periodic SQLite cleanup on the live delivery path.
- Production and test backends used different ports but shared the same default
  runtime-event database.
- The TUI parsed SSE event IDs but did not retain or send Last-Event-ID and did not
  reconcile canonical session status after reconnect.
- A session with roughly 461 KB of canonical message text occupied roughly 45 MB plus
  a 45 MB backup, dominated by OpenCode transcript metadata and duplicated tool
  output.
- Terminal tool events, engine iteration saves, and autosave could rewrite the same
  session concurrently. Fixed temp paths produced repeated rename collisions.
- The active system prompt was roughly 53,000 characters / 12,000 tokens across every
  nominal prompt mode, before about 50 tool schemas.
- Prompt instructions imposed a 5 to 12 tool-call minimum for analysis and favored
  serial one-action-per-response work.
- Current CWM behavior was category trimming, not compaction or summarization. It
  repeatedly removed SYSTEM_OUTPUT while the total context was below the global
  budget.
- Independent tool-result trimming orphaned native tool calls, forced large Codex
  replay sanitization, shifted prompt prefixes, and correlated with cache-read
  collapse.

## Execution discipline

1. Work phase by phase in order.
2. Establish a failing deterministic test or measured characterization before each
   behavior change.
3. Implement the smallest coherent vertical slice that changes the real production
   path, not a test-only surrogate.
4. Re-run focused tests after each slice and the broader relevant suite at each phase
   gate.
5. Add timing and state evidence before claiming a performance improvement.
6. Parallelize independent read-only investigation where useful. Serialize conflicting
   edits, Git operations, installs, process control, and mutation.
7. Keep PenguinCore as orchestration/facade. Put business logic in the appropriate
   runtime, service, persistence, provider, or TUI module.
8. Preserve native function-call/output adjacency and partial-stream replay safety.
9. Keep public docs, architecture.md, AGENTS.md, and task status synchronized with
   shipped runtime behavior.
10. If a phase reveals an architectural prerequisite, implement and test it rather
    than masking it with a larger timeout, higher iteration cap, larger context
    window, or disabled safety mechanism.

## Phase 0 — Operational containment and measurement

### 0A. Isolate production and test runtime state

- Add a supported test-server configuration that binds HOST=127.0.0.1 and PORT=8080
  while assigning a unique test PENGUIN_WORKSPACE and runtime-event ledger path.
- Ensure test logs, sessions, checkpoints, tool artifacts, SQLite files, and backups
  remain inside that isolated location.
- Add startup diagnostics for server role, host/port, PID, workspace, log directory,
  ledger path, checkpoint path, and conversation path.
- Detect and clearly warn or fail when two live backends would share mutable runtime
  storage unintentionally.
- Add deterministic two-server tests proving an 8080 test backend cannot contend with
  or mutate the 9000 production backend's files.

### 0B. Make checkpoint and disk growth safe

- Build a read-only checkpoint inventory and cleanup planner.
- Its dry run must report candidates, retained items, total/candidate/retained bytes,
  age buckets, session ownership, active-session protection, configured retention
  reasoning, and the exact recovery/archive plan.
- The default execution for cleanup tooling must be dry-run. A destructive mode must
  require an explicit flag and must not be invoked during this goal.
- Enforce early disk-space and growth warnings before ENOSPC.
- Prevent new background archival/checkpoint work when the safety floor is crossed
  while preserving active conversation and user-visible error reporting.
- Stop unbounded checkpoint creation until automatic retention and off-loop
  persistence are implemented in Phase 1.

### 0C. Add trustworthy performance and liveness telemetry

- Instrument provider setup/wait/stream, first event, last progress event, stream
  callback, event projection, ledger enqueue/commit/cleanup, tool queue/schedule/run,
  transcript update, session save, checkpoint work, context assembly, and end-to-end
  request duration.
- Separate actual tool execution from Penguin orchestration time.
- Emit monotonic progress timestamps that distinguish request age, provider-event age,
  tool-event age, and UI-event age.
- Add bounded connection-attempt/success/disconnect history to debug exports.
- Keep sensitive prompts, tool payloads, credentials, and full outputs out of ordinary
  telemetry.
- Establish repeatable 8080 baselines for a fresh session and a large persisted
  session using a deterministic fake provider and controlled tool outputs.

### Phase 0 acceptance

- The updated todo records the program and current evidence.
- A documented 8080 command/configuration cannot touch production mutable storage.
- Automated tests prove production/test storage isolation.
- The checkpoint cleanup dry run completes without changing source data.
- Disk and checkpoint safety floors are visible and deterministic.
- Stage timings can explain provider time, tool time, and local overhead separately.
- Baseline results and remaining uncertainty are recorded before Phase 1.

## Phase 1 — Stop, retry, and visible-state correctness

### 1A. Checkpoint worker correctness

- Make worker queues and tasks owned by exactly one running event loop.
- Make start and stop idempotent across repeated startup, shutdown, thread, and loop
  boundaries.
- Use a bounded queue with explicit overflow behavior.
- Move full-session conversion, JSON serialization, gzip, checkpoint writes, and
  index persistence off the main event loop.
- Add bounded retry/backoff, rate-limited logging, and a circuit breaker. No worker
  error may become a CPU, disk, or log storm.
- Enforce max-count, max-age, and max-size retention automatically.
- Protect active/manual/branch checkpoints according to explicit policy.

### 1B. Provider watchdog and retry contract

- Add OpenAI/Codex chunk-idle and total-attempt watchdogs.
- Represent timeout, disconnect, incomplete stream, and retry exhaustion as typed
  provider failures with accurate recoverability.
- Keep the one safe replay bounded, use backoff/jitter, and never replay after partial
  assistant output or a pending native tool call unless protocol safety is proven.
- Ensure a nominal non-stream retry is genuinely bounded and does not silently reuse
  the same unbounded SSE behavior.
- Preserve partial output and lifecycle diagnostics on failure.
- Release provider, request, session, and tool state on success, abort, cancellation,
  timeout, and retry exhaustion.

### 1C. Truthful TUI and API terminal/liveness state

- Parse the chat response body in the TUI instead of reducing every 2xx response to
  success.
- Preserve and display status, recoverable, error details, iterations, action count,
  partial response, and abort/cancellation state.
- Define distinct visible states for running, reconnecting, stalled/degraded,
  max_iterations, provider exhaustion, repeated empty/tool-only loop, aborted,
  cancelled, completed, and failed.
- Derive healthy running from real progress, not active-request count alone.
- When the no-event threshold is crossed, retain elapsed run time but show a truthful
  stalled/degraded state with Interrupt, Retry, and Resume actions.
- Add a bounded client POST deadline and bounded per-session gate acquisition.
- Replace guessed manual continuation with an explicit continuation action. Only
  auto-continue when durable state and replay semantics prove it is safe.
- Reconcile architecture.md, API schemas, and TUI contracts around one documented
  iteration/continuation policy. Do not merely raise the 100-iteration cap.

### Phase 1 tests

- Cross-loop and repeated-start checkpoint worker tests.
- Worker error storm, queue overflow, backoff, circuit-breaker, and retention tests.
- Fake-provider no-header, no-chunk, incomplete-chunk, disconnect, retry-success,
  retry-exhaustion, partial-output, pending-tool, abort, and cancellation tests.
- TUI tests for HTTP-200 non-completed bodies, visible terminal reasons, no-event
  degradation, user interrupt/retry/resume, and request deadlines.
- State-machine tests proving every path releases busy/request/session/tool state.

### Phase 1 acceptance

- No worker exception can spin without delay or bound.
- No provider stream can wait forever.
- The common no-events symptom becomes visibly stalled/degraded with bounded recovery.
- Every non-completed result is visible and actionable in the TUI.
- Safe transient errors recover automatically; exhausted recovery never masquerades
  as success.
- Focused backend and TUI suites pass.

## Phase 2 — Event, transcript, checkpoint, and session persistence

### 2A. Runtime-event ledger

- Replace awaited per-event SQLite commits with a bounded single-writer queue and
  batched transactions.
- Define durability, backpressure, overflow, shutdown-drain, and replay-gap behavior
  explicitly.
- Persist text deltas or bounded snapshots, not a growing cumulative text body on
  every chunk.
- Deduplicate unchanged busy/status projections and record progress timestamps
  separately.
- Move retention, checkpoint, vacuum, and size cleanup off live event delivery.
- Account for SQLite freelist pages and WAL size correctly.
- Use isolated ledger paths per server/worktree and prevent accidental multi-process
  sharing unless a supported single-writer architecture exists.

### 2B. SSE replay and reconnect

- Retain the last delivered SSE event ID in the TUI.
- Send Last-Event-ID or last_event_id on reconnect.
- Replay from the durable cursor, deduplicate replay/live overlap, and surface
  server.replay_gap truthfully.
- Rehydrate and reconcile canonical active session status after every connection.
- Preserve newer live events if a slower hydration response arrives later.
- Include connection history and replay decisions in debug exports.

### 2C. Transcript and session persistence

- Bound OpenCode transcript metadata.
- Store tool output once, with one canonical artifact reference for large output.
- Remove duplication between state.output and state.metadata.output.
- Define retention/migration behavior for existing oversized session files.
- Coalesce saves at durable boundaries rather than saving every terminal tool part and
  again after every engine iteration.
- Serialize saves per session, use unique temp files, and retain atomic replacement
  and backup safety.
- Prevent autosave/request-save collisions and stale writers.
- Make session/checkpoint index updates incremental or otherwise avoid full global
  rewrites for every event.
- Current-PR exception to the CWM v2 deferral: preserve native tool-call/tool-result
  units atomically anywhere the existing trim, replay, transcript, or provider
  sanitation paths can split them. Do not use this exception to redesign context
  budgeting, summarization, retrieval, or compaction in this PR.

### Phase 2 tests and benchmarks

- Production-path stream stress test including adapter, transcript, ledger, session
  save, and SSE delivery.
- Multi-process/server isolation test.
- Ledger overflow, shutdown, replay, replay-gap, cleanup, WAL/freelist, and corruption
  fault tests.
- TUI reconnect tests with missed busy/idle/tool/message events.
- Large-session save concurrency tests across autosave and request-driven saves.
- Migration tests for existing transcript/output duplication.
- Native tool-call/tool-result adjacency tests across existing trimming, replay, and
  provider sanitation boundaries.
- Benchmark cumulative database bytes and local latency for thousands of small text
  chunks and tool events.

### Phase 2 acceptance

- Live UI delivery no longer waits on per-event disk commits.
- Reconnect restores event and status continuity from a durable cursor.
- Repeated busy snapshots and cumulative text no longer dominate the ledger.
- Session files and backups remain bounded under a long tool-heavy run.
- Concurrent saves produce no temp collisions, lost updates, or stale overwrites.
- Existing trimming and replay never emit an orphaned native tool call or result.
- Local persistence overhead is measured and no longer dominates millisecond tools by
  tens of seconds.

## Phase 3 — Tool-loop, request, and cache performance

### 3A. Tool scheduling and iteration contract

- Parallelize independent read-only inspection.
- Keep filesystem mutation, Git, process control, installs, tests, and order-dependent
  tools serialized.
- Measure queue/schedule/event/persistence time separately from tool execution.
- Use ordered native batching where needed without globally classifying harmless
  inspection as mutation.
- Replace the silent 100-iteration mismatch with one documented cap and continuation
  contract.
- Detect stale/repeated tool-only loops early and show the reason.

### 3B. Request overhead and cache affinity

- Measure system prompt, message payload, tool schemas, provider framing, input,
  cached input, output, reasoning, and service-tier/variant boundaries per request.
- Add a stable session-scoped OpenAI prompt_cache_key and bound/normalize it to
  provider requirements.
- Verify unrelated sessions use distinct cache affinity.
- Preserve prefix stability across tool loops.
- Treat provider/model/reasoning variant changes as explicit cache-boundary events.
- Avoid unnecessary per-iteration provider client creation where safe connection reuse
  is supported.

### Phase 3 acceptance

- Independent reads can run concurrently without weakening mutation safety.
- Iteration caps and continuation are visible and documented.
- Cache affinity is stable per session and measurable.
- Fresh and large-session 8080 benchmarks isolate request/tool-loop/cache latency.
- CWM behavior has not been changed to hide Phase 0 through 3 regressions, except for
  the narrowly scoped native tool adjacency repair in Phase 2.

## Phase 3.5 — Prompt and immediate-context engineering

Phase 3.5 remains part of this runtime-reliability PR. It follows Phase 3 and fixes
prompt/context engineering that can be evaluated without changing how historical
conversation content is selected.

This phase owns the instructions Penguin sends and the small active-turn envelope
around them. It does not own conversation-history selection, global token budgets,
tool-output slimming, summarization, retrieval, or compaction; those remain CWM v2.

### 3.5A. Mode-aware prompt architecture

- Wire the real mode-aware prompt builder into the core request path.
- Add characterization tests proving direct, implement, review, explain, and any
  compatibility mode produce intentional, materially different prompts.
- Make the normal implementation path lean and implementation-first: inspect only
  what is needed, act promptly, verify in proportion to risk, and stop when genuinely
  complete.
- Remove the blanket 5 to 12 analysis-tool minimum.
- Remove legacy instructions that force every tool action into a separate model turn.
- Resolve contradictory completion, continuation, and stopping instructions against
  the actual engine contract.

### 3.5B. Tool and instruction surface

- Inventory the always-on system instructions and tool schemas by tokens and purpose.
- Remove duplication and stale guidance without weakening required safety, tool
  contracts, or repository/user instructions.
- Use task/mode-aware tool exposure or concise tool descriptions where runtime
  semantics allow it; preserve compatibility for tools that must remain available.
- Explicitly encourage safe parallel read-only inspection while retaining mutation
  ordering rules.
- Keep prompt changes versioned or fingerprinted so behavior and cache-boundary
  regressions can be attributed.

### 3.5C. Stable active-turn envelope

- Separate the stable, cacheable instruction prefix from dynamic run state.
- Represent active task, continuation, terminal reason, and relevant tool state in a
  compact structured envelope rather than repeating prose.
- Keep explicit user attachments and user instructions authoritative.
- Measure instructions, tool schemas, active-turn state, and provider framing
  separately so prompt reductions are visible rather than inferred.
- Do not add history truncation, sliding windows, summarization, retrieval, or CWM
  budget policy in this phase.

### Phase 3.5 tests and acceptance

- Snapshot/contract tests cover each prompt mode and the stable/dynamic boundary.
- Small behavioral fixtures distinguish implement, direct, review, and explain intent
  without depending only on string snapshots.
- Simple implementation tasks no longer inherit forced investigation depth or
  contradictory stopping rules.
- Required tools, safety instructions, user attachments, and completion semantics do
  not regress as prompt size falls.
- Prompt-prefix/cache stability and per-section token costs are measurable.
- The diff contains no deferred CWM v2 history-selection or compaction work.

## Phase 4 — CWM v2 follow-up PR readiness and handoff

Phase 4 in this goal is documentation and handoff work in the current PR; it does not
implement CWM v2. Begin the handoff only after Phases 0 through 3.5 meet their
acceptance criteria and their measurements are stable. Close and independently verify
this runtime-reliability PR before beginning CWM v2 implementation. Prefer to create
the CWM v2 branch from the merged runtime-reliability result so each change set can be
tested and reviewed in isolation.

Implement CWM v2 only in that separate follow-up branch and PR. Use
`feat/CWM-v2` or `Penguin-Context-Window-Manager-v2` for the follow-up branch.

Current CWM language must remain precise: it trims message categories by priority and
recency; it does not compact or summarize conversation content.

### 4A. Lock the PR boundary

- Keep the current PR responsible for runtime recovery, persistence, reconnect,
  request/tool-loop/cache performance, prompt engineering, full request accounting,
  and the native tool adjacency exception.
- Keep the CWM v2 PR responsible for final-packet assembly, elastic global budgets,
  deterministic historical tool-output slimming, optional durable summarization,
  retrieval, compaction lifecycle, policy presets, and persisted-session migration.
- Record any unavoidable prerequisite or API introduced by the current PR without
  prematurely implementing its CWM consumer.

### 4B. Prepare evidence and the executable follow-up brief

- Update context/tasks/CWM-v2.md when verified evidence changes its assumptions,
  terminology, dependency order, success targets, or migration plan.
- Capture repeatable fresh-session, large-session, and tool-heavy baselines on the
  isolated 8080 harness after the current-PR fixes land.
- Preserve fixtures for full request accounting, native tool adjacency, long
  transcripts, large tool outputs, explicit attachments, and replay sanitation.
- Specify CWM v2 entry criteria, its own phases, test matrix, migration/rollback plan,
  metrics, and exit criteria in a follow-up `/goal`-ready brief.
- Make the follow-up dependency explicit: CWM results must be compared against the
  stable post-reliability baseline, not the original broken runtime.

### Phase 4 handoff acceptance

- CWM v2 has an independently reviewable follow-up scope and PR boundary.
- Baselines and fixtures needed to evaluate CWM behavior are repeatable and retained.
- Required interfaces and telemetry from this PR are documented and stable.
- The current diff contains no CWM v2 implementation beyond the native tool adjacency
  safety exception.
- The follow-up brief can be started without rediscovering the reliability evidence or
  making unresolved architectural decisions.

## Program-wide exit criteria

Do not mark the goal complete until all of the following are true:

1. No backend can enter an unbounded checkpoint/worker error loop.
2. No provider attempt can wait forever for a header, chunk, completion, or retry.
3. The TUI distinguishes running from reconnecting and stalled/degraded using real
   progress timestamps.
4. The no-events symptom has a bounded, visible Interrupt/Retry/Resume recovery path.
5. Every non-completed run reason is visible and does not masquerade as HTTP-success
   completion.
6. Safe transient failures recover automatically; exhausted recovery is explicit.
7. Port 8080 verification cannot mutate, lock, read as active state, or contend with
   port 9000 production runtime storage.
8. Checkpoint, ledger, transcript, session, backup, artifact, and log growth are
   bounded by automatic policy.
9. Disk-safety behavior is deterministic and prevents another ENOSPC cascade.
10. The cleanup planner has a reviewed dry-run report; no destructive cleanup was
    performed without separate approval.
11. Live UI/event delivery does not synchronously wait on per-event SQLite commits or
    large session rewrites.
12. SSE reconnect uses a durable cursor, handles replay gaps, and reconciles canonical
    session state without stale busy/running projections.
13. Session saves are serialized and atomic, with no temp-file collision or stale
    overwrite under concurrency.
14. Tool output has one canonical representation plus artifact references; long
    sessions do not grow metadata by duplicating full output.
15. Local orchestration and persistence timing is measured separately and no longer
    turns millisecond tools into unexplained tens-of-seconds batches.
16. Existing trimming, transcript, replay, and provider sanitation paths preserve
    native tool-call/tool-result adjacency without relying on large silent drops.
17. Independent read-only tools can execute concurrently while mutation ordering
    remains safe.
18. Iteration caps, stale-loop guards, partial progress, and continuation semantics are
    documented and visible.
19. Session-scoped prompt cache affinity is implemented and verified.
20. Prompt modes are materially distinct, implementation-first behavior is available,
    and no blanket investigation/tool-count minimum remains.
21. The prompt/tool surface has a tested stable prefix and compact active-turn
    envelope without weakening safety, user instructions, attachments, or required
    tool contracts.
22. Full request overhead is measurable by section, and repeatable isolated 8080
    baselines and long-session fixtures are retained for the CWM v2 follow-up.
23. CWM v2 has a `/goal`-ready separate-PR brief with explicit entry criteria,
    phases, migration/rollback plan, metrics, and exit criteria; this branch contains
    no CWM v2 implementation beyond the native tool adjacency exception.
24. Current public docs and architecture descriptions match shipped runtime truth.
25. Focused tests, fault-injection tests, concurrency tests, TUI tests, and production
    path stress tests pass.
26. Run Ruff/format checks on touched Python, the relevant Bun/TUI suites, the core
    pytest suite, and other proportionate repository verification required by
    AGENTS.md.
27. Produce a final evidence report with before/after metrics, commands, test results,
    storage behavior, known residual risks, and any intentionally deferred work.

At each phase boundary, update context/tasks/todo.md, record measured evidence, and
make a scoped local commit only after the phase acceptance criteria pass. Phase 4 is
complete when the separate-PR handoff is executable, not when CWM v2 is implemented.

If genuinely blocked on a decision or authority expansion, preserve state, identify
the exact blocker and safest options, and ask one focused question. Do not declare the
goal complete because a time, token, iteration, or context limit was reached.
