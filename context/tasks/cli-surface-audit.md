# CLI Surface Audit

## Purpose

This file tracks concrete CLI-surface findings after the RunMode / Project / ITUV refactor work.

The CLI is currently workable, but it has real drift and a structural problem:
- some commands still reflect older task/project semantics
- some status handling is representation-sensitive
- `penguin/cli/cli.py` is oversized enough that correctness work and decomposition work need to be separated explicitly

This file separates:
- what must be fixed now for surface honesty
- what can be deferred
- what should be decomposed later once correctness is stable

## Scope

### In Scope
- headless CLI task/project/run/workflow surfaces
- slash-command task/project flows in `PenguinInterface`
- CLI event/status display for RunMode clarification states
- correctness of public command behavior and messaging

### Out of Scope
- large-scale `cli.py` slimming in this pass
- broad UX redesign
- registry migration cleanup beyond correctness blockers

## Current Findings

### 1. Task list status filter bug
- File: `penguin/cli/cli.py`
- Lines: `2853-2862`
- Problem:
  - parses status with `TaskStatus(status.upper())`
  - enum values are lowercase
  - valid input can fail incorrectly
- Priority: must-fix now

### 2. Project status summary counts are wrong
- File: `penguin/cli/interface.py`
- Lines: `823-829`
- Problem:
  - compares `t.status.value` to uppercase strings like `"ACTIVE"`
  - actual enum values are lowercase
  - project task summaries can silently undercount or lie
- Priority: must-fix now

### 3. Clarification answer events are not surfaced in CLI status handling
- File: `penguin/cli/event_manager.py`
- Lines: `385-394`
- Problem:
  - `clarification_needed` is handled
  - `clarification_answered` is not
  - CLI can show the pause but not the resume/answer acknowledgement
- Priority: must-fix now

### 4. Task start messaging is semantically stale
- File: `penguin/cli/cli.py`
- Lines: `2908-2941`
- Problem:
  - docstring says “set status to running”
  - implementation sets task to `ACTIVE`
  - messaging still says “started” without clarifying the actual state
- Priority: fix soon

### 5. Task complete command is actually an approval command
- File: `penguin/cli/cli.py`
- Lines: `2949-2981`
- Problem:
  - command name and docstring imply direct completion
  - behavior is actually: approve `PENDING_REVIEW` or no-op if already completed
  - semantics are better than the label, but the label still lies
- Priority: fix soon

### 6. CLI surface duplication is high
- Files:
  - `penguin/cli/cli.py`
  - `penguin/cli/interface.py`
- Problem:
  - task/project behavior is implemented in more than one surface
  - headless Typer commands and slash-command handlers can drift independently
- Priority: document and decompose later, but do not rewrite now

## Must Fix Now

1. Fix CLI task status parsing to accept normal lowercase/uppercase input and report real valid options.
2. Fix project task summary counting to use actual `TaskStatus` semantics instead of uppercase string comparisons.
3. Add `clarification_answered` handling in CLI event/status display so human-in-the-loop resume flow is visible.

These are correctness issues, not cleanup preferences.

## Fix Soon

1. Update `task start` docstring/message to reflect `ACTIVE` state honestly.
2. Rename or reword `task complete` semantics so it is clear this is approval/review completion, not a side-door bypass.
3. Review slash-command task/project responses for richer lifecycle truth (`phase`, clarification state, dependency truth) where useful.

## Recommended Decomposition Later

This is intentionally separate from the must-fix-now work.

### Goal
Shrink `penguin/cli/cli.py` without destabilizing the working CLI.

### Likely decomposition seams
- task/project Typer command definitions → `penguin/cli/project_commands.py`
- run/workflow command definitions → `penguin/cli/run_commands.py`
- app/bootstrap/init helpers → `penguin/cli/bootstrap.py`
- shared task/project rendering → `penguin/cli/renderers/project_rendering.py` or similar
- argument parsing / normalization helpers → `penguin/cli/parsing.py`

### Rules for the later decomposition
- preserve exact command behavior first
- move code without semantic rewrites where possible
- keep test coverage ahead of structural movement
- do not mix “slim file” work with “change lifecycle semantics” work unless unavoidable

## Notes

The CLI is not the cleanest surface, but it should still be a truthful one.

The immediate bar is not elegance. It is stopping the CLI from lying about status, summaries, and clarification flow.
