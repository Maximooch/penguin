# RunMode / Project / ITUV Branch Summary

## What This Branch Fixed

- restored stricter task/runtime truth across RunMode, project orchestration, and ITUV-related flows
- hardened clarification handling so non-terminal outcomes like `waiting_input` are preserved instead of flattened
- improved status/phase visibility in task/web surfaces
- added richer task/project payload truth for web/API consumers
- fixed CLI/root normalization and related surface correctness issues
- restored honest project/task listing behavior and related storage plumbing

## What This Branch Verified

### CLI surface
- scripted verification for project/task help and lifecycle wording
- status filter behavior
- active-state start semantics
- pending-review approval semantics
- execution-root consistency across nested CLI commands

### Web/API surface
- scripted verification for health/task/project routes
- richer task payload truth (`status`, `phase`, dependencies, dependency specs, artifact evidence, clarification metadata)
- execute route preserving non-terminal `waiting_input` outcomes
- clarification resume route behavior
- clarification-related SSE/session visibility support

### Clarification happy path
- deterministic proof that a task can:
  - execute
  - reach `waiting_input`
  - accept a clarification answer
  - resume to a truthful post-clarification result

## What This Branch Explicitly Deferred

- deeper PenguinAPI surface refresh / ergonomics audit
- CLI workspace semantics and broader interface ergonomics
- project bootstrap workflow (`project init`, `project start`)
- RunMode command / loop ownership audit (`--run`, `--247`, `--continuous`, RunMode vs Engine loop boundaries)
- deeper verification hardening / reliability pass 2

## Why The Deferred Split Matters

This branch is the core-truth / verification pass.
It should not keep expanding into CLI redesign, Python library refresh, or broader ergonomics work.

The follow-up backlog for those areas lives in:
- `context/tasks/todo.md`
