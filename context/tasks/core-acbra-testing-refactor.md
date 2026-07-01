# Core.py ACBRA Testing And Refactor Campaign

## Purpose

Turn `penguin/core.py` from a high-risk coordinator/god object into a small,
well-tested composition layer by applying a repeatable ACBRA loop:

1. **Audit** current behavior, responsibilities, invariants, and failure modes.
2. **Characterize** behavior that must not regress.
3. **Build** the testing pyramid for the target slice.
4. **Refactor** behind the new test boundary.
5. **Assault** the slice with stress, property, fault-injection, and mutation
   checks where they are useful.

This document is intentionally scoped to `core.py`. It should become the model
for later campaigns against CLI, web routes, tool manager, parser, and provider
runtime surfaces.

## Why This Exists

`penguin/core.py` is currently far beyond the intended architecture boundary.
It should be an orchestrator that wires subsystems together and delegates
behavior. Instead, it contains substantial business logic for:

- startup and dependency construction
- model/runtime resolution
- agent and conversation routing
- streaming session isolation and finalization
- OpenCode/TUI event translation and persistence
- RunMode streaming bridges
- action-to-tool mapping and result metadata synthesis
- checkpoint/session convenience methods
- status, diagnostics, and system information

This creates several problems:

- subtle regressions are hard to localize
- tests often need heavy mocks or `PenguinCore.__new__`
- unrelated changes collide in one file
- old compatibility paths survive because their real contract is unclear
- agents can grow the file faster than humans can preserve the mental model

The goal is not to produce a perfectly tested 6,000+ line `core.py`. The goal is
to extract tested subsystems until `core.py` is mostly construction, delegation,
and compatibility shims.

## Relationship To Existing Plans

This campaign depends on:

- `context/tasks/testing-pyramid.md`
- `context/tasks/llm-provider-contract.md`
- `context/tasks/tool-call-runtime-architecture.md`
- `context/tasks/forking-checkpoints-testing.md`
- `context/tasks/penguin_tla.md`
- `context/tasks/core-refactor-phase-5.md`
- `context/tasks/core-refactor-phase-6.md`
- `context/tasks/core-refactor-phase-7.md`
- `context/tasks/core-refactor-phase-8.md`
- `context/tasks/core-refactor-future-overkill-reliability.md`
- `context/process/blueprint.template.md` for the ITUV lifecycle

The campaign should not resurrect `context/archive/plans/core-refactor-plan.md`
verbatim. That plan is historically useful, but `core.py` has since changed
substantially and Penguin already has streaming primitives in
`penguin/llm/stream_handler.py`.

Reference upstream OpenCode at
`/Users/maximusputnam/Code/Penguin/penguin/reference/opencode` when planning
future `penguin-tui` work and when auditing OpenAI auth or related provider
handling. Treat it as a reference implementation for event, auth, provider, and
session-flow shape, not as code to copy blindly.

## Phase Sequencing Update

Phases 7 and 8 stay on the already planned path:

- **Phase 7**: continue bounded `PenguinCore` extraction slices behind
  characterized contracts.
- **Phase 8**: assault the extracted boundaries with deterministic
  random-order, property, state-machine, replay, fault-injection, and small
  mutation-test candidates.

The broader safety-critical reliability effort is deferred to future phases.
Those future phases can add overkill testing, formal models, observability,
metrics, replay pipelines, and production-grade assurance after the current
refactor has made subsystem ownership clear.

## ITUV Gate

Every ACBRA slice must pass ITUV before it is considered complete:

- **IMPLEMENT**: code changes are scoped to the selected slice and extraction
  target.
- **TEST**: relevant unit, property, state-machine, contract, and integration
  tests pass.
- **USE**: at least one real local usage recipe exercises the slice through the
  normal Penguin surface.
- **VERIFY**: acceptance criteria and invariants are checked against test and
  usage artifacts.

For `core.py`, "USE" should avoid live providers by default. Prefer fake
providers, in-process web clients, local session stores, and deterministic tool
fixtures.

