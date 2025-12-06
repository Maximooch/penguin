## Penguin RunMode + Project Management Roadmap (Spec‑Driven + ITUV)

Goal: make Run Mode predictable, traceable, and resilient by wiring spec‑driven development into task creation/selection and executing each task through a formal ITUV lifecycle (Implement → Test → Use → Verify), with clear gates, events, and artifacts.

### Guiding principles
- Small, composable increments; ship value each milestone.
- Source of truth: docs → blueprint items → tasks → commits → tests → verification.
- UI/CLI should surface status in one line; details available on drill‑down.
- Strong observability: events, artifacts, telemetry, and reproducible runs.

---

### Phase 0 – Quick wins and scaffolding
- [x] Add lightweight CLI shortcuts for small tasks
  - `fix` (alias of implement), `research` (alias of review) in `penguin/cli/commands.yml`
- [ ] Document current RunMode event flow and UI consumption
  - Output: short diagram and event key list in `context/`

---

### Three‑phase adoption plan (orchestration)
- Phase 1: NetworkX (native DAG in Penguin) ✅ COMPLETED
  - Build/maintain Blueprint DAG; frontier selection with tie‑breakers; continuous mode advances via DAG.
  - Maps to this roadmap's Phase 1 (parsing/metadata) and Phase 5 (scheduler).
- Phase 2: Temporal (durable ITUV) 🚧 IN PROGRESS
  - Make RunMode loops and ITUV phases durable with retries, backoff, timers, signals/queries.
  - Introduce under a feature flag without breaking native mode.
- Phase 3: PenguinGraph (first‑class graph runtime)
  - A thin graph API with backends: NetworkX (native), Temporal (durable), future custom backends.
  - Keeps Engine/tools intact while enabling editable graphs, richer capabilities, and swap‑able backends.
  - Leverage Link

---

### Phase 2 Temporal – Detailed Implementation Plan

**Goal:** Make ITUV workflows durable across restarts with retries, timeouts, signals, and queries.

**Package Structure:**
```
penguin/orchestration/
├── __init__.py           # Public API exports
├── backend.py            # Abstract OrchestrationBackend interface
├── native.py             # NetworkX + in-memory implementation
├── state.py              # WorkflowState storage (SQLite)
├── temporal/
│   ├── __init__.py
│   ├── client.py         # Temporal client wrapper
│   ├── worker.py         # Activity worker setup
│   ├── workflows.py      # ITUVWorkflow definition
│   └── activities.py     # IMPLEMENT, TEST, USE, VERIFY activities
└── config.py             # Backend selection, connection settings
```

**Changes:**
- [ ] `penguin/orchestration/backend.py`
  - Abstract `OrchestrationBackend` with methods:
    - `start_workflow(task_id, blueprint_id) -> workflow_id`
    - `get_workflow_status(workflow_id) -> WorkflowStatus`
    - `signal_workflow(workflow_id, signal, payload)`
    - `query_workflow(workflow_id, query) -> Any`
    - `cancel_workflow(workflow_id)`
    - `list_workflows(project_id, status_filter) -> List[WorkflowInfo]`
- [ ] `penguin/orchestration/native.py`
  - Wrap existing NetworkX DAG + RunMode as `NativeBackend`
  - In-memory workflow state with persistence to SQLite
  - Signals handled via EventBus
- [ ] `penguin/orchestration/state.py`
  - `WorkflowState` model: workflow_id, task_id, phase, status, started_at, updated_at, context_snapshot_id, artifacts
  - SQLite storage for state persistence (survives restarts)
  - Conversation history stored by reference (context_snapshot_id) to avoid payload limits
- [ ] `penguin/orchestration/temporal/client.py`
  - `TemporalClient` wrapper with connection management
  - Local dev mode (auto-start Temporal server) vs external connection
  - Retry logic for transient connection failures
- [ ] `penguin/orchestration/temporal/worker.py`
  - Activity worker registration
  - Graceful shutdown handling
  - Health check endpoint
