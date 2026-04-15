# PenguinAPI Surface Refresh Plan

## Purpose

This file scopes a follow-up branch/PR for refreshing the Penguin Python API/library
surface so it matches current runtime truth more closely.

This work is intentionally lower priority than CLI and web/API surface verification.
Those surfaces are more heavily used and were the priority in the current
RunMode / Project / ITUV reliability pass.

## Why This Is Separate

The current branch focused on:
- core RunMode / project / ITUV correctness
- clarification handling
- surface verification for CLI and web/API
- restoring honest public behavior

The Python embedding surface (`PenguinAPI` and related library entry points) now has
some compatibility glue, but it has not received the same depth of audit, verification,
and UX cleanup as the CLI and web/API surfaces.

## Current State

### What exists now
- `PenguinAPI.run_task(...)` routes through `RunMode`
- `PenguinAPI.resume_with_clarification(...)` delegates to `RunMode`
- lightweight tests exist for delegation behavior

### What is still missing
- a broader surface contract audit
- stronger verification of result shapes and parity
- clarification-flow happy-path coverage through the embedding surface
- documentation refresh for current library semantics
- confidence that `PenguinAPI` is a first-class public surface rather than a thin wrapper that drifted behind runtime changes

## Scope

### In Scope
- `PenguinAPI` method contract audit
- clarification/resume support review
- return-shape normalization review
- docs/examples refresh
- dedicated verification checklist or test plan
- parity notes against CLI and web/API where useful

### Out of Scope
- core RunMode/ITUV state-machine changes unless needed for compatibility
- CLI ergonomics and bootstrap command design
- large-scale web route redesign

## Candidate Workstreams

### 1. Audit current public methods
Review:
- `PenguinAPI.chat(...)`
- `PenguinAPI.run_task(...)`
- `PenguinAPI.resume_with_clarification(...)`
- any related `PenguinAgent` convenience entry points that are meant to be public-facing

Questions:
- do return shapes match current runtime truth?
- do errors surface consistently?
- do clarification-related non-terminal states survive intact?
- are method names and docs still honest?

### 2. Clarification-flow parity
Add or strengthen tests for:
- `run_task(...)` returning `waiting_input`
- `resume_with_clarification(...)` happy path
- error path for missing/open clarification mismatch
- parity with web route behavior where practical

### 3. Result-shape normalization
Review whether the Python API should guarantee:
- `status`
- `completion_type`
- `message`
- iteration counts
- task identifiers / project identifiers where available

If shapes differ across library entry points, document and normalize intentionally.

### 4. Documentation refresh
Update:
- examples
- method docs
- any README or docs usage sections that imply stale library behavior

### 5. Verification plan
Create a dedicated audit/testing file if needed so the Python embedding surface is not silently treated as “probably fine.”

## Priority

Lower than:
- core runtime correctness
- CLI surface truth
- web/API surface truth

Higher than:
- speculative ergonomics polish for the library surface

## Acceptance Criteria

This follow-up is good enough when:
- `PenguinAPI` methods reflect current runtime truth honestly
- clarification-related non-terminal states are verifiably preserved
- docs/examples are not materially stale
- the library surface has a dedicated audit/testing trail rather than piggybacking on CLI/web assumptions

## Relationship to Other Files

- `context/tasks/runmode-project-ituv-checklist.md`
- `context/tasks/surface-verification-checklist.md`
- `context/tasks/cli-interface-ergonomics-plan.md`

## Bottom Line

`PenguinAPI` should be treated as a real public surface, but it does not need to block
the current branch from wrapping.

It needs its own refresh/audit pass, not more accidental drift.
