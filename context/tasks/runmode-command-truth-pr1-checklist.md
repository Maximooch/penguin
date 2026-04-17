# RunMode Command Truth PR 1 Checklist

## Purpose

This checklist defines the exact implementation scope for the first follow-up PR from
`context/tasks/runmode-command-loop-audit.md`.

This PR is intentionally about **contract truth and user-facing semantics**, not broad
loop refactoring.

## Goal

Make the public RunMode command surface honest and test-backed without changing the
fundamental ownership split between:
- `RunMode` outer orchestration
- `Engine` inner reasoning/action loops

This PR is CLI-first, but it is **not** CLI-only. Because Penguin is primarily
used through the web server surfaces (TUI, headless, desktop, and related clients),
later phases of this checklist may extend the same contract-truth cleanup to the
web/API surface when that can be done without turning the PR into a redesign.

## Design Decisions

- `--247` stays public.
- `--247` and `--continuous` remain aliases for now.
- project-scoped continuous mode should be documented and surfaced as honest idle/workfrontier automation
- non-project continuous mode should remain available and be described honestly as exploratory/autonomous continuation
- CLI is the first surface to clean up, but the web/API surface should follow in a later phase of the same plan where it reuses the same RunMode truth
- broad SSE/event schema redesign is still out of scope for this PR unless a tiny compatibility fix is required
- clarification waiting/resume stays owned by `RunMode`
- deeper `Engine.run_task(...)` thinning is deferred unless a very small, clearly safe cleanup falls out naturally
- time-limit behavior needs explicit wording review, especially when limits may come from blueprint/task metadata rather than only CLI flags

## In Scope

- clarify `--run`, `--247`, `--continuous`, and `--time-limit`
- improve CLI help text and output wording
- clarify project-scoped vs non-project continuous behavior
- clarify idle vs time-limit vs clarification vs completed outcomes
- strengthen tests for those contracts
- update docs to match the actual command/runtime truth
- add a later-phase web/API truth pass if the same outcome distinctions are not surfaced honestly there yet

## Out of Scope

- introducing a dedicated `penguin run ...` command namespace
- rewriting `cli.py`
- removing exploratory fallback behavior entirely
- moving orchestration ownership from `RunMode` into `Engine`
- broad `Engine` loop refactor
- broad web route or SSE schema redesign

## Files Likely To Change

### Primary runtime / CLI files
- `penguin/cli/cli.py`
- `penguin/run_mode.py`
- `penguin/core.py` (only if output/hand-off truth requires tiny adjustments)

### Possible later-phase web/API files
- `penguin/web/routes.py`
- `penguin/web/services/*` (only if needed to surface the same RunMode truth more honestly)

### Docs
- `docs/docs/usage/automode.md`
- `docs/docs/usage/cli_commands.md`
- `docs/docs/usage/web_interface.md`
- possibly `README.md` if runmode wording there is stale

### Tests
- `tests/test_runmode_continuous_drift.py`
- `tests/test_runmode_task_resolution.py`
- `tests/test_runmode_clarification_handling.py`
- add/update CLI-oriented runmode help/output tests
- add/update targeted web/API truth tests only if the later web phase is needed

## Implementation Checklist

### Phase 1: Contract Definition In Code And Docs
- [x] Audit current `--run`, `--247`, `--continuous`, and `--time-limit` help text in `penguin/cli/cli.py`
- [x] Audit current RunMode user-facing completion/idle output paths in CLI flow
- [x] Identify where generic completion wording is emitted even when the outcome is really:
  - clarification wait
  - idle/no-ready-task
  - time-limit stop
  - exploratory continuation
- [x] Define the exact wording contract for each outcome before patching text

#### Phase 1 Findings
- Top-level CLI help is currently too generic:
  - `--run` says “Run a specific task or project in autonomous mode.”
  - `--247` / `--continuous` says “Run in continuous mode until manually stopped.”
  - `--time-limit` says “Time limit in minutes for task/continuous execution.”
