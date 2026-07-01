# Dynamic Workflows Implementation Plan

## Status

- Created: 2026-05-28
- Scope: Penguin-native dynamic workflows inspired by Claude Code dynamic workflows
- Owner: TBD
- Target surface: Core runtime, orchestration, Project/Task storage, subagents,
  web API, TUI event stream, MCP runtime tools

## Objective

Implement first-class dynamic workflows in Penguin: a durable coordinator that
can plan, fan out, verify, refute, synthesize, pause, cancel, and resume
multi-agent software work outside the main conversation context.

This should not be just "let the model spawn more subagents." Penguin already
has subagent tools and an `AgentExecutor`. The missing product/runtime layer is
a workflow coordinator with durable state, structured handoffs, explicit
verification, progress visibility, and operator approval.

## External Reference

Anthropic's May 28, 2026 announcement describes dynamic workflows as:

- model-generated orchestration scripts/workflows
- tens to hundreds of parallel subagents in one session
- independent verification before results reach the user
- long-running work over hours or days
- saved progress and resume after interruption
- first-run confirmation because usage can be high
- an `ultracode`/high-effort mode where the agent decides when to use workflows

Penguin should copy the architecture pattern, not the exact Claude product
surface.

## Current Penguin Substrate

Penguin already has most of the lower-level pieces:

- `penguin/orchestration/`
  - `backend.py`: workflow interface, phases, status, signals.
  - `native.py`: in-process workflow backend with SQLite state.
  - `state.py`: durable workflow state and context snapshots.
  - `temporal/`: early durable-backend option.
- `penguin/project/`
  - `models.py`: task status, ITUV phases, typed dependencies, artifact evidence.
  - `runtime_jobs.py`: compact durable job record shape.
  - `workflow_orchestrator.py`: task-level ITUV coordinator.
  - `task_executor.py`: RunMode-backed task execution adapter.
- `penguin/multi/executor.py`
  - parallel background agent execution with concurrency control.
- `penguin/tools/tool_manager.py`
  - `spawn_sub_agent`, `delegate`, `wait_for_agents`, `get_agent_status`,
    `sync_context`, `delegate_explore_task`.
- `penguin/core.py`
  - isolated/shared subagent sessions.
  - `run_agent_prompt_in_session(...)`.
  - subagent session creation events for the TUI.
- `penguin/web/routes.py`
  - `/api/v1/workflows` start/list/status/signal endpoints.
- `penguin/web/sse_events.py`
  - OpenCode-compatible SSE stream.
- `penguin/system/context_window.py`
  - category-aware context trimming and isolated context-window support.

## Current Gaps

The current orchestration layer is mostly task/ITUV-shaped:

- `NativeBackend._run_workflow(...)` runs fixed sequential phases.
- `NativeBackend._execute_test(...)` and `_execute_use(...)` are placeholders.
- Workflow state persists high-level status, but not a rich dynamic plan DAG.
- Subagent execution state is mostly in `AgentExecutor` memory.
- Child outputs are free-form strings rather than structured handoff artifacts.
- There is no first-class verifier/refuter/convergence loop.
- Restart recovery can reload workflow state, but cannot reliably reconnect
  in-flight subagent work.
- The TUI can observe session/subagent events, but not a workflow DAG/timeline.
- Usage/risk approval is not a formal gate for high-fan-out runs.

## Proposed Product Shape

Add two ways to start a dynamic workflow:

1. Explicit request:
   - User says "create a workflow", "run this as a dynamic workflow", or uses
     an API/TUI command.
2. Auto mode:
   - A config/effort mode, tentatively `dynamic_workflows.auto` or `ultracode`,
     lets Penguin decide when a task is large/risky enough to warrant a
     workflow.

Before execution, Penguin should show a compact approval preview:

- objective
- planned phases
- number of worker/reviewer/refuter agents
- max concurrency
- token/time budget
- tools that may mutate state
- expected artifacts
- rollback/checkpoint behavior

