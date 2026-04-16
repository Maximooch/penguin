# PR 1 Checklist: CLI Workspace Semantics and Honesty Fixes

## Purpose

This file defines the exact implementation checklist for the first follow-up CLI PR.

This PR is intentionally narrow.
It should fix the highest-value user-facing honesty problems in the CLI without
turning into a broader bootstrap workflow PR or a premature `cli.py` rewrite.

## Primary Goal

Make project creation and related CLI messaging honest and predictable.

That means:
- no lying `--workspace` flag
- no muddy execution-root vs project-workspace output
- no stale task/project help text that teaches outdated lifecycle truth
- regression tests protecting the new contract

## Behavior Decision

### Decision: **Honor `--workspace`**

Do **not** remove or hide it in PR 1.

### Why

- users already see and reasonably expect this flag to work
- the current behavior is a surface-contract lie
- honoring the option is better than deleting functionality users want
- bootstrap workflow work (`project init`) will be cleaner if workspace semantics are already real

### Required behavior

If the user runs:

```bash
penguin project create MyProject --workspace /some/path
```

then the created project should record a workspace path rooted at `/some/path`
(or a clearly documented derived child path if that is the chosen contract).

### Constraint

This PR must **not** introduce hidden behavior.
If the chosen workspace resolution logic is:
- exact path
- normalized path
- project-subdirectory path

then that rule must be explicit in:
- command output
- help text
- tests

## Scope

### In Scope
- `project create --workspace` semantics
- project creation output wording
- execution root vs project workspace clarity
- stale task/project help text cleanup where it conflicts with current truth
- regression tests for workspace/location behavior

### Out of Scope
- `project init`
- `project start`
- broader bootstrap workflow logic
- large CLI help overhaul
- broad CLI decomposition
- runmode command redesign
- `PenguinAPI` surface work

## Files To Touch

### Required
- `penguin/cli/cli.py`
  - `project create`
  - possibly shared project/workspace output helpers
  - task/project help wording cleanup
- `penguin/project/manager.py`
  - if needed to actually honor explicit project workspace paths cleanly
- `penguin/project/models.py`
  - only if model-level clarification/documentation of workspace semantics is needed
- `docs/docs/usage/project_management.md`
  - update CLI semantics after implementation
- `docs/docs/usage/cli_commands.md`
  - update help/examples if behavior changes materially

### Possibly touched
- `penguin/project/storage.py`
  - only if persistence behavior needs a small update for explicit workspace path storage
- `context/tasks/cli-interface-ergonomics-plan.md`
  - only if the plan should record the final chosen workspace contract
- `context/tasks/cli-refactor-and-bootstrap-audit.md`
  - optional note that PR 1 behavior decision is now implemented

### Should Avoid If Possible
- top-level callback/init ordering in `main_entry(...)`
- `_initialize_core_components_globally(...)`
- `_handle_run_mode(...)`
- `PenguinCLI` interactive shell class

## Implementation Checklist

### 1. Define the concrete workspace contract
Pick and implement one explicit rule:
- [ ] `--workspace` means **use this exact path as the project workspace**
- [ ] or `--workspace` means **create/use a deterministic child path under this directory**
- [ ] document the rule in code comments/help/output
- [ ] ensure path is normalized (`expanduser`, resolve where appropriate)

### 2. Update `project create`
- [ ] pass the workspace choice through instead of ignoring it
- [ ] remove the misleading `workspace_path is managed internally` behavior/comment
- [ ] fail cleanly if the provided workspace path is invalid or unusable
- [ ] keep project creation output concise but explicit

### 3. Clarify command output
After project creation, output should clearly distinguish:
- [ ] execution root
- [ ] managed Penguin workspace root, if relevant
- [ ] resulting project workspace
- [ ] whether the project workspace came from `--workspace` or default behavior

### 4. Tighten help text
- [ ] `project create --help` reflects real workspace semantics
- [ ] `task list --help` no longer advertises outdated lifecycle examples
- [ ] project/task help avoids implying commands/features that do not exist

### 5. Keep behavior honest under defaults
When `--workspace` is omitted:
- [ ] output should still explain where the project was created
- [ ] default project workspace behavior should be predictable
- [ ] current execution root should not be confused with stored project workspace

## Tests To Add / Update

### Required regression tests
- [ ] `project create --workspace <PATH>` creates a project with the expected recorded workspace path
- [ ] project creation output reflects explicit workspace usage honestly
- [ ] project creation output reflects default workspace behavior honestly
- [ ] `project create --help` documents real workspace semantics
- [ ] `task list --help` / related help text reflects current lifecycle truth

### Good candidates for existing test files
- `tests/test_cli_surface_audit_regressions.py`
- `tests/test_cli_integration.py`
- `tests/test_cli_entrypoint_dispatcher.py`
- any project-manager tests if manager-level workspace semantics change

### Optional but useful
- [ ] test invalid/unusable `--workspace` path failure message
- [ ] test that project listing still shows the created project cleanly after explicit workspace selection
- [ ] test that no stale repo/workspace env leak changes the chosen project workspace unexpectedly

## Suggested Implementation Order

1. define the workspace contract
2. patch manager/create path behavior
3. patch CLI output/help wording
4. add/update regression tests
5. update docs
6. rerun the CLI verification subset most likely to regress

## Verification Commands

Run at minimum:

```bash
pytest -q \
  tests/test_cli_surface_audit_regressions.py \
  tests/test_cli_integration.py \
  tests/test_cli_entrypoint_dispatcher.py
```

If project-manager semantics change, also run the relevant project tests.

## Acceptance Criteria

This PR is done when:
- `project create --workspace` is no longer misleading
- users can distinguish execution root from project workspace from CLI output alone
- stale help text is corrected
- regression tests protect the workspace/location contract
- docs reflect the new truth

## Non-Goals Reminder

This PR is **not** the place to:
- add `project init`
- add `project start`
- redesign runmode flags
- refactor half of `cli.py`
- solve all discoverability issues in one shot

Do the honest thing first. Fancy comes later.