- `_handle_run_mode(...)` still prints one generic final line:
  - `Run mode execution completed.`
  even though `RunMode` already distinguishes clarification wait and time-limit states.
- `RunMode` already exposes meaningful internal truth:
  - clarification path returns `status="waiting_input"` with `completion_type="clarification_needed"`
  - continuous mode emits `status_type="time_limit_reached"`
  - project-scoped no-task continuous mode exits honestly
  - non-project no-task continuous mode synthesizes `determine_next_step`
- `Engine` is not the Phase 1 bottleneck. The immediate lie is surface wording, not loop mechanics.

#### Phase 1 Wording Contract
- `--run`
  - describe as starting autonomous execution for a specific task/project target
- `--247` / `--continuous`
  - describe as continuous execution mode
  - note that project-scoped mode works ready tasks and may stop honestly when no work is ready
  - note that non-project mode may continue exploratorily by determining next steps
- `--time-limit`
  - describe as a cap on run duration when explicitly provided here
  - do not imply blueprint/task-defined time-limit support unless that path is confirmed/surfaced
- Final CLI outcome messaging must distinguish at least:
  - completed successfully
  - waiting for clarification / user input
  - stopped because no ready work remained in project-scoped continuous mode
  - stopped because the explicit time limit was reached
- `current_runmode_status_summary` and CLI-facing wording should avoid conflating:
  - `pending_review`
  - `waiting_input`
  - generic completion


### Phase 2: CLI Semantics Cleanup
- [ ] Update help text for `--247`
- [ ] Update help text for `--continuous`
- [ ] Update help text for `--run`
- [ ] Update help text for `--time-limit`
- [ ] Clarify that `--247` is the public product-language flag for long-running continuous work, not a hidden/internal alias
- [ ] Clarify in help/output that project-scoped continuous mode works the ready frontier and may stop honestly when no tasks are ready
- [ ] Clarify in help/output that non-project continuous mode may synthesize next steps and continue exploratorily
- [ ] Ensure outcome messaging distinguishes:
  - completed
  - waiting for clarification / `waiting_input`
  - idle / no ready task
  - stopped by time limit

### Phase 3: Time-Limit Truth Cleanup
- [x] Audit where CLI `--time-limit` is actually enforced today
- [x] Audit whether blueprint/task-defined time limits already surface into runtime behavior
- [x] Conclude whether blueprint/task-defined limits should be distinguished from explicit CLI time limits in this PR
- [x] Record the honest wording/documentation constraint for this surface

#### Phase 3 Findings
- CLI `--time-limit` is passed through `penguin/cli/cli.py` -> `PenguinCore.start_run_mode(...)` -> `RunMode(..., time_limit=...)`.
- Actual enforcement of `time_limit` happens in `RunMode.start_continuous(...)`:
  - the continuous loop checks elapsed wall-clock time against `self.time_limit`
  - emits `status_type="time_limit_reached"`
  - initiates graceful shutdown
- Single-task `RunMode.start(...)` currently receives/displayes `time_limit` through the CLI path, but there is no equivalent per-task wall-clock enforcement in the single-task loop.
- Web/API and `api_client.py` also pass a `time_limit` through to `start_run_mode`, so this truth is shared across surfaces.
- Blueprint/task/project timing-related fields do exist, but they are separate concepts today:
  - `budget_minutes` on `Project` / `Task`
  - `phase_timebox_sec` on Blueprint / ITUV workflow config
  - orchestration backend `phase_timeouts`
- Those timing fields are **not** the same as the runmode CLI `--time-limit` contract, and they are not currently surfaced as equivalent limits in the runmode CLI.

#### Phase 3 Direction
- For this PR, keep the runmode CLI help/output honest:
  - `--time-limit` is an explicit CLI-supplied cap on run duration
  - do **not** imply that blueprint/task/project-defined timing fields are surfaced into the runmode CLI contract yet