After approval, the workflow runs outside the main conversation and streams
status back to the current session/TUI.

## Runtime Architecture

```text
User Prompt / API Request
        |
        v
DynamicWorkflowPlanner
        |
        v
WorkflowPlan schema + validation + approval preview
        |
        v
DynamicWorkflowCoordinator
        |
        +--> WorkflowStateStorage / ProjectStorage / RuntimeJobRecord
        |
        +--> WorkflowScheduler
        |       |
        |       +--> AgentExecutor
        |       |       +--> isolated worker sessions
        |       |       +--> reviewer sessions
        |       |       +--> refuter sessions
        |       |
        |       +--> RunMode / Engine for individual agent prompts
        |
        +--> ArtifactEvidence / structured handoffs
        |
        +--> EventBus / SSE / TUI workflow timeline
        |
        v
Synthesis agent produces final answer, task state, artifacts, or PR-ready result
```

## Data Model Additions

Add these as Pydantic/dataclass models, likely in `penguin/orchestration/models.py`
or an expanded `penguin/orchestration/state.py`.

### WorkflowPlan

Fields:

- `workflow_id`
- `objective`
- `source_session_id`
- `project_id`
- `task_id`
- `created_by`
- `created_at`
- `mode`: `explicit | auto`
- `risk_level`: `low | medium | high`
- `budget`: token, wall-clock, agent-count, max-concurrency
- `approval`: required/approved/approved_by/approved_at
- `steps`: list of `WorkflowStepSpec`
- `edges`: typed dependencies between steps
- `expected_artifacts`
- `verification_policy`
- `synthesis_policy`

### WorkflowStepSpec

Fields:

- `step_id`
- `kind`: `plan | explore | implement | test | use | verify | review | refute | synthesize`
- `title`
- `prompt`
- `agent_role`
- `persona`
- `model_config_id`
- `allowed_tools`
- `input_artifacts`
- `output_artifacts`
- `depends_on`
- `parallel_group`
- `max_attempts`
- `timeout_seconds`
- `mutation_policy`: `read_only | workspace_write | external_side_effect`

### WorkflowStepRun

Fields:

- `run_id`
- `workflow_id`
- `step_id`
- `agent_id`
- `session_id`
- `status`: `pending | ready | running | waiting_input | completed | failed | cancelled`
- `attempt`
- `started_at`
- `updated_at`
- `finished_at`
- `result_summary`
- `result_json`
- `error`
- `token_usage`
- `tool_usage`
- `artifacts`
- `review_of`
- `refutes`

### WorkflowArtifact

Fields:

- `artifact_id`
- `workflow_id`
- `step_id`
- `kind`
- `key`
- `path`
- `content_ref`
- `summary`
- `valid`
- `producer_agent_id`
- `created_at`
- `metadata`

## Storage Plan

Prefer extending existing workflow/project storage rather than adding another
database.

Minimum viable path:

- Extend `WorkflowState` with JSON columns:
  - `plan`
  - `step_runs`
  - `artifact_index`
  - `usage`
  - `approval`
- Mirror top-level workflow execution as `RuntimeJobRecord(kind="dynamic_workflow")`.
- Mirror each step execution as either:
  - `RuntimeJobRecord(kind="dynamic_workflow_step")`, or
  - rows in a new `workflow_step_runs` table.

Recommendation: use separate normalized tables once the MVP works. JSON columns
are acceptable for the first slice, but queryability will matter for the TUI,
MCP, and resume.

## Planner And Plan Validation

Add a planner service:

- `penguin/orchestration/dynamic/planner.py`
- input: objective, current project/task/session context, config, capability catalog
- output: `WorkflowPlan`

Planner constraints:

- The model proposes a plan in strict JSON.
- Penguin validates schema before approval.
- Penguin rejects unknown tools, invalid dependency edges, cycles, invalid
  mutation policies, missing verification for mutating work, and budgets above
  configured limits.
- Penguin may rewrite IDs and normalize agent names before persistence.

