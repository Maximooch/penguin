# Core Refactor Future Phases: Overkill Reliability

## Purpose

After phases 7-8 finish the current extraction and assault work, run a separate
reliability campaign that treats Penguin's core/runtime boundary like
mission-critical infrastructure.

This document intentionally does not expand Phase 7 or Phase 8. It captures the
future "overkill" direction so the current branch can stay focused.

## Guiding Principle

Every production bug should become one of:

- a deterministic unit, contract, property, state-machine, replay, or
  fault-injection test
- an observability gap with a concrete event/metric/trace field to add
- a spec gap where the intended behavior was not explicit enough

## Future Testing Layers

### Property Testing

Use Hypothesis for small, deterministic contracts:

- model/provider ID normalization
- request preparation and base URL isolation
- tool/action payload normalization
- action-result metadata synthesis
- CWM category-priority and recency trimming
- checkpoint/fork/revert metadata invariants
- event payload defaults and missing optional fields

### Stateful Model Testing

Use Hypothesis state machines or equivalent executable reference models for:

- agent/sub-agent lifecycle
- task/run orchestration lifecycle
- provider stream lifecycle
- checkpoint/fork/revert graph lifecycle
- permission/question lifecycle
- busy/idle request reference counting

### Replay Testing

Build replay corpora for:

- provider streams, including incomplete and malformed streams
- native tool-call adjacency
- OpenCode/TUI event traces
- project/run orchestration traces
- checkpoint/fork/revert traces

Replay fixtures should be minimized, scrubbed, deterministic, and runnable
offline.

### Fault Injection

Inject failures around:

- session save/load
- checkpoint persistence
- event bus emission
- provider retry and release behavior
- tool execution cancellation
- filesystem permission errors
- malformed config/env
- corrupted session metadata

### Mutation Testing

Use mutation testing only where the module is small enough that failures are
actionable:

- provider request prep
- stream state transitions
- task state transitions
- checkpoint lineage helpers
- agent lifecycle helpers
- action mapping helpers

Do not start with mutation testing on `core.py` or other legacy god files.

### Formal Methods

Use formal specs only for stable, compact state machines where ambiguity is
expensive:

- task lifecycle
- provider stream lifecycle
- checkpoint/fork/revert lineage
- request busy/idle reference counting

Start with executable Python reference models. Add TLA+ or another external
formal model only when the implementation contract is stable enough to justify
maintaining a parallel spec.

## Observability And Metrics

After `core.py` is mostly a facade, add structured observability for every
meaningful operation.

Required correlation fields:

- `request_id`
- `session_id`
- `conversation_id`
- `agent_id`
- `task_id`
- `provider`
- `model`
- `phase`
- `state_before`
- `state_after`
- `error_category`
- `duration_ms`

Trace surfaces:

- `core.process`
- provider request and stream lifecycle
- tool/action execution
- sub-agent spawn and wait
- RunMode task execution
- checkpoint/fork/revert
- OpenCode/TUI bridge events

Metrics should answer:

- which lifecycle transitions fail most often
- which providers produce incomplete streams
- where cancellation cleanup fails
- which tools produce ambiguous or oversized outputs
- which sessions or agents leak state across boundaries
- where retries are happening and whether they are safe

## Reliability Backlog Seeds

- Add a replay fixture format for provider streams and OpenCode events.
- Add state-machine reference models for task and stream lifecycles.
- Add a trace schema for core/runtime operations.
- Add event/metric capture hooks that default to no-op in tests.
- Add mutation tooling for small extracted modules.
- Add random-order and repeated-run jobs in CI once the default suite is
  consistently clean.
- Add failure classifiers to default-suite reports: stale test, real
  regression, external opt-in, env leak, order leak.

## Non-Goals

- no live-provider dependency in the default suite
- no broad formal spec for all of Penguin
- no metrics platform before subsystem boundaries are stable
- no mutation testing over large legacy files
- no replacing pragmatic ACBRA work with speculative assurance artifacts