- [ ] `penguin/orchestration/temporal/workflows.py`
  - `ITUVWorkflow`:
    - Input: task_id, blueprint_id, config (timeouts, retries)
    - Phases: IMPLEMENT → TEST → USE → VERIFY (sequential activities)
    - Gate logic: each phase must pass before advancing
    - Failure handling: retry with backoff, then pause for human input
    - Signals: `pause`, `resume`, `cancel`, `inject_feedback`
    - Queries: `get_status`, `get_phase`, `get_artifacts`, `get_progress`
- [ ] `penguin/orchestration/temporal/activities.py`
  - `implement_activity(task_id, context_snapshot_id) -> ImplementResult`
  - `test_activity(task_id, test_patterns) -> TestResult`
  - `use_activity(task_id, recipe_name) -> UseResult`
  - `verify_activity(task_id, acceptance_criteria) -> VerifyResult`
  - Each activity: load context from storage, invoke Engine, save artifacts, return result
- [ ] `penguin/orchestration/config.py`
  - `orchestration.backend`: `native` | `temporal` (default: `native`)
  - `orchestration.temporal.address`: Temporal server address (default: `localhost:7233`)
  - `orchestration.temporal.namespace`: Temporal namespace (default: `penguin`)
  - `orchestration.temporal.task_queue`: Task queue name (default: `penguin-ituv`)
  - `orchestration.temporal.auto_start`: Auto-start local Temporal server (default: `true` for dev)
- [ ] `pyproject.toml`
  - Add `temporalio` to optional dependencies under `[project.optional-dependencies.orchestration]`
- [ ] `penguin/project/manager.py`
  - Add `get_orchestration_backend() -> OrchestrationBackend` factory method
  - Integrate workflow start/status into task lifecycle
- [ ] CLI
  - `workflow start <task_id>` - Start ITUV workflow for task
  - `workflow status <workflow_id>` - Get workflow status
  - `workflow pause <workflow_id>` - Pause workflow
  - `workflow resume <workflow_id>` - Resume workflow
  - `workflow cancel <workflow_id>` - Cancel workflow
  - `workflow list [project_id]` - List workflows

**Durability Model:**
- Workflow state persisted in Temporal (survives restarts)
- Conversation history persisted in SQLite, referenced by snapshot_id
- Artifacts stored in project workspace, paths recorded in workflow state
- On restart: query Temporal for active workflows, resume from last checkpoint

**Signal/Query Patterns:**
- `pause` signal: Set workflow to PAUSED state, wait for `resume`
- `resume` signal: Continue from current phase
- `cancel` signal: Graceful termination, mark task as cancelled
- `inject_feedback` signal: Provide human clarification mid-workflow
- `get_status` query: Returns current phase, status, progress
- `get_artifacts` query: Returns list of artifacts with paths

**Acceptance Criteria:**
- [ ] ITUV workflow runs to completion via Temporal
- [ ] Workflow survives worker restart and resumes from checkpoint
- [ ] Signals (pause/resume/cancel) work correctly
- [ ] Queries return accurate status and artifacts
- [ ] Native backend continues to work when Temporal is disabled
- [ ] Config toggle switches between backends without code changes

**Deployment Architecture:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Deployment Options                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Option A: Development (all-in-one)                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │            Penguin Process (CLI or Web)                        │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────────────┐  │ │
│  │  │ CLI/Routes  │──│ Native      │──│ SQLite State          │  │ │
│  │  │ (client)    │  │ Backend     │  │ (workflow_state.db)   │  │ │
│  │  └─────────────┘  └─────────────┘  └───────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Option B: Development with Temporal (local server)                  │
│  ┌────────────┐    ┌───────────────────┐                            │
│  │ Penguin    │───▶│ temporal server   │  (temporal server start-dev)│
│  │ (client+   │    │ start-dev         │                            │
│  │  worker)   │◀───│ (in-memory)       │                            │
│  └────────────┘    └───────────────────┘                            │
│                                                                      │
│  Option C: Production (separate processes)                           │
│  ┌────────────┐    ┌─────────────────┐    ┌─────────────────────┐  │
│  │ Penguin    │───▶│ Temporal Server │◀───│ Penguin Worker      │  │
│  │ Web/CLI    │    │ (external/cloud)│    │ (separate process)  │  │
│  │ (client)   │    └─────────────────┘    │ python -m penguin.  │  │
│  └────────────┘                           │ orchestration.worker│  │
│                                           └─────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Testing Phase 2:**