Important: the planner should not directly execute tools. Planning and execution
must be separate phases so approval, audit, and tests are deterministic.

## Scheduler

Add a scheduler:

- `penguin/orchestration/dynamic/scheduler.py`

Responsibilities:

- Compute the ready frontier from step dependencies.
- Enforce max concurrency and budgets.
- Spawn isolated agent sessions for worker steps.
- Persist `WorkflowStepRun` before starting execution.
- Update status on every transition.
- Capture outputs as structured artifacts.
- Retry failed steps according to policy.
- Pause/cancel cooperatively.
- Refuse to start mutation steps until approval exists.
- Resume pending/ready/failed-safe steps after restart.

For execution, reuse:

- `core.create_sub_agent(...)`
- `core.publish_sub_agent_session_created(...)`
- `core.run_agent_prompt_in_session(...)`
- `AgentExecutor`

Avoid calling `ToolManager` subagent tools from the scheduler. The scheduler
should use core/runtime APIs directly so the workflow state remains authoritative.

## Verification And Convergence

Dynamic workflows need explicit checking before synthesis.

Recommended MVP policies:

- Read-only discovery workflows:
  - at least one reviewer/refuter step for every high-confidence finding batch.
- Mutating implementation workflows:
  - implementation steps must produce changed files and evidence.
  - reviewer step checks diff against acceptance criteria.
  - test/use/verify gates must pass before final synthesis.
- High-risk workflows:
  - require two independent reviewers or one reviewer plus one adversarial refuter.

Convergence rule examples:

- `all_required_steps_completed`
- `all_artifacts_valid`
- `no_unresolved_refutations`
- `tests_passed`
- `review_quorum_met`

Store these decisions in workflow state so the final answer is auditable.

## Event Surface

Emit events through the existing EventBus/SSE path:

- `workflow.created`
- `workflow.approval.required`
- `workflow.approval.granted`
- `workflow.started`
- `workflow.step.ready`
- `workflow.step.started`
- `workflow.step.progress`
- `workflow.step.completed`
- `workflow.step.failed`
- `workflow.step.cancelled`
- `workflow.artifact.created`
- `workflow.review.completed`
- `workflow.refutation.created`
- `workflow.synthesis.started`
- `workflow.completed`
- `workflow.failed`
- `workflow.cancelled`
- `workflow.waiting_input`

TUI should eventually render:

- workflow list/status
- DAG or grouped step timeline
- active agents
- child session links
- artifact/evidence list
- token/time budget usage
- pause/resume/cancel controls
- approval modal for high-fan-out or mutating runs

## API Surface

Initial endpoints:

- `POST /api/v1/workflows/dynamic/plan`
  - returns a validated plan and approval preview.
- `POST /api/v1/workflows/dynamic`
  - creates and optionally starts an approved dynamic workflow.
- `POST /api/v1/workflows/{workflow_id}/approve`
  - records approval and starts/resumes execution.
- `GET /api/v1/workflows/{workflow_id}`
  - extend current response with plan, steps, artifacts, usage.
- `POST /api/v1/workflows/{workflow_id}/signal`
  - preserve pause/resume/cancel/inject_feedback behavior.
- `GET /api/v1/workflows/{workflow_id}/artifacts`
  - returns structured artifact index.

Keep existing `/api/v1/workflows` routes compatible.

## Config Surface

Add config under `orchestration.dynamic_workflows`:

```yaml
orchestration:
  dynamic_workflows:
    enabled: false
    auto: false
    require_approval: true
    max_agents: 20
    max_concurrent_agents: 5
    max_wall_clock_seconds: 7200
    max_total_tokens: 2000000
    default_worker_model: null
    default_reviewer_model: null
    default_refuter_model: null
    allowed_mutation_tools:
      - read_file
      - list_files
      - grep_search
      - execute
      - apply_patch
    high_risk_requires_reviewers: 2
```

Default should be `enabled: false` until the runtime is well tested.