## Current Baseline To Capture

Before refactoring, record:

- `wc -l penguin/core.py`
- `rg -n "^(class|def|async def)|^    (class|def|async def)" penguin/core.py`
- current test status for core-related tests
- package-source test artifacts under `penguin/`
- known dirty worktree files so unrelated user changes are not reverted
- coverage for the selected slice, not only global coverage

Known local signal from onboarding:

- `penguin/core.py` is around 6,458 lines.
- `tests/test_core_tool_mapping.py` and
  `tests/test_core_opencode_stream_fallback.py` pass in the local venv.
- `tests/test_core_model_management.py` currently has stale expectations around
  `max_tokens` versus `max_output_tokens` and changed model-resolution behavior.

## Core Invariants

These invariants matter more than raw line coverage.

### Process And Delegation

- `PenguinCore.process(...)` delegates reasoning to `Engine` when available.
- legacy fallback paths are explicit and covered if they remain.
- user messages, assistant messages, tool results, and token updates are
  persisted or emitted exactly once per intended lifecycle event.
- cancellation returns an explicit aborted result and releases active session
  bookkeeping.
- exceptions emit structured UI errors without corrupting conversation state.

### Model And Runtime Resolution

- runtime model IDs are canonical for their adapter edge.
- OpenAI/Anthropic native adapters receive provider-local model IDs.
- OpenRouter IDs do not gain duplicate `openrouter/` prefixes.
- unknown unqualified model IDs fail clearly.
- `max_output_tokens` and `max_context_window_tokens` remain semantically
  distinct.
- safe context window clamping is deterministic.
- model switches propagate to `APIClient`, `ConversationManager`,
  `ContextWindowManager`, and `Engine`.
- request-scoped runtime resolution does not mutate global core state.

### Streaming And Session Isolation

- stream chunks are scoped by session and agent.
- concurrent sessions cannot leak chunks into each other.
- finalization persists to the target session store, not a stale shared current
  session.
- empty streams produce explicit diagnostics or placeholders only where policy
  requires it.
- aborting a stream does not persist incomplete assistant dialog.
- final stream events include correct `session_id`, `conversation_id`, and
  `agent_id`.

### OpenCode/TUI Bridge

- OpenCode part events preserve message, part, session, and model metadata.
- final content fallback works when no delta was emitted.
- usage metadata is applied to the correct assistant message.
- session status events remain scoped and do not bleed across clients.
- TUI-specific shaping stays outside core where possible.

### Action-To-Tool Mapping

- legacy action names map to canonical tool names and inputs deterministically.
- edit/write/read/search/todo/question/subagent mappings preserve metadata
  needed by the UI and transcript.
- malformed action payloads fail closed into explicit empty/error metadata,
  not ambiguous partial commands.
- diffs are normalized consistently.
- failed mutating actions preserve attempted diff metadata when available.

### Checkpoints And Sessions

- checkpoint, rollback, branch, fork, revert, and unrevert operations preserve
  lineage and do not mutate source sessions accidentally.
- session IDs do not bleed across agents, forks, or execution contexts.
- exposed session payloads match TUI/API contracts.

## Slice Plan

Work in small campaigns. Do not refactor across multiple slices in one PR unless
the tests already prove the shared contract.

### Slice 1: Model And Runtime Resolution

Candidate extraction target:

- `penguin/core/model_runtime.py`

Move or wrap:

- `_build_model_config_for_model`
- `_canonicalize_runtime_model_id`
- `_resolve_model_provider`
- request-scoped runtime resolution helpers where practical

Required tests:

- unit tests for provider inference and canonicalization
- contract tests for `list_available_models()` and `get_current_model()` payloads
- property tests over qualified model IDs and provider prefixes
- mutation candidate: provider inference branch decisions
- integration test proving `load_model()` propagates config to API client,
  conversation manager, context window, and engine

First task:

