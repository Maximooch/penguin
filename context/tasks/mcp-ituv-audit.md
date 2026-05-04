# MCP ITUV Audit

## Status

- Created: 2026-05-04
- Scope: Phase 2B Slice 4 planning for Penguin's MCP server surface
- Bias: expose read/status truth before mutation

## Context

The broad system model lives in `context/architecture/runmode-project-ituv-system-map.md`. That file is useful orientation, but the implementation truth comes from code.

Relevant code checked for Slice 4A:

- `penguin/project/models.py`
  - `TaskStatus`
  - `TaskPhase`
  - `DependencyPolicy`
  - `ArtifactEvidence`
- `penguin/project/manager.py`
  - `get_ready_tasks`
  - `get_blocked_ready_candidates`
  - `get_next_task_dag`
  - `get_dag_stats`
  - `_is_dependency_satisfied`
  - `_get_unsatisfied_dependencies`
- `penguin/web/services/project_payloads.py`
  - shared task/project serializers already used by MCP PM and Blueprint tools

## State Model

Penguin task lifecycle has two axes:

- `status`: operational/review state
- `phase`: ITUV workflow phase

Current `TaskPhase` values:

- `pending`
- `implement`
- `test`
- `use`
- `verify`
- `done`
- `blocked`

Current `TaskStatus` values:

- `active`
- `running`
- `pending_review`
- `completed`
- `cancelled`
- `failed`
- `archived`

Important semantic warning:

- `phase=done` is not the same thing as `status=completed`.
- Successful execution normally reaches `phase=done` and `status=pending_review` before human/trusted approval completes the task.

## Dependency Readiness Semantics

Current central dependency check is `ProjectManager._is_dependency_satisfied(...)`.

Policies:

- `completion_required`: upstream `status == completed`
- `review_ready_ok`: upstream `phase == done` and `status in {pending_review, completed}`
- `artifact_ready`: valid matching artifact evidence on the upstream dependency task

This is the source of truth for DAG frontier/readiness. MCP should not duplicate this logic when a `ProjectManager` method can answer the question.

## Public/Usable Read APIs

Safe to expose read-only in Slice 4A:

- `ProjectManager.get_dag_stats(project_id)`
- `ProjectManager.get_ready_tasks(project_id)`
- `ProjectManager.get_next_task_dag(project_id)`
- `ProjectManager.get_blocked_ready_candidates(project_id)`
- task/project serializers from `penguin.web.services.project_payloads`

Useful but private:

- `_get_unsatisfied_dependencies(task, task_map)`

Slice 4A may use `_get_unsatisfied_dependencies` defensively for task-specific readiness, but this should be treated as an implementation detail. If the surface becomes important, extract a public ProjectManager method later.

## Mutation APIs To Avoid For Slice 4A

Do not expose yet:

- `update_task_status`
- `update_task_phase`
- `mark_task_execution_ready_for_review`
- artifact evidence writes
- ITUV workflow signaling

Reason: these mutate lifecycle state and require legal transition validation plus a policy story. Exposing them before read/status is solid is a foot-gun.

## Slice 4A Tool Recommendation

Expose behind `--allow-runtime-tools`:

- `penguin_ituv_capabilities`
  - status values
  - phase values
  - status transition map
  - dependency policies
  - known gaps
- `penguin_ituv_status`
  - task/project lifecycle truth
  - dependency specs
  - artifact evidence
  - DAG stats
  - ready tasks and blocked candidates when scoped to a project
- `penguin_ituv_frontier`
  - dependency-aware ready task frontier
  - next DAG task
  - blocked candidates

All Slice 4A tools must be read-only.

## Slice 4B Preconditions

Before mutation/signaling tools:

1. Define legal phase transition rules as explicitly as `TaskStatus.valid_transitions()`.
2. Decide whether MCP may call `update_task_status` / `update_task_phase` directly or must route through an orchestrator/service.
3. Define artifact evidence write schema and validation.
4. Make pending-review vs completed semantics impossible to confuse.
5. Decide whether mutation tools need a separate flag beyond `--allow-runtime-tools`.

## Decision

Proceed with Slice 4A only. Pause before Slice 4B.