## Permission And Safety Rules

Fail closed:

- No dynamic workflow execution if disabled.
- No auto workflow unless `auto: true`.
- No mutating workflow without approval.
- No external side-effect tool without explicit tool approval.
- No over-budget workflow without approval override.
- No synthesis from unverified high-risk artifacts.

Integrate with existing ToolManager permission checks and approval flow. The
workflow coordinator should not bypass per-tool approval.

## Context Strategy

The coordinator should keep most details out of the main chat context:

- Worker sessions are isolated by default.
- Main conversation receives compact progress events and final synthesis.
- Child outputs are summarized into structured artifacts.
- Full child transcripts remain linked by session ID.
- Synthesis gets summaries/artifacts, not every child transcript.
- Context Window Manager behavior remains trimming, not conversation compaction.

## Implementation Phases

### Phase 0 - Alignment And Naming

- Decide final public name:
  - `dynamic_workflows`
  - `workflow mode`
  - `ultracode`
- Recommendation: use `dynamic_workflows` internally; expose `ultracode` only as
  an optional high-effort preset if desired.
- Decide MVP scope:
  - read-only discovery/audit first, or
  - implementation workflows first.
- Recommendation: start with read-only discovery/review workflows.

### Phase 1 - Durable Plan Schema

- Add plan/step/artifact/run schemas.
- Add schema validation tests.
- Add storage round-trip tests.
- Extend workflow status endpoint to include plan and step summary.
- Add `RuntimeJobRecord(kind="dynamic_workflow")` persistence.

Acceptance:

- A dynamic plan can be created, validated, saved, loaded, and listed.
- Invalid plans fail closed with useful errors.

### Phase 2 - Planner MVP

- Implement model-backed strict-JSON planner behind a service.
- Add deterministic fake-provider planner tests.
- Add plan linting:
  - unknown step kinds
  - cycles
  - unreachable steps
  - missing synthesis
  - mutating step without review
  - budget exceeds config
- Add `POST /api/v1/workflows/dynamic/plan`.

Acceptance:

- Given a fake model response, Penguin creates a valid plan and approval preview.
- Bad planner output cannot start execution.

### Phase 3 - Read-Only Scheduler MVP

- Implement ready-frontier scheduling.
- Execute read-only `explore`, `review`, `refute`, and `synthesize` steps.
- Persist every step transition.
- Emit workflow/step/artifact events.
- Add pause/cancel behavior.
- Add basic resume for pending/ready steps after restart.

Acceptance:

- A read-only codebase audit workflow fans out to multiple agents and produces a
  synthesized final report.
- Step results survive process restart if they completed before interruption.

### Phase 4 - Verification And Artifact Evidence

- Add structured child handoff schema.
- Record `ArtifactEvidence` for findings, reports, changed-file lists, test
  outputs, and review decisions.
- Add reviewer/refuter quorum policies.
- Add convergence decision records.

Acceptance:

- Final synthesis refuses to claim unverified findings as confirmed.
- Refuted findings are either dropped or explicitly reported as unresolved.

### Phase 5 - Mutating Implementation Workflows

- Allow implementation steps with workspace writes.
- Require approval before mutating work.
- Capture changed files per step.
- Integrate tests/use/verify gates with `ValidationManager` and recipe runner.
- Add rollback/checkpoint decision points.
- Keep PR creation in existing project/Git manager paths.

Acceptance:

- A workflow can split an implementation across independent steps, review them,
  run tests/use recipes, then mark the task `pending_review`.

### Phase 6 - TUI And Web UX

- Add workflow timeline state to TUI sync.
- Render workflow status, step groups, active agents, child sessions, artifacts,
  and budget usage.
- Add approval modal.
- Add pause/resume/cancel controls.

Acceptance:

- User can understand what is running without opening logs.
- User can inspect child sessions/artifacts from the workflow view.

### Phase 7 - MCP Runtime Surface

