# Runtime Surface Audit Checklist

## Purpose

This file tracks the audit of Penguin's public and semi-public runtime surfaces after the recent RunMode / Project / ITUV refactor work.

It exists because the current work has changed backend truth substantially:
- task lifecycle semantics
- typed dependency behavior
- Blueprint diagnostics
- clarification waiting
- clarification answer/resume flow

The risk now is not only backend bugs. It is **surface drift**:
- CLI commands that do not reflect current runtime behavior
- web/API endpoints that expose stale or incomplete task flows
- library exports that have quietly fallen behind
- examples/docs that imply capabilities or return shapes that no longer match implementation

## Audit Principle

Do **not** treat "surface audit" as a rewrite project.

The goal of this pass is:
- identify stale or missing public entry points
- identify mismatched contracts and return shapes
- identify where behavior changed but surfaces did not
- separate "must fix now" from "should defer until after major slimming/refactor"

This is especially important for `penguin/cli/cli.py`, which is large and messy.  
Slimming it down is a valid future project, but not the scope of this audit.

## Current Surface Map

### CLI Surface
Primary entry files:

- `penguin/cli/entrypoint.py`
- `penguin/cli/cli.py`
- `penguin/cli/commands.py`
- `penguin/cli/command_registry.py`
- `penguin/cli/interface.py`
- `penguin/cli/typer_bridge.py`

Reality note:

- `penguin/cli/cli.py` is a monster file and likely needs eventual decomposition.
- This audit should focus on correctness and compatibility first, not structural cleanup.

### Web/API Surface
Primary entry files:

- `penguin/web/server.py`
- `penguin/web/app.py`
- `penguin/web/routes.py`
- `penguin/web/sse_events.py`

Reality note:

- the web surface is probably less structurally chaotic than CLI
- but it still needs contract review for task lifecycle and clarification flow support

### Library / Embedding Surface
Primary entry files:

- `penguin/__init__.py`
- `penguin/api_client.py`
- high-level exports such as:
  - `PenguinAgent`
  - `PenguinClient`
  - `PenguinCore`
  - lazy-loaded project/task exports

Reality note:

- the library surface appears least recently tended
- stale exports and outdated examples are high-probability risk areas

### Packaging / Script Entry Surface
Primary references:

- `pyproject.toml`
- `[project.scripts]` entry points
- package export surface in `penguin/__init__.py`

## Must-Audit Areas

### 1. CLI Command Coverage vs Current Backend Truth
- [ ] Verify CLI commands that touch tasks/project/run mode still match current lifecycle semantics
- [ ] Verify CLI flows do not assume direct completion where orchestration/validation now owns completion
- [ ] Verify CLI output/messages do not lie about clarification-needed vs completed behavior
- [ ] Verify any CLI task/project commands understand typed dependencies where relevant
- [ ] Identify commands that should expose clarification answer/resume behavior
- [ ] Record commands that are functionally correct but structurally deferred because `cli.py` needs slimming later

### 2. Web/API Endpoint Coverage vs Current Backend Truth
- [ ] Identify task/project endpoints and check whether they expose current phase/status semantics
- [ ] Identify whether clarification-needed state is visible through API responses
- [ ] Identify whether clarification answer/resume is exposed anywhere
- [ ] Verify SSE/event surfaces understand `clarification_needed` and `clarification_answered`
- [ ] Verify web routes do not silently flatten typed dependency semantics into old plain-dependency behavior
- [ ] Record missing endpoints/fields separately from implementation bugs

### 3. Library / Embedding Contract Audit
- [ ] Verify `penguin/__init__.py` exports still reflect maintained public surface
- [ ] Verify high-level client/agent examples are not stale relative to current runtime behavior
- [ ] Identify whether library consumers can access task/project/clarification flows cleanly
- [ ] Identify missing or misleading helper APIs for task execution, diagnostics, or clarification resume
- [ ] Separate "stale but harmless" export issues from "actively misleading" ones

### 4. Packaging / Entrypoint Audit
- [ ] Verify `pyproject.toml` script entry points still match actual supported interfaces
- [ ] Verify entrypoint routing in `penguin/cli/entrypoint.py` still reflects intended CLI vs TUI behavior
- [ ] Verify package export claims in docs/examples match available symbols
- [ ] Flag any entry points that look accidentally stale, broken, or misleading

### 5. Contract / Return Shape Audit
- [ ] Compare return shapes for task-related flows across CLI, web/API, and library surfaces
- [ ] Compare how surfaces expose:
  - task status
  - task phase
  - dependency readiness state
  - clarification requests
  - clarification answers / resume results
- [ ] Identify where one surface has the new truth and another still exposes old assumptions
- [ ] Treat inconsistent return semantics as audit findings even if individual surfaces "work"

### 6. Event / Observability Surface Audit
- [ ] Verify consumers of runtime status events handle:
  - `clarification_needed`
  - `clarification_answered`
- [ ] Identify whether any UI/event plumbing silently drops these events
- [ ] Record whether event payload shape is documented anywhere useful

## Explicit Deferrals

These are intentionally **not** the goal of this audit pass unless they block correctness:

- [ ] large-scale `cli.py` decomposition / slimming
- [ ] major library API redesign
- [ ] broad CLI UX redesign
- [ ] broad API re-architecture
- [ ] doc polish beyond what is required to stop misleading users

## Deliverables

A useful audit pass should produce:

- a list of surface mismatches by category:
  - CLI
  - web/API
  - library
  - packaging/entrypoints
- a split between:
  - must-fix now
  - safe to defer
  - larger refactor follow-up
- specific file-level references for each issue
- recommended sequencing for fixes

## Suggested Follow-On Task Files

Depending on findings, these are likely next-step files to create:

- `context/tasks/cli-surface-audit.md`
- `context/tasks/library-surface-audit.md`

That split is probably justified if:
- CLI findings are numerous but partly blocked by future `cli.py` slimming
- library findings are stale enough to require a separate rehabilitation pass

## Notes

Use `context/tasks/penguin-capability-bar.md` as the quality bar for this audit.

This audit is not about making the surfaces pretty.  
It is about making sure they do not lie.