- If later work wants unified time-limit semantics, that should be a separate follow-up that explicitly reconciles:
  - RunMode wall-clock limits
  - task/project budgets
  - ITUV/orchestration phase timeouts

### Phase 4: Tests
- [ ] Add/refresh tests for CLI help text covering:
  - `--run`
  - `--247`
  - `--continuous`
  - `--time-limit`
- [ ] Add/refresh tests for project-scoped continuous no-task behavior
- [ ] Add/refresh tests for non-project exploratory fallback behavior
- [ ] Add/refresh tests for clarification-wait outcome wording vs completed wording
- [ ] Add/refresh tests for time-limit stop behavior wording
- [ ] Keep tests focused on contract truth, not internal implementation details

### Phase 5: Docs Alignment (CLI + shared runtime truth)
- [x] Update `docs/docs/usage/automode.md` to reflect current continuous-mode truth
- [x] Update `docs/docs/usage/cli_commands.md` for runmode flag truth
- [x] Ensure docs explain the two continuous-mode contracts clearly
- [x] Ensure docs do not imply that all continuous behavior is project/DAG-driven when it is not
- [x] Ensure docs mention clarification wait/resume outcomes where relevant

### Phase 6: Web/API Surface Truth Pass (later in this PR if still manageable)
- [ ] Audit whether web/API task execution surfaces distinguish:
  - completed
  - waiting for clarification / `waiting_input`
  - idle / no ready task
  - stopped by time limit
- [ ] If web/API wording or payload summaries are weaker than RunMode truth, patch them surgically
- [ ] Update `docs/docs/usage/web_interface.md` if web/API runmode/task-execution wording changes
- [ ] Add or refresh targeted web/API tests only where needed to preserve the same outcome truth
- [ ] Do not redesign SSE/event schemas here unless a tiny compatibility fix is required

### Phase 7: Optional Micro-Cleanup Only If Safe
- [ ] Evaluate whether there is one tiny, test-backed simplification in `Engine.run_task(...)` that can be included safely
- [ ] Only include it if:
  - it is mechanically obvious
  - it does not broaden scope
  - tests prove no behavior drift
- [ ] Otherwise defer all loop cleanup to the next PR

## Acceptance Criteria

This PR is good enough when:
- help text for `--run`, `--247`, `--continuous`, and `--time-limit` matches actual behavior
- project-scoped and non-project continuous modes are distinguished honestly
- clarification wait, idle exit, time-limit exit, and completed states are not conflated in CLI messaging
- tests cover the contract changes
- docs match the actual command/runtime truth
- if web/API wording or payload summaries were in scope for this pass, they also distinguish the same outcome states honestly

## Suggested Test Command Buckets

### RunMode-focused
```bash
pytest -q tests/test_runmode_continuous_drift.py tests/test_runmode_task_resolution.py tests/test_runmode_clarification_handling.py
```

### CLI-focused
```bash
pytest -q tests/test_cli_surface_audit_regressions.py tests/test_cli_integration.py tests/test_cli_entrypoint_dispatcher.py
```

### Optional web/API validation
```bash
pytest -q tests/api/test_sse_and_status_scoping.py tests/api/test_web_routes_task_shapes.py tests/api/test_penguin_api_surface.py
```

### Optional broader confidence pass
```bash
pytest -q tests/api/test_sse_and_status_scoping.py tests/api/test_web_routes_task_shapes.py tests/api/test_penguin_api_surface.py
```

## Risks

- `cli.py` is high-churn and overgrown; keep edits surgical
- wording changes can drift from actual runtime behavior if not backed by tests
- web/API wording can drift separately from CLI if the shared RunMode outcome contract is not made explicit first
- trying to sneak loop refactoring into this PR will expand scope and slow review

## Bottom Line

This PR should make RunMode command behavior **honest and legible**.

It should start with CLI truth, then extend that truth to web/API surfaces only where doing so remains surgical and test-backed.

It should not try to solve every architectural problem at once.