- repair or rewrite stale `tests/test_core_model_management.py` so the canonical
  keys are `max_output_tokens` and `max_context_window_tokens`

### Slice 2: Action-To-Tool Mapping

Candidate extraction target:

- `penguin/core/action_mapping.py`

Move or wrap:

- `_map_action_to_tool`
- `_map_action_result_metadata`
- payload normalization helpers used only by mapping

Required tests:

- table-driven unit tests for every supported action alias
- property tests for malformed string/dict payloads
- contract tests for UI/transcript metadata shape
- fuzz harness for action payload parsing if this remains a compatibility path

Acceptance:

- `PenguinCore` delegates mapping to the extracted module.
- existing `tests/test_core_tool_mapping.py` passes with only import/name
  updates if needed.

### Slice 3: Streaming And Finalization

Candidate extraction target:

- `penguin/core/streaming_bridge.py`

Move or wrap:

- `_resolve_stream_scope_id`
- `_handle_stream_chunk`
- `finalize_streaming_message`
- `abort_streaming_message`
- `_persist_finalized_message`
- RunMode stream callback bridge helpers if they remain core-owned

Required tests:

- unit tests for stream scope resolution
- state-machine tests for inactive -> active -> finalizing -> inactive
- concurrency tests for two sessions and two agents streaming at once
- integration tests with fake session stores
- fault-injection tests for cancellation and abort
- regression tests from `tests/test_core_opencode_stream_fallback.py`

Acceptance:

- no stream finalization path reads a stale shared current session when an
  explicit session scope exists.
- abort paths emit scoped final/abort events and persist no dialog.

### Slice 4: OpenCode/TUI Event Bridge

Candidate extraction target:

- `penguin/core/opencode_bridge.py`

Move or wrap:

- `_get_tui_adapter`
- `_on_tui_stream_chunk`
- `_on_tui_action`
- `_on_tui_action_result`
- `_persist_opencode_event`
- usage metadata helpers

Required tests:

- contract tests for emitted OpenCode event shapes
- hermetic integration tests through the web/SSE service layer
- replay fixtures from minimized web-server logs
- property tests for missing optional fields where schema allows

Acceptance:

- core owns subscription/wiring only.
- bridge owns OpenCode-specific event shaping and persistence.

### Slice 5: Process Orchestration Facade

Candidate extraction target:

- likely keep the public method on `PenguinCore`, but extract support objects
  for request bookkeeping and process lifecycle.

Move or wrap:

- active request/session bookkeeping
- user message event emission
- assistant final event emission
- token usage update/application
- cancellation cleanup

Required tests:

- hermetic integration tests with fake `Engine`
- fault-injection tests for engine errors and cancellation
- session status busy/idle lifecycle tests
- exact-once event emission tests

Acceptance:

- `process(...)` becomes readable orchestration, not inline policy.

### Slice 6: Startup And Composition

Candidate extraction target:

- `penguin/core/factory.py` or explicit builder functions

Move or wrap:

- `PenguinCore.create(...)` startup phases
- progress reporting
- model config construction from loaded config
- ToolManager/APIClient/ConversationManager construction policy

Required tests:

- unit tests for config-to-model-config conversion
- integration tests for `fast_startup`
- no direct `print()` debugging in startup path
- startup failure diagnostics preserve original exception context

Acceptance:

- `create(...)` is a small factory method or delegates to a factory module.

## Testing Pyramid For Each Slice

### Layer 0: Static Hygiene

Commands:

```bash
.venv/bin/python -m compileall penguin
ruff check penguin tests
ruff format --check penguin tests
```

Use `uv run` equivalents when `uv` is available.

### Layer 1: Unit

Target pure helpers first. Unit tests should not construct a real
`PenguinCore` unless the behavior genuinely requires it.

### Layer 2: Property

Use Hypothesis for:

- model ID canonicalization
- action payload coercion
- stream scope keys
- event metadata defaults
- session ID and agent ID combinations

### Layer 3: State Machine

