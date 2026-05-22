# Core Refactor Phase 7: Continue Core Extraction Slices

## Objective

Continue extracting stable responsibilities from `PenguinCore` after the
default suite, provider contracts, web/provider services, agent lifecycle, and
project orchestration tests are trustworthy.

Phase 7 is not a free-form cleanup pass. Each extraction should start from a
tested contract and end with `PenguinCore` acting as construction, delegation,
and compatibility facade only.

## Scope

Candidate extraction areas:

- agent/session routing
- run/task orchestration facade methods
- checkpoint, fork, and revert surfaces
- tool/action mapping and action-result metadata
- status and diagnostics helpers
- OpenCode/TUI bridge helpers only where already characterized by earlier
  phases

Avoid extracting unrelated code solely because `core.py` is large. Prefer
bounded slices whose behavior is already protected by deterministic tests.

## Extraction Rules

- Add or repair tests before moving behavior.
- Preserve public API compatibility where reasonable.
- Use explicit compatibility shims rather than restoring deprecated
  architecture.
- Do not add new business logic to `PenguinCore`.
- Keep route business logic in `penguin/web/services/*`.
- Keep provider request/runtime behavior in provider/runtime modules.
- Keep Penguin's CWM terminology accurate: it trims by category priority and
  recency; do not describe current behavior as compaction.

## ACBRA Flow

### Audit

For each candidate slice:

- list current `PenguinCore` methods and direct collaborators
- identify public API callers, test callers, CLI/web/TUI callers, and legacy
  compatibility paths
- record current state mutations and persistence side effects
- classify behavior as orchestration, business logic, compatibility, or dead
  code
- check for existing plan dependencies in `context/tasks`

### Characterize

Before moving code, prove the current supported behavior:

- inputs and outputs
- state mutation boundaries
- emitted events
- persistence side effects
- failure behavior
- compatibility behavior
- isolation between sessions, agents, runs, and providers

Delete or mark tests only when they encode stale behavior. Fix runtime code when
tests reveal real contract drift.

### Build

Build the smallest useful test pyramid for the slice:

- unit tests for pure helpers and state transitions
- contract tests for provider/tool/runtime boundaries
- service or manager tests for business behavior
- in-process integration tests for public API paths
- opt-in smoke tests only for live providers or external systems

Prefer fake providers, fake tools, in-memory stores, captured requests, and
deterministic fixtures.

### Refactor

Move behavior into focused modules.

Likely package targets:

- `penguin/core_runtime/` for core-facing orchestration helpers
- `penguin/orchestration/` for run/task state and transitions
- `penguin/agent/` for agent lifecycle and persona behavior
- `penguin/tools/` for tool/action mapping if ownership belongs there
- `penguin/web/services/` for web-facing business logic

Keep imports one-way where practical: extracted modules should not need to
import `PenguinCore` just to perform their work.

### Assault

Once a slice is extracted:

- run tests in random order where supported
- add fault-injection around persistence and event emission
- add property tests for small pure state modules where useful
- add provider stream edge cases when the slice touches streaming
- consider mutation tests only for small critical modules with stable behavior

## Suggested Slice Order

1. Agent/session routing follow-up from Phase 5.
2. Run/task orchestration facade follow-up from Phase 6.
3. Checkpoint, fork, and revert surfaces.
4. Tool/action mapping and action-result metadata.
5. Status, diagnostics, and system information helpers.
6. OpenCode/TUI bridge helpers after upstream OpenCode reference review where
   relevant.

Use `/Users/maximusputnam/Code/Penguin/penguin/reference/opencode` as reference
material for OpenCode/TUI, OpenAI auth, and provider-handling shape when those
areas intersect this phase. Preserve Penguin's architecture boundaries and
offline default-test constraints.

## Acceptance Criteria

- `PenguinCore` line count and direct responsibility count trend downward.
- Extracted modules have focused tests that fail for meaningful regressions.
- Public API compatibility is preserved or intentionally shimmed.
- Default `pytest tests -q` remains deterministic and offline.
- No extraction introduces hidden network, provider credential, Docker, or real
  server assumptions.
- Each completed slice has an ITUV note or equivalent verification summary.

## Verification

Run targeted tests for each extraction, then periodically run:

```bash
uv run --group dev pytest tests -q
python -m compileall penguin tests
git diff --check
```

Run targeted Ruff checks on every new extracted module and each meaningfully
touched test file. Broad Ruff failures from unrelated legacy files should be
documented separately instead of blocking scoped extraction work.