```bash
# 1. Test native backend (no external deps)
python scripts/test_orchestration_manual.py

# 2. Test with Temporal server (requires temporal CLI)
temporal server start-dev  # In separate terminal
python scripts/test_orchestration_manual.py --backend temporal

# 3. Test via REST API (requires web server)
penguin-web  # In separate terminal
python scripts/test_orchestration_manual.py --api http://localhost:8000

# 4. Run pytest suite
pytest tests/test_orchestration.py -v
```

**REST API Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/workflows` | List workflows |
| POST | `/api/v1/workflows` | Start workflow |
| GET | `/api/v1/workflows/{id}` | Get workflow status |
| POST | `/api/v1/workflows/{id}/signal` | Send signal |
| POST | `/api/v1/workflows/{id}/pause` | Pause workflow |
| POST | `/api/v1/workflows/{id}/resume` | Resume workflow |
| POST | `/api/v1/workflows/{id}/cancel` | Cancel workflow |
| GET | `/api/v1/orchestration/config` | Get config |
| GET | `/api/v1/orchestration/health` | Health check |

---

### Phase 1 – Blueprint‑driven task sync (docs → structured "blueprint items" → tasks) ✅ COMPLETED
Outcomes: parse markdown/docs into structured blueprint items; maintain a doc→task→commit→test graph; auto‑create/update tasks and flag drift.

**Completed Changes:**
- [x] `penguin/project/blueprint_parser.py` (NEW)
  - BlueprintParser class with support for markdown, YAML, and JSON formats
  - Extracts BlueprintItem blocks: id, title, description, acceptance criteria, usage recipes, dependencies
  - Parses YAML frontmatter for project metadata and ITUV settings
  - Supports inline task metadata: `{priority=high, effort=2, agent_role=implementer, ...}`
  - Parses Usage Recipes section for USE gate automation
- [x] `penguin/project/models.py`
  - Added `TaskPhase` enum: PENDING → IMPLEMENT → TEST → USE → VERIFY → DONE | BLOCKED
  - Added `BlueprintItem` model with full metadata support
  - Added `Blueprint` model for parsed Blueprint documents
  - Extended `Task` with: `blueprint_id`, `phase`, `effort`, `value`, `risk`, `sequence`, `agent_role`, `required_tools`, `skills`, `parallelizable`, `batch`, `recipe`, `assignees`
  - Added `advance_phase()` and `set_phase()` methods for ITUV lifecycle
- [x] `penguin/project/manager.py`
  - Added NetworkX-based DAG: `build_dag()`, `get_ready_tasks()`, `get_next_task_dag()`
  - Added `sync_blueprint()` for creating/updating tasks from Blueprint
  - Added `_sort_by_tie_breakers()` with configurable tie-breaker order
  - Added `get_dag_stats()` and `export_dag_dot()` for visualization
  - Added `set_tie_breakers()` and `invalidate_dag()` for DAG management
- [x] `penguin/run_mode.py`
  - Updated `start_continuous()` to accept `project_id` and `use_dag` parameters
  - Updated `_get_next_task_data()` to use DAG-based selection when project is active
  - Added `_task_to_data()` helper with ITUV/Blueprint context fields
- [x] `penguin/cli/commands.yml`
  - Added: `/blueprint sync`, `/blueprint status`
  - Added: `/task deps`, `/task graph`, `/task ready`, `/task frontier`
- [x] `penguin/cli/interface.py`
  - Added `_handle_blueprint_command()` for sync and status
  - Added DAG operations to `_handle_task_command()`: deps, graph, ready, frontier
- [x] `context/blueprint.template.md`
  - Complete Blueprint template with ITUV settings, agent routing, usage recipes, and reference sections
- [ ] CLI
  - `project blueprint sync [--project PROJECT_ID] [--path PATH_GLOB]`
  - `project blueprint status [PROJECT_ID]`
  - `task depends add <task_id> <dep_task_id>` / `task depends remove <task_id> <dep_task_id>` / `task depends list <task_id>`
  - `project graph show [--format dot|json]` (export DAG for visualization)
- [ ] Tests
  - Unit: parser coverage for headings/AC/recipes; manager reconciliation.
  - E2E: sync on a sample doc creates tasks with AC and usage recipe attached.

Acceptance
- Can parse a doc with ≥3 blueprint items, create/update tasks with AC and usage recipes.
- Drift status shows which tasks are stale and which AC lack test coverage.

---

### Phase 2 – Prompt enrichment in Run Mode (contextual, blueprint‑aware execution)
Outcomes: RunMode automatically injects Blueprint section + AC into the execution prompt and telemetry, improving determinism and verifiability.

Changes
- [ ] `penguin/run_mode.py`
  - When executing a task with `blueprint_id`, append a “Blueprint” and “Acceptance Criteria” section to the task prompt (hide internal markers from UI).
  - Include `context.metadata.blueprint_id` and `context.metadata.phase` in events.
- [ ] `penguin/core.py`
  - Thread `blueprint_id` into RunMode context when called from project manager or CLI.
- [ ] `penguin/engine.py`
  - Ensure `message_callback` preserves order: assistant → tool output → status.

Acceptance
- RunMode prompt contains blueprint+AC when task has `blueprint_id`.
- Events include `blueprint_id` and are consumable by CLI/TUI without duplication.

---

### Phase 3 – ITUV lifecycle model and gates (Implement → Test → Use → Verify)
Outcomes: every task can run through ITUV phases with clear success criteria, artifacts, and status transitions.

Changes
- [ ] `penguin/project/models.py`
  - Add `TaskPhase = IMPLEMENT|TEST|USE|VERIFY`, `phase_status`, `phase_timestamps`, `artifacts: dict`.
- [ ] `penguin/engine.py`
  - Add optional `phase: str` to `run_task(...)` and include `phase` in STARTED/PROGRESSED/COMPLETED/FAILED events.
- [ ] `penguin/run_mode.py`
  - New orchestration method: given a task (or Blueprint), run sequential phases:
    - Implement: produce code per AC.
    - Test: run targeted tests for AC/blueprint markers and gather results.
    - Use: execute usage recipe (CLI/API flow) to demonstrate behavior.
    - Verify: check AC satisfied, tests pass, usage recipe success; attach summary.
  - Phase timeboxes and retry rules; stop on failure, emit `clarification_needed`.
- [ ] CLI
  - `task ituv start <task_id>`
  - `task ituv next [<task_id>]` (advance with summary)
  - `task ituv verify <task_id>` (re‑run VERIFY gate standalone)
- [ ] `penguin/project/validation_manager.py`
  - Implement VERIFY gate: AC coverage, test status, usage recipe success, lint/type checks (configurable).

Acceptance
- A task with `blueprint_id` completes IMPLEMENT+TEST+USE+VERIFY, producing artifacts and marking the task completed when gates pass.

---

### Phase 4 – Targeted Test Runner and Usage Recipe Runner
Outcomes: deterministic validation tied to blueprint/AC.

Changes
- [ ] `penguin/project/validation_manager.py`
  - Pytest integration: run `pytest -q -k "blueprint_id or AC markers"`; parse results.
  - Accept recipe types: `shell`, `http`, `python` with a safe runner and timeout.
  - Collect artifacts: stdout/stderr, HTTP transcripts, exit codes, screenshots/logs (if web).
- [ ] `penguin/tools` (optional)
  - Minimal `exec_usage_recipe` tool callable from Engine when needed.

Acceptance
- For a sample Blueprint, AC tests are invoked and usage recipe is executed; artifacts persist on the task record.

---

### Phase 5 – Scheduler & resilience upgrades for Continuous mode
Outcomes: better task selection and safe long‑running autonomy.

Changes
- [ ] `penguin/project/manager.py`
  - DAG‑aware scheduling:
    - `get_ready_tasks_async(project_id)` returns the frontier (in‑degree 0) filtered by status and phase gates.
    - Topological selection with configurable tie‑breakers: priority DESC, due_date ASC, sequence, created_at.
    - Cycle detection on sync; annotate tasks involved and block scheduling with actionable error.
    - Failure policy: on task failure, automatically hold downstream dependents until override or re‑VERIFY.
- [ ] `penguin/run_mode.py`
  - Watchdog: detect repeated identical LLM output and request clarification.
  - Model fallback on empty responses: one retry with non‑streaming or alternate model via `core.load_model`.
  - Timeboxes per phase; heartbeat/health events with CPU/mem thresholds.
  - DAG continuation: after completing a task, pick next from `get_ready_tasks_async` instead of “most relevant”; if multiple, apply tie‑breakers deterministically.
  - Multi/sub‑agent dispatch:
    - Use `agent_role` from task to request coordinator selection; pass `agent_role`/`agent_id` to `engine.run_task` (already supported in RunMode).
    - Maintain per‑agent queues from the DAG frontier respecting `ready_parallelism` and agent capacity.
    - Capability filter: only assign tasks whose `skills/required_tools` are satisfied by agent capabilities mapping.
    - Fairness: round‑robin across agents when multiple can take a task with equal tie‑breakers.
- [ ] `penguin/engine.py`
  - Ensure `message_callback` preserves order: assistant → tool output → status.
- [ ] CLI
  - `task ituv start <task_id>`
  - `task ituv next [<task_id>]` (advance with summary)
  - `task ituv verify <task_id>` (re‑run VERIFY gate standalone)
  - `run continuous [PROJECT]` shows “DAG frontier” preview: upcoming ready tasks in order of selection.
  - `run continuous --parallel N` sets scheduler `ready_parallelism`

Acceptance
- Continuous mode advances through the DAG in topological order, only selecting tasks whose dependencies are satisfied; shows concise phase/progress and the current frontier in UI.

---

### Phase 6 – Git/CI integration and blueprint drift workflow
Outcomes: link code to tasks/blueprints; close the loop via CI.

Changes
- [ ] `penguin/project/git_integration.py`, `git_manager.py`
  - Commit metadata: include `task_id` and `blueprint_id` in messages; open PR with checklist derived from AC.
- [ ] CI (docs)
  - Provide a GH Actions example: run blueprint sync, targeted pytest, usage recipes; fail CI on unmet AC/drift.
- [ ] Drift detection
  - On doc change, mark affected tasks as “stale” and recommend ITUV rerun.

Acceptance
- A PR referencing a task/blueprint runs VERIFY checks in CI; status surfaces in the PR.

---

### Phase 7 – Observability and UX polish
Outcomes: first‑class timeline and status.

Changes
- [ ] Event payloads include: `agent_id`, `blueprint_id`, `phase`, `iteration`, `progress`, `artifacts`.
- [ ] CLI/TUI
  - Timeline: assistant/tool/status grouped by phase, with collapsible details.
  - `runmode status` shows: current phase, iteration, progress, timebox left.
- [ ] Telemetry snapshot
  - Per‑task: iterations, time, tokens, tools invoked, tests/usage results.

Acceptance
- A single command prints a compact ITUV summary with links to artifacts.

---

### Configuration & flags
- [ ] `config.yml`
  - `runmode.ituv.enabled` (default: true)
  - `runmode.ituv.phase_timebox_sec` per phase
  - `verification.strict` (lint/type/test gates)
  - `blueprints.sources` (glob list for docs)
  - `blueprints.formats` (accepted: markdown|yaml|json)
  - `blueprints.default_dir` (default: `context/specs/`)
  - `blueprints.auto_create_tasks` (default: true)
  - `blueprints.test_mapping.strategy` (default: `file_patterns`)
  - `blueprints.test_mapping.patterns` (list of glob patterns with `{id}` placeholder)
  - `usage_runner.enabled|sandbox|network|timeout_sec` (defaults via config)
  - `scheduler.strategy` (default: `dag`)
  - `scheduler.tie_breakers` (default: `["priority_desc", "due_date_asc", "sequence", "created_at_asc"]`)
  - `scheduler.ready_parallelism` (default: 1)
  - `scheduler.on_failure` (default: `pause_dependents`)
  - `scheduler.max_frontier` (default: 20)
  - `orchestration.backend` (default: `native`; options: `native|temporal|penguin_graph`)

Example (initial defaults):

```yaml
blueprints:
  sources:
    - "context/specs/**/*.md"
    - "context/specs/**/*.{yaml,yml}"
    - "context/specs/**/*.json"
  formats: ["markdown", "yaml", "json"]
  default_dir: "context/specs/"
  auto_create_tasks: true
  test_mapping:
    strategy: "file_patterns"
    patterns:
      - "tests/**/test_*blueprint_{id}*.py"
      - "tests/**/test_{id}*.py"
