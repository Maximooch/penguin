# Core Refactor Phase 8: Assault Phase

## Objective

Assault the extracted core/runtime boundaries after phases 5-7 have made the
default suite trustworthy and moved stable responsibilities out of
`PenguinCore`.

Phase 8 should find hidden coupling, order sensitivity, lifecycle edge cases,
and fault-handling gaps without expanding into the future safety-critical
reliability program. Keep it pragmatic, deterministic, and default-suite
friendly.

## Scope

- random-order and repeated default-suite runs
- environment isolation checks
- focused Hypothesis/property tests for small extracted modules
- state-machine tests for already-stabilized lifecycle surfaces
- provider stream edge cases using fake providers and replay fixtures
- fault injection around persistence, event emission, cancellation, and retry
- mutation-test candidates for small critical modules only
- residual-risk inventory for future overkill reliability phases

Do not make Phase 8 a broad observability platform, formal-methods rewrite, or
production metrics project. Those belong in future phases after `core.py` is
smaller and subsystem ownership is clearer.

## Target Surfaces

Prioritize surfaces that phases 5-7 extracted or hardened:

- `penguin/core_runtime/agent_lifecycle.py`
- agent/session routing helpers
- run/task orchestration facade helpers
- checkpoint, fork, revert, and unrevert helpers
- tool/action mapping and action-result metadata
- provider request/stream lifecycle helpers touched by earlier phases
- OpenCode/TUI bridge helpers only where already characterized

## ACBRA Flow

### Audit

- List extracted modules and their critical invariants.
- Identify tests that still rely on ambient env, order, filesystem state, or
  current working directory.
- Identify modules small enough for property or mutation testing.
- Identify lifecycle surfaces that can be modeled as state machines.
- Record residual `PenguinCore` responsibilities that remain too tangled for
  Phase 8 assault.

### Characterize

Freeze expected behavior before adding adversarial tests:

- valid state transitions
- invalid transition failures
- event ordering and exact-once emission
- persistence side effects
- retry/release behavior
- cancellation cleanup
- session, agent, run, and provider isolation

### Build

Add focused adversarial tests:

- Hypothesis properties for normalization and metadata helpers
- Hypothesis state machines for small lifecycle modules
- replay fixtures for incomplete streams and malformed tool-call adjacency
- fault injection for failed save, missing session, cancelled task, and event
  bus failure
- randomized-order checks where the test runner supports them locally

Keep these tests deterministic and offline. Live providers remain opt-in smoke
checks only.

### Refactor

Only refactor when assault tests reveal unclear ownership or brittle behavior.
Prefer small helpers and explicit compatibility shims over moving large blocks
of code late in the phase.

### Assault

Run stress/fault combinations that are still practical for a developer loop:

- repeated targeted test runs
- default suite after order/env isolation changes
- provider stream replay corpus
- state-machine edge-case expansion
- mutation testing on small modules if tooling is available locally

## Acceptance Criteria

- Default `pytest tests -q` remains deterministic and offline.
- Random-order or repeated targeted runs do not expose order/env/cache leakage.
- Critical extracted modules have property or state-machine coverage where the
  input/state space is broad.
- Provider stream edge cases are covered by fake-provider or replay fixtures.
- Fault-injection tests prove cleanup for cancellation, failed persistence, and
  event emission errors.
- Mutation-test candidates are listed even if mutation tooling is deferred.
- A future reliability backlog is updated with overkill testing and
  observability candidates.

## Verification

Run targeted assault clusters first, then:

```bash
uv run --group dev pytest tests -q
python -m compileall penguin tests
git diff --check
```

If `uv` or Ruff is unavailable in the local environment, use the repo venv
fallback and record the exact command used.

## Non-Goals

- no live-provider correctness proof
- no full formal-methods program yet
- no production metrics or tracing platform yet
- no broad mutation testing over legacy god files
- no large new business logic in `PenguinCore`
