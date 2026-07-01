# Core Refactor Phase 5: Agent And Sub-Agent Lifecycle

## Objective

Lock down Penguin's agent and sub-agent lifecycle behind deterministic tests
before extracting more behavior from `PenguinCore`.

Phase 5 should clarify the new conversation-centered API while preserving
`register_agent` as an explicit compatibility shim. The shim should stay small,
well-tested, and clearly routed into the current agent/session machinery; stale
tests should not force deprecated architecture back into the core.

## Scope

- agent registration and lookup compatibility
- conversation-centered agent/session routing
- parent-child sub-agent relationships
- sub-agent event emission and ordering
- waiting, completion, cancellation, and failure behavior
- action result ownership across main agent and sub-agents
- session isolation between concurrent or sequential agents
- lightweight extraction out of `PenguinCore` where tests reveal stable seams

Do not expand this phase into provider runtime, project workflow, checkpoint,
or TUI implementation work except where those surfaces are required to prove
agent lifecycle behavior.

## Compatibility Decision

Keep `register_agent` as a supported shim during this refactor phase.

The shim should:

- accept the existing public call shape where reasonable
- normalize inputs into the conversation-centered runtime path
- avoid network/provider discovery in default tests
- emit or persist the same lifecycle facts as the modern path
- return clear compatibility metadata where useful
- avoid adding new business logic to `PenguinCore`

Tests for shim behavior should be separated from tests for the preferred API so
the compatibility layer remains visible and removable later.

## ACBRA Flow

### Audit

- Inventory current agent-related methods in `penguin/core.py`.
- Identify direct test dependencies on `PenguinCore.__new__`, monkeypatching,
  stale `register_agent` assumptions, and global/session state.
- Map the canonical lifecycle from agent creation through terminal state.
- Record which events are public contract versus incidental implementation
  details.

### Characterize

Capture current supported behavior before changing structure:

- one default agent uses the active conversation/session
- a registered compatibility agent resolves to a deterministic session target
- sub-agents preserve parent identity and do not overwrite parent state
- waiting behavior observes terminal states without polling real external work
- action results attach to the agent/session that produced them
- failed or cancelled sub-agent work emits explicit state instead of silently
  disappearing

### Build

Prefer small hermetic tests with fake managers and in-memory stores.

Test groups:

- `register_agent` shim compatibility
- agent/session routing
- sub-agent creation and parent-child metadata
- lifecycle event ordering
- wait semantics and timeout/failure behavior
- action result ownership
- isolation across multiple agents and sessions

Avoid live providers, real web servers, real GitHub calls, Docker, or network
traffic in default tests.

### Refactor

Extract only after characterization tests are in place.

Likely targets:

- `penguin/core_runtime/agent_runtime.py`
- `penguin/core_runtime/session_routing.py`
- `penguin/agent/persona_runtime.py` follow-up hardening if needed

`PenguinCore` should remain an orchestrator and compatibility facade. New
lifecycle decisions should live in extracted helpers or existing managers.

### Assault

Add edge-case tests after the happy path is stable:

- duplicate agent names or IDs
- missing parent session
- cancelled sub-agent before first event
- sub-agent failure while parent continues
- interleaved action results from multiple agents
- repeated wait calls after terminal state
- randomized agent/session ordering where practical

## Acceptance Criteria

- Default `pytest tests -q` remains deterministic and offline.
- `register_agent` compatibility behavior is explicitly tested as a shim.
- Preferred conversation-centered lifecycle tests do not depend on deprecated
  APIs.
- Agent and sub-agent lifecycle state is owned outside `PenguinCore` where
  practical.
- No new business logic is added to `PenguinCore`.
- Event and action-result ownership are unambiguous in tests.

## Verification

Run targeted tests after each cluster, then periodically run:

```bash
uv run --group dev pytest tests -q
python -m compileall penguin tests
git diff --check
```

Run targeted Ruff checks on new or meaningfully touched files. If legacy files
still carry unrelated lint debt, document the reduced Ruff target used for this
phase.