usage_runner:
  enabled: true
  sandbox: true
  network: false
  timeout_sec: 60
runmode:
  ituv:
    enabled: true
    phase_timebox_sec:
      implement: 600
      test: 300
      use: 180
      verify: 120
scheduler:
  strategy: dag
  tie_breakers: ["priority_desc", "due_date_asc", "sequence", "created_at_asc"]
  ready_parallelism: 1
  on_failure: pause_dependents
  max_frontier: 20
orchestration:
  backend: native
verification:
  strict: true
```

---

### Risks and mitigations
- Blank/empty LLM responses: already handled with non‑streaming fallback and exception; add model fallback once before aborting.
- Large docs / token pressure: inject only relevant Blueprint section and AC; link out to rest.
- Flaky tests/recipes: retries with backoff; allow VERIFY override with justification stored on task.
- Security for usage recipes: allowlist commands; sandbox; timeouts; masked env.

---

### KPIs / success criteria
- 90%+ tasks with `spec_id` auto‑complete ITUV without human intervention.
- 90%+ tasks with `blueprint_id` auto‑complete ITUV without human intervention.
- 0 duplicate assistant blocks; correct ordering of assistant → tool → status in UI.
- CI pass rate ≥95% for tasks with AC‑backed tests.
- Blueprint drift detection under 1s per changed file; actionable statuses in CLI.

---

### Rollout plan
1) Phase 1 (Blueprint sync) – foundational, safe to ship behind CLI.  
2) Phase 2 (Prompt enrichment) – low risk, improves quality immediately.  
3) Phase 3 (ITUV lifecycle) – adds real gates; default OFF for non‑project chats.  
4) Phase 4 (Runners) – unlock VERIFY confidence; document sandboxing.  
5) Phase 5–7 (Scheduler, Git/CI, UX) – operational excellence and polish.

---

### Tracking checklist (high‑level)
- [ ] P1: Blueprint parser + models + reconcile + CLI  
- [ ] P2: RunMode prompt enrichment + blueprint metadata in events  
- [ ] P3: ITUV data model + Engine phase + RunMode orchestration + CLI  
- [ ] P4: Test and Usage runners + artifacts  
- [ ] P5: Scheduler/timeboxes/watchdog + model fallback  
- [ ] P6: Git/CI + drift + PR checklist  
- [ ] P7: Timeline UI + telemetry snapshot + concise status

---

### Notes for implementers
- Use existing files as anchors:
  - `penguin/project/spec_parser.py`, `validation_manager.py`, `manager.py`, `models.py`
  - `penguin/run_mode.py`, `penguin/engine.py`, `penguin/core.py`
  - `penguin/project/task_executor.py`, `project/workflow_orchestrator.py`
  - `penguin/project/git_integration.py`, `git_manager.py`
- Keep edits narrowly scoped; prefer additive changes and feature flags.  
- Add tests alongside each milestone; aim for deterministic runners with timeouts.


