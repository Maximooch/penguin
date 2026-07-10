# Runtime reliability and performance recovery — final evidence

Branch: `fix/runtime-reliability-recovery`

## Phase commits

- `82c97ae66` — Phase 0 operational containment and measurement
- `b364634c0` — Phase 1 stop/retry and visible terminal truth
- `86bfa473e` — Phase 2 batched persistence, durable replay, and reconnect state
- `bf65effc3` — Phase 3 safe tool scheduling, request accounting, and prompt cache affinity
- `1b84ff956` — Phase 3.5 mode-aware prompts and active-turn envelope/CWM handoff
- `bd49ea411` — Typer-compatible CLI regression assertions

## Verification

- `uv run pytest tests -q` → **2303 passed, 3 skipped, 113 deselected**.
- Storage-boundary slice → **45 passed**, covering bounded session diagnostics,
  atomic-save interactions, concurrent session isolation, and artifact quota
  admission.
- Phase 2 focused gate → **98 passed**; Phase 3 provider/tool/cache gate → **147 passed**.
- Prompt/active-turn gate → **8 passed**.
- TUI focused suites → **51 passed** at the Phase 1 gate and **28 passed** for the Phase 2 cursor/terminal slice; `bun run typecheck` passed for the latter.
- Touched Python `ruff check --select E9,F,I` and `git diff --check` passed; compileall passed for touched modules. Repository-wide Ruff still has legacy violations outside this program's surface.
- Deterministic isolated test harness recorded fresh and large-persisted cases on `127.0.0.1:8080` without starting a network server. No live provider and no port `9000` verification were used.

## Shipped behavior

- Checkpoint work is loop-owned, bounded, offloaded, retried with backoff, circuit-broken, retained by policy, and blocked before a critical disk floor.
- Provider attempts have header/chunk/total deadlines, typed terminal failures, bounded safe replay, and lifecycle release.
- REST/WebSocket/TUI terminal truth distinguishes stalled, retryable, exhausted, cancelled, aborted, max-iteration, and completed outcomes; reconnect uses durable cursors and canonical status hydration.
- Runtime events use a bounded single writer with batched SQLite transactions, stable ledger identity, conflict-preserving IDs, pending-vs-committed cursor semantics, replay-gap controls, and coalesced busy heartbeats.
- Session writes serialize atomically with unique temp files and unchanged-save coalescing; lifecycle/tool-record metadata is capped at load and append boundaries, and tool output records use bounded previews plus artifact references.
- Independent read-only native tool calls may overlap while mutation and explicit ordered batches remain serial and provider-result order is preserved.
- OpenAI requests receive bounded session-scoped prompt cache affinity and sectioned request accounting; provider/model/variant changes log cache boundaries.
- Normal prompt modes are materially distinct and implementation-first; fixed investigation/tool quotas and one-action-per-turn guidance are removed. A stable mode-specific prefix and compact active-turn envelope are fingerprinted. CWM v2 history selection/compaction remains deferred.

## Separate CWM v2 handoff

The current diff contains no CWM v2 implementation beyond the native adjacency safety
exception. The follow-up is ready at
`context/tasks/CWM-v2-followup-goal.md`, with entry criteria, phases, deterministic
tests, migration/rollback controls, metrics, and exit criteria. Begin it from the
merged reliability result so CWM measurements are compared against the retained
post-fix baseline.

## Residual risks

- Live-provider cache hit rates and production socket behavior remain opt-in smoke
  checks; deterministic fixtures are the correctness proof.
- Existing legacy session files with duplicated historical tool output are not
  destructively migrated in this PR; the CWM v2 follow-up owns reviewed migration.
- Tool-artifact admission is bounded by default (2,048 files or 512 MiB per artifact
  directory); operators should still set deployment-specific quotas and monitor the
  emitted storage diagnostics. Existing rotating server-log policy remains in place.