Use state-machine tests for:

- streaming lifecycle
- request busy/idle bookkeeping
- cancellation/abort/finalize behavior
- checkpoint/fork/revert lifecycle where core remains involved

### Layer 4: Contract

Freeze:

- public `PenguinCore` method return shapes
- OpenCode event payloads
- web/TUI-facing session metadata
- model runtime payloads
- action metadata shape

### Layer 5: Hermetic Integration

Use:

- fake `Engine`
- fake `APIClient`
- fake provider adapters
- fake session stores
- FastAPI/TestClient for route-visible behavior
- temporary workspaces

No test in this layer should require a real provider or a running server on a
fixed port.

### Layer 6: E2E Smoke

Keep small:

- CLI/help starts
- web server starts on configured `HOST` / `PORT`
- one fake-provider chat flow through web API
- one scoped streaming session flow

### Layer 7: Live Smoke

Opt-in only. Live provider checks must never be required for the default suite.

### Layer 8: Fuzz

Start with:

- action payloads
- patch/edit payloads still routed through core mapping
- OpenCode event payloads
- malformed session metadata

### Layer 9: Mutation

Start only after extraction, on small modules:

- model provider inference
- action mapping decisions
- stream scope resolution
- request lifecycle cleanup

### Layer 10: Formal

Candidates after extraction:

- stream lifecycle
- request busy/idle reference counting
- session/fork/revert lineage

Formal specs should mirror implementation tests; they should not become a
parallel, disconnected model.

## Default Verification Commands

Preferred when `uv` is available:

```bash
uv run pytest tests -q -m "not live and not e2e and not slow"
uv run pytest tests/test_core_tool_mapping.py tests/test_core_opencode_stream_fallback.py -q
uv run pytest tests/test_core_model_management.py -q
```

Local venv fallback:

```bash
.venv/bin/python -m pytest tests -q -m "not live and not e2e and not slow"
.venv/bin/python -m pytest tests/test_core_tool_mapping.py tests/test_core_opencode_stream_fallback.py -q
.venv/bin/python -m pytest tests/test_core_model_management.py -q
```

Coverage for this campaign should be reported by extracted slice, not only by
global package percentage.

## ACBRA Checklist

For each slice:

- [ ] Audit responsibilities and call sites.
- [ ] Audit current tests and known failures.
- [ ] Write invariants in the slice PR/task.
- [ ] Add characterization tests before moving code.
- [ ] Add unit tests for local decisions.
- [ ] Add property tests where input space is broad.
- [ ] Add state-machine tests where lifecycle matters.
- [ ] Add contract tests for public/cross-module behavior.
- [ ] Refactor behind passing tests.
- [ ] Run targeted tests and default offline suite.
- [ ] Add fault-injection, fuzz, or mutation checks if the slice is critical.
- [ ] Record residual risks and next slice.

## Definition Of Done

Short term:

- stale core model-management tests are repaired or retired intentionally
- core-related default tests pass
- first extraction slice lands with characterization and pyramid coverage

Medium term:

- model/runtime, action mapping, streaming, and OpenCode bridge logic are out of
  `core.py`
- `core.py` no longer contains large compatibility mapping tables or event
  shaping logic
- coverage reports are available per extracted core subsystem

Long term:

- `core.py` is small enough to audit as a composition root
- critical extracted modules have property/state-machine tests
- mutation testing is useful on selected deterministic modules
- future agent work can invoke ACBRA as a repeatable protocol rather than an
  ad hoc refactor plan

## Open Questions

- Should the general ACBRA protocol live in `context/ACBRA.md` after this first
  campaign proves the shape?
- Should ITUV task records include an explicit `assurance_layer` field for the
  testing pyramid layer touched by a task?
- Should extracted core modules live under `penguin/core/` as a package, or use
  flat modules such as `penguin/core_runtime.py` to avoid import churn?
- Which slice should be first after model-management tests are made believable:
  action mapping or streaming?