- Expose dynamic workflow tools through Penguin MCP server:
  - `penguin_workflow_plan_dynamic`
  - `penguin_workflow_start_dynamic`
  - `penguin_workflow_get`
  - `penguin_workflow_list`
  - `penguin_workflow_signal`
  - `penguin_workflow_artifacts`
- Keep start/mutation tools runtime-gated.

Acceptance:

- External hosts can plan, start, inspect, and cancel Penguin dynamic workflows
  with the same permission model as web/API.

## Testing Plan

Follow `context/tasks/testing-pyramid.md`.

Required tests before enabling by default:

- Schema/unit:
  - `WorkflowPlan` validation.
  - `WorkflowStepSpec` dependency validation.
  - artifact and run serialization caps.
- Property:
  - arbitrary DAGs either schedule validly or fail with clear cycle/unreachable
    errors.
  - malformed planner JSON never starts execution.
- State-machine:
  - pending -> ready -> running -> completed.
  - running -> cancelled.
  - running -> waiting_input -> running.
  - failed -> retry -> completed.
  - restart with running steps marks them orphaned or resumable.
- Contract:
  - API response shapes.
  - SSE event shapes.
  - Runtime job records.
  - artifact evidence records.
- Fault injection:
  - child agent failure.
  - timeout.
  - partial result.
  - invalid handoff JSON.
  - verifier rejects output.
  - cancel during fan-out.
- Integration:
  - fake-provider end-to-end dynamic audit.
  - fake-provider mutating workflow with temp repo and deterministic tests.
- Live provider:
  - opt-in smoke only, not proof of correctness.

Suggested commands while developing:

```bash
pytest -q tests/test_orchestration.py
pytest -q tests/test_workflow_orchestrator_truth.py
pytest -q tests/tools/test_sub_agent_tools.py
pytest -q tests/api/test_sse_and_status_scoping.py
pytest -q tests/test_mcp_phase1.py
```

Add new focused files:

- `tests/orchestration/test_dynamic_plan_schema.py`
- `tests/orchestration/test_dynamic_scheduler.py`
- `tests/orchestration/test_dynamic_resume.py`
- `tests/orchestration/test_dynamic_verification.py`
- `tests/api/test_dynamic_workflow_routes.py`
- `tests/api/test_dynamic_workflow_sse.py`

## Open Questions

- Should the first MVP be read-only audits/reviews, or should it support code
  mutation from day one?
- Should `ultracode` be a public Penguin term, or only `dynamic workflows`?
- Should the durable workflow storage live in `workflow_state.db`, `.penguin/projects.db`,
  or be consolidated into `ProjectStorage`?
- Should high-fan-out worker sessions share the parent session family in the TUI,
  or appear under a distinct workflow tree?
- Should Temporal become the long-running default backend, or remain optional
  after the native coordinator matures?
- What is the default approval threshold for auto mode: any mutating workflow,
  any workflow over N agents, or any workflow over N estimated tokens?

## Recommendation

Start with a read-only "dynamic audit" slice.

Reasoning:

- It exercises planner, fan-out, persistence, verifier/refuter, synthesis,
  events, and UI visibility without risking broad file mutations.
- It maps directly to high-value use cases: bug hunts, dead-code discovery,
  security scans, architecture review, migration planning.
- It gives Penguin a credible dynamic-workflow product surface before tackling
  multi-agent write conflicts and rollback.

After that, add mutating workflows with strict approval, artifact evidence, and
review gates.

## Definition Of Done For MVP

- Dynamic workflow planning endpoint exists and validates strict schema.
- A read-only workflow can fan out to multiple isolated subagents.
- Workflow/step/artifact state persists durably.
- Progress streams over SSE.
- User can pause/cancel.
- Completed child outputs are summarized into structured artifacts.
- Reviewer/refuter steps run before synthesis.
- Final synthesis cites verified artifacts and separates unresolved/refuted
  findings.
- Fake-provider tests cover planner, scheduler, cancellation, retry, resume, and
  verification behavior.
