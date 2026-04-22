---
title: "Team Tasks API"
project_key: "TASKAPI"
version: 0.1.0
status: draft
owners: ["@you"]
labels: ["backend", "python", "crud"]
created: 2026-04-21
updated: 2026-04-21

ituv:
  enabled: true
  phase_timebox_sec:
    implement: 900
    test: 420
    use: 240
    verify: 180

agent_defaults:
  agent_role: implementer
  required_tools: []
  skills: ["python", "fastapi", "sqlite", "pytest"]
---

# Team Tasks API

## Overview
Build a small but production-lean Python CRUD service for managing team tasks. The system should support user authentication, task CRUD, task filtering, and a lightweight audit trail. This is intended as a practical Penguin test project for project bootstrap, RunMode execution, verification, and later TUI/web workflow testing.

## Goals
- Build a clean Python REST API for task management.
- Support authenticated CRUD operations for users and tasks.
- Include tests, migrations/setup, and basic validation.
- Be realistic enough to exercise Penguin project/task orchestration.

## Non-Goals
- Multi-tenant enterprise RBAC.
- Realtime collaboration.
- Full production infra/deployment automation.

## Context
- Tech stack: Python, FastAPI, SQLite, pytest.
- Key constraints: small codebase, deterministic tests, easy local setup.
- Security/perf notes: auth required for protected routes, input validation, no fake test pass path.

## Interfaces / APIs
- POST /api/auth/register
- POST /api/auth/login
- GET /api/tasks
- POST /api/tasks
- GET /api/tasks/{id}
- PATCH /api/tasks/{id}
- DELETE /api/tasks/{id}

## Tasks
- [ ] TASKAPI-1 Create FastAPI app skeleton {estimate=2, priority=high, labels=backend,api, effort=2, value=5}
  - Acceptance: App starts locally and exposes a health endpoint.
  - Acceptance: Project structure is organized for routes, models, and tests.
  - Recipe: api-health
  - Description: Create the application entrypoint, package layout, and minimal startup wiring.

- [ ] TASKAPI-2 Add SQLite persistence and task model {estimate=3, priority=high, labels=backend,database, effort=3, value=5}
  - Acceptance: Task records persist across runs.
  - Acceptance: Task model supports title, description, status, due_date, and created_by.
  - Depends: TASKAPI-1
  - Recipe: task-crud
  - Description: Add database setup and persistence logic for task data.

- [ ] TASKAPI-3 Add user registration and login {estimate=3, priority=high, labels=auth,api, effort=3, value=5}
  - Acceptance: Users can register and log in with hashed passwords.
  - Acceptance: Auth returns a token or session suitable for protected routes.
  - Depends: TASKAPI-1
  - Recipe: auth-flow
  - Description: Implement basic authentication flow for local use.

- [ ] TASKAPI-4 Protect task routes with authentication {estimate=2, priority=high, labels=auth,api, effort=2, value=5}
  - Acceptance: Unauthenticated task access is rejected.
  - Acceptance: Authenticated users can access only valid task operations.
  - Depends: TASKAPI-2, TASKAPI-3
  - Recipe: auth-flow
  - Description: Add route protection and current-user resolution.

- [ ] TASKAPI-5 Implement task CRUD endpoints {estimate=4, priority=high, labels=crud,api, effort=3, value=5}
  - Acceptance: Users can create, list, update, and delete tasks.
  - Acceptance: API returns appropriate status codes and JSON payloads.
  - Depends: TASKAPI-2, TASKAPI-4
  - Recipe: task-crud
  - Description: Implement the main task API behavior.

- [ ] TASKAPI-6 Add task filtering and validation {estimate=2, priority=medium, labels=crud,validation, effort=2, value=4}
  - Acceptance: Tasks can be filtered by status and due date.
  - Acceptance: Invalid payloads fail with clear validation errors.
  - Depends: TASKAPI-5
  - Recipe: task-filtering
  - Description: Add query filtering and stronger request validation.

- [ ] TASKAPI-7 Add tests for auth and CRUD flows {estimate=4, priority=high, labels=testing,qa, effort=3, value=5}
  - Acceptance: Auth and task CRUD are covered by pytest tests.
  - Acceptance: Tests are deterministic and runnable locally.
  - Depends: TASKAPI-5
  - Recipe: test-suite
  - Description: Add focused automated coverage for happy path and invalid input paths.

- [ ] TASKAPI-8 Add audit trail for task changes {estimate=3, priority=medium, labels=backend,audit, effort=3, value=4}
  - Acceptance: Task create/update/delete actions are recorded.
  - Acceptance: Audit entries include actor, timestamp, and action type.
  - Depends: TASKAPI-5
  - Recipe: audit-trail
  - Description: Add a simple audit log for task mutations.

## Usage Recipes
- recipe: "api-health"
  description: "Verify the API starts and responds to a health check."
  steps:
    - http: "GET /health"
      expect_status: 200
      expect_json: {"status": "ok"}

- recipe: "auth-flow"
  description: "Register, log in, and access a protected endpoint."
  steps:
    - http: "POST /api/auth/register"
      body: {"email": "test@example.com", "password": "secret123"}
      expect_status: 201
    - http: "POST /api/auth/login"
      body: {"email": "test@example.com", "password": "secret123"}
      expect_status: 200
    - http: "GET /api/tasks"
      headers: {"Authorization": "Bearer {{ token }}"}
      expect_status: 200

- recipe: "task-crud"
  description: "Create, fetch, update, and delete a task."
  steps:
    - http: "POST /api/tasks"
      headers: {"Authorization": "Bearer {{ token }}"}
      body: {"title": "Write tests", "description": "Add coverage", "status": "todo"}
      expect_status: 201
      expect_json: {"id": "*"}
    - http: "GET /api/tasks/{{ id }}"
      headers: {"Authorization": "Bearer {{ token }}"}
      expect_status: 200
    - http: "PATCH /api/tasks/{{ id }}"
      headers: {"Authorization": "Bearer {{ token }}"}
      body: {"status": "done"}
      expect_status: 200
    - http: "DELETE /api/tasks/{{ id }}"
      headers: {"Authorization": "Bearer {{ token }}"}
      expect_status: 204

- recipe: "task-filtering"
  description: "Verify filtering by task status."
  steps:
    - http: "GET /api/tasks?status=todo"
      headers: {"Authorization": "Bearer {{ token }}"}
      expect_status: 200

- recipe: "test-suite"
  description: "Run the automated test suite."
  steps:
    - shell: "pytest -q"
      expect_exit: 0

- recipe: "audit-trail"
  description: "Verify task mutations create audit entries."
  steps:
    - http: "GET /api/audit"
      headers: {"Authorization": "Bearer {{ token }}"}
      expect_status: 200

## Validation
- [ ] Authenticated task CRUD works end-to-end.
- [ ] Invalid payloads fail with explicit validation errors.
- [ ] Test suite passes locally.
- [ ] Audit trail records task mutations.

## Risks / Open Questions
- Risk: Auth/session implementation may drift if kept too abstract.
- Question: Should audit entries be exposed via API immediately or remain internal first?

## Changelog
- 2026-04-21: v0.1 – Initial Penguin bootstrap/testing blueprint example
