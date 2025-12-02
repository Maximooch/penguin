---
title: "<Project or Feature Title>"
project_key: "<KEY>" # e.g., BACKEND, WEB, AUTH
version: 0.1.0
status: draft # draft | active | completed | archived
owners: ["@you"] # Link handles resolve to team/user entities
labels: ["product", "backend"]
repo: "" # optional: repo URL
path: "context/blueprint.md" # optional: path in repo
links:
  - label: "Design Doc"
    url: ""
created: YYYY-MM-DD
updated: YYYY-MM-DD

# ITUV lifecycle defaults (optional, override per-task)
ituv:
  enabled: true
  phase_timebox_sec:
    implement: 600
    test: 300
    use: 180
    verify: 120

# Default agent routing (optional, override per-task)
agent_defaults:
  agent_role: implementer # planner | implementer | qa | reviewer
  required_tools: []
  skills: []
---

# {{ title }}

<!--
Keep this document concise and parseable. Tasks should be explicit and actionable.
Prefer small, well-scoped items. The importer can read tasks, acceptance, and dependencies.
-->

## Overview
<!-- 2–4 sentences describing the what and why. -->

## Goals
- 
- 

## Non-Goals
- 
- 

## Context
<!-- Key decisions, constraints, notable patterns. Keep to short bullets. -->
- Tech stack: 
- Key constraints: 
- Security/perf notes: 

## Interfaces / APIs (optional)
<!-- List important endpoints/contracts. Keep it high level. -->
- GET /api/...
- POST /api/...

## Milestones (optional)
- M1: 
- M2: 

## Tasks
<!--
Task line format (basic):
  - [ ] <IDENT> <Title>

Task line format (with metadata):
  - [ ] <IDENT> <Title> {key=value, ...}

Supported metadata keys:
  Core:
    estimate     - Story points or hours (int)
    priority     - low | medium | high | critical
    labels       - Comma-separated tags
    assignees    - @handles (Link-resolvable)
    due          - YYYY-MM-DD
    id           - Stable slug if IDENT not yet assigned

  ITUV tie-breakers:
    effort       - 1-5 scale (lower = easier)
    value        - 1-5 scale (higher = more impactful)
    risk         - 1-5 scale (higher = riskier)
    sequence     - alpha | beta | rc | ga (soft ordering)

  Agent routing:
    agent_role      - planner | implementer | qa | reviewer
    required_tools  - Comma-separated tool names (apply_diff, grep_search, ...)
    skills          - Comma-separated (python, fastapi, react, ...)
    parallelizable  - true | false (can run concurrently with peers)
    batch           - Group name for batched execution

Rules:
1) IDENT should be stable if known, e.g., AUTH-1. If you don't have numbers yet, use an id=slug.
2) Indent subtasks by two spaces beneath their parent; importer treats them as child tasks.
3) Use one or more "Acceptance:" bullets under a task for criteria (feeds VERIFY gate).
4) Use a "Depends:" bullet listing upstream task idents (comma-separated) for DAG edges.
5) Use a "Recipe:" bullet to reference a usage recipe by name (feeds USE gate).
-->

- [ ] <KEY-1> Short, actionable task title {estimate=2, priority=medium, labels=backend, effort=2, value=4}
  - Acceptance: Clear, verifiable condition 1
  - Acceptance: Clear, verifiable condition 2
  - Depends: <KEY-0>
  - Recipe: happy-path
  - Description: One or two lines of detail if needed

- [ ] <KEY-2> Another task title {estimate=3, priority=high, labels=api,security, assignees=@you, agent_role=implementer, skills=python,fastapi}
  - Acceptance: ...
  - Depends: <KEY-1>
  - Recipe: auth-flow
  - Description: ...
  
  - [ ] <KEY-2A> Subtask example {estimate=1, labels=testing, agent_role=qa, parallelizable=true}
    - Acceptance: ...

<!-- Add more tasks as needed. Keep each concise. -->

## Usage Recipes
<!--
Structured steps for the USE phase. The importer parses these for automated validation.
Each recipe has a name and a list of steps. Steps can be shell, http, or python.

Format:
- recipe: "<name>"
  description: "..."
  steps:
    - shell: "<command>"
      expect_exit: 0
      expect_stdout: "<regex or substring>"
    - http: "<method> <url>"
      body: { ... }
      expect_status: 200
      expect_json: { "key": "value" }
    - python: "<inline assertion or function call>"
  artifacts:
    - stdout
    - response.json
-->

- recipe: "happy-path"
  description: "Basic end-to-end flow"
  steps:
    - shell: "curl -s http://localhost:8000/health"
      expect_exit: 0
      expect_stdout: "ok"
    - http: "POST /api/resource"
      body: { "name": "test" }
      expect_status: 201
      expect_json: { "id": "*" }
    - python: "assert response['id'] is not None"

- recipe: "auth-flow"
  description: "Login and access protected endpoint"
  steps:
    - http: "POST /api/auth/login"
      body: { "username": "test", "password": "secret" }
      expect_status: 200
    - http: "GET /api/protected"
      headers: { "Authorization": "Bearer {{ token }}" }
      expect_status: 200

## Validation
<!-- Spec-level acceptance that complements task-level criteria. Feeds the VERIFY gate. -->
- [ ] End-to-end path works under expected constraints
- [ ] P95 latency < 200ms for critical endpoints
- [ ] Test coverage >= 90% for changed components
- [ ] All referenced recipes pass

## Risks / Open Questions
- Risk: 
- Question: 

## Rollout Plan (optional)
- Launch criteria: 
- Metrics to watch: 
- Rollback strategy: 

## Changelog
- YYYY-MM-DD: v0.1 – Initial blueprint

---

## Reference: ITUV Lifecycle

Each task progresses through four phases (gates):

1. **IMPLEMENT** – Agent writes/modifies code to satisfy the task.
2. **TEST** – Run tests matching task's file patterns or explicit test markers.
3. **USE** – Execute the referenced usage recipe; capture artifacts.
4. **VERIFY** – Check acceptance criteria against test results and recipe outputs.

Phase transitions are automatic when gates pass; failures trigger retries, clarification requests, or escalation based on config.

## Reference: DAG Scheduling

Tasks form a directed acyclic graph via `Depends:` edges. The scheduler:
1. Computes the ready frontier (tasks with all deps satisfied).
2. Applies tie-breakers in order: `priority` (desc), `due` (asc), `sequence`, `effort` (asc), `value` (desc), `risk` (asc), `created_at` (asc).
3. Assigns tasks to agents based on `agent_role`, `required_tools`, `skills`.
4. Respects `parallelizable` and `batch` for concurrent execution.

## Reference: Link Integration

- `owners` and `assignees` fields accept `@handles` that resolve to Link user/team entities.
- Link provides the user registry, permissions, and notification routing.
- Blueprint sync can push task updates to Link for cross-system visibility.
