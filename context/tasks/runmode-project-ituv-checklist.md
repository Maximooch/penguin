# RunMode / Project / ITUV Checklist

## Purpose

This file is the execution-tracking companion to `context/tasks/runmode-project-ituv-gap-matrix.md`.

Use this checklist to track what is:

- completed
- in progress
- next
- deferred
- explicitly rejected for now

Do **not** turn this file into a second copy of the architecture contracts or the gap matrix.

## Completed

- [x] Define and document the canonical task state-machine contract
  - Reference: `context/architecture/ituv-task-state-machine-contract.md`
- [x] Define and document the artifact evidence contract
  - Reference: `context/architecture/artifact-evidence-contract.md`
- [x] Define and document the typed dependency syntax contract
  - Reference: `context/architecture/blueprint-typed-dependency-syntax-contract.md`
- [x] Define and document the clarification handling contract
  - Reference: `context/architecture/clarification-handling-contract.md`
- [x] Add the runmode/project/ITUV system map
  - Reference: `context/architecture/runmode-project-ituv-system-map.md`
- [x] Prevent `RunMode` from directly completing project tasks
- [x] Enforce task `status × phase` integrity in manager-level transitions
- [x] Add explicit task phase persistence/update APIs
- [x] Harden validation to fail closed
- [x] Add cycle detection during dependency validation
- [x] Implement dependency policy semantics
  - Includes:
    - `completion_required`
    - `review_ready_ok`
    - `artifact_ready`
- [x] Add artifact evidence support for `artifact_ready`
- [x] Add focused and Hypothesis-backed dependency-policy coverage
- [x] Add Markdown Blueprint support for typed dependency syntax
  - Includes multiline `Depends:` and structured `Dependency Specs:`
- [x] Add Blueprint diagnostics v1
  - Includes coded parse errors and a minimal linter
- [x] Implement clarification waiting handling
  - Includes:
    - `waiting_input`
    - clarification persistence in `Task.metadata["clarification_requests"]`
    - `clarification_needed` runtime event
- [x] Implement clarification resume/answer handling
  - Includes:
    - `RunMode.resume_with_clarification(...)`
    - answer persistence
    - closing latest open clarification
    - injected clarification context on resume
    - `clarification_answered` runtime event
- [x] Cross-link the architecture doc cluster so the contracts and plans are discoverable
- [x] Define the Penguin capability bar / quality standard
  - Reference: `context/tasks/penguin-capability-bar.md`

## In Progress

- [ ] Verification hardening: deeper Hypothesis / stateful coverage
  - Reference: `context/tasks/runmode-project-ituv-gap-matrix.md`

## Next

- [ ] Review and update CLI/API/library surfaces for compatibility with the refactored runtime
  - Audit user-facing and embedding entry points so they reflect current task, clarification, and dependency behavior
  - Reference: `context/tasks/runtime-surface-audit-checklist.md`
- [ ] Review Blueprint sync/import callers for new parser and diagnostics semantics
- [ ] Audit task metadata consumers for clarification and artifact evidence compatibility
- [ ] Audit event/UI consumers for new clarification status events
- [ ] Review README / architecture / public docs drift after the runtime refactor
- [ ] Define and normalize public-surface contracts for task and clarification flows
  - Especially return shapes and entry points across CLI, API, and library embeddings
- [ ] Update public docs for typed dependencies, diagnostics, and clarification handling
- [ ] Review `context/process/blueprint.template.md` for typed dependency and diagnostics drift
- [ ] Review `context/tasks/testing_scenarios.md` for stale scenarios after clarification, diagnostics, and dependency-policy changes
- [ ] Keep verification-planning docs aligned without prematurely dragging in TLA+ v2 scope
  - Reference: `context/tasks/penguin_tla.md` is later-stage work, not the current reliability-first pass
- [ ] Use `context/tasks/penguin-capability-bar.md` as the quality bar when auditing surfaces and verification expectations
- [ ] Extend current Hypothesis/property-based tests for dependency-policy semantics
- [ ] Add stateful transition tests for `TaskStatus` and `TaskPhase`
- [ ] Add clarification lifecycle invariants for waiting/resume behavior
- [ ] Decide whether waiting tasks should release execution slots for other ready tasks
- [ ] Wire clarification handling into CLI/API surfaces
  - Expose `resume_with_clarification` through a real user-facing interface

## Deferred

- [ ] Waiting-time vs execution-time accounting
  - Current stance: defer until timebox enforcement matters operationally
- [ ] Automatic blocker escalation after unanswered clarification timeout
  - Revisit after waiting/accounting semantics are clearer

## Rejected / Not Now

- [ ] Global timeout-based default assumptions for unanswered clarification
  - Current stance: reject unless explicitly task-scoped and intentionally configured
- [ ] Treat scheduler-aware waiting as equivalent to time accounting
  - Current stance: keep them separate

## References

- Strategy / backlog: `context/tasks/runmode-project-ituv-gap-matrix.md`
- Capability bar: `context/tasks/penguin-capability-bar.md`
- Surface audit checklist: `context/tasks/runtime-surface-audit-checklist.md`
- Lifecycle contract: `context/architecture/ituv-task-state-machine-contract.md`
- Artifact contract: `context/architecture/artifact-evidence-contract.md`
- Typed dependency syntax: `context/architecture/blueprint-typed-dependency-syntax-contract.md`
- Clarification contract: `context/architecture/clarification-handling-contract.md`
- System map: `context/architecture/runmode-project-ituv-system-map.md`
