# CLI ACBRA Testing And Refactor Campaign

## Purpose

Turn `penguin/cli/cli.py` from a high-risk startup, command, and interactive
shell god file into a small composition and registration layer by applying the
same repeatable ACBRA loop used for the core-runtime campaign:

1. **Audit** current behavior, responsibilities, invariants, and failure modes.
2. **Characterize** behavior that must not regress.
3. **Build** the testing pyramid for the selected CLI slice.
4. **Refactor** behind the new test boundary.
5. **Assault** the extracted boundary with property, fault-injection, ordering,
   and replay checks where they are useful.

This document is intentionally scoped to the Python CLI implementation under
`penguin/cli/`, with `penguin/cli/cli.py` as the primary decomposition target.
It is not a CLI redesign plan and it is not permission to rewrite the file in
one pass.

## Why This Exists

`penguin/cli/cli.py` is currently far beyond the intended boundary for a CLI
entrypoint. It owns or coordinates:

- import timing and startup diagnostics
- configuration compatibility and model/runtime projection
- global core construction
- workspace and environment normalization
- direct-prompt, interactive, session, and RunMode dispatch
- Typer command registration for config, permissions, skills, MCP, agents,
  projects, tasks, coordination, profiling, and chat
- the legacy interactive `PenguinCLI` shell
- display, streaming, reasoning, interrupt, and input behavior

This creates predictable failure modes:

- model and configuration intent is reconstructed differently by different
  entry paths
- a model override can accidentally inherit capabilities from the configured
  source model
- explicit and inferred configuration values are difficult to distinguish
  after projection through dictionaries
- command behavior and command registration are too coupled to test cleanly
- fixes in one surface can destabilize direct prompt, interactive, RunMode, or
  command-group startup
- review-driven local patches reinforce the god file instead of removing the
  source of the defects

The goal is not to make a perfectly polished 5,000-line CLI. The goal is to
extract tested services until `cli.py` primarily registers commands, parses
top-level options, and delegates to focused startup and command modules.

## Relationship To Existing Plans

This campaign depends on:

- `context/tasks/testing-pyramid.md`
- `context/tasks/cli-refactor-and-bootstrap-audit.md`
- `context/tasks/cli-surface-audit.md`
- `context/tasks/project-bootstrap-workflow.md`
- `context/process/blueprint.template.md` for the ITUV lifecycle

Historical input:

- `context/archive/plans/refactoring_python_cli_plan.md`
  - useful for prior display, streaming, event, class, and command extraction
    ideas
  - stale line counts and assumptions must be re-audited before use
- `context/archive/plans/penguin_cli_refactor_plan.md`
  - primarily concerns the retired TypeScript/Ink CLI and should not drive this
    Python campaign

The user-facing follow-up is:

- `context/tasks/cli-interface-ergonomics-plan.md`

That ergonomics plan should follow structural stabilization rather than drive
the decomposition. Command naming, discoverability, defaults, and workflow
polish are easier and safer once startup, configuration, rendering, and command
execution have explicit owners. Correctness blockers may still be fixed before
the refactor, but broad UX work should not be mixed into extraction PRs.

## Relationship To The Core ACBRA Campaign

This campaign follows the protocol established by
`context/tasks/core-acbra-testing-refactor.md`:

- characterize before moving behavior
- extract one responsibility at a time
- preserve compatibility at the old public boundary
- use deterministic fake dependencies before live-provider checks
- report coverage and assurance by extracted slice, not only by global test
  percentage

The CLI has a different risk profile from `PenguinCore`. Its highest risks are
startup ordering, environment mutation, configuration provenance, command
dispatch, terminal state, and duplicated user-facing behavior.

## ITUV Gate

Every ACBRA slice must pass ITUV before it is complete:

- **IMPLEMENT**: changes are limited to one selected responsibility and its
  delegation boundary.
- **TEST**: characterization, unit, contract, and integration tests for that
  responsibility pass.
- **USE**: at least one real local CLI recipe exercises the normal installed or
  `uv run` surface.
- **VERIFY**: acceptance criteria, preserved behavior, and residual risks are
  recorded from test and usage evidence.

Live providers are not the default proof of correctness. Prefer monkeypatched
configuration loaders, fake cores, fake provider clients, Typer test runners,
temporary workspaces, and deterministic event streams. A live provider smoke
may supplement the evidence when the slice specifically concerns provider
startup, but it must not replace hermetic tests.

## Current Baseline To Capture

Before the first extraction PR, record:

```bash
wc -l penguin/cli/cli.py
rg -n "^def |^async def |^class |^    def |^    async def " penguin/cli/cli.py
git status --short
uv run pytest -q \
  tests/test_cli_entrypoint_dispatcher.py \
  tests/test_cli_integration.py \
  tests/test_cli_surface_audit_regressions.py \
  tests/cli
```

Known baseline on July 9, 2026:

- `penguin/cli/cli.py` is 5,213 lines.
- model/reasoning projection helpers live directly in `cli.py` around the
  global initialization path.
- `_initialize_core_components_globally(...)` remains a high-risk composition
  function used by many commands.
- the interactive `PenguinCLI` class begins late in the file and still owns
  terminal/display behavior despite existing manager classes.
- CLI-focused tests exist across `tests/cli/`,
  `tests/test_cli_entrypoint_dispatcher.py`, `tests/test_cli_integration.py`,
  and `tests/test_cli_surface_audit_regressions.py`.

The baseline must also list known dirty worktree files so unrelated user work
is not reverted or committed during the campaign.

## CLI Invariants

These invariants matter more than raw line reduction.

### Startup And Composition

- import-time behavior remains lazy enough that `penguin --help` is fast and
  does not initialize providers unnecessarily
- root, workspace, and environment normalization happen once in a documented
  order
- configuration is loaded once per intended startup lifecycle
- global compatibility state is assigned only after construction succeeds
- partial startup failure preserves the original exception and does not leave
  misleading half-initialized globals
- direct prompt, interactive chat, RunMode, and command groups resolve the same
  target runtime semantics unless their contracts intentionally differ

### Model And Reasoning Configuration

- the target model is resolved before model-derived capabilities are inferred
- `--model` never inherits capabilities from the configured source model
- explicit user choices outrank provider defaults and inferred values
- explicit `false`, explicit effort, and explicit token budget remain distinct
  from unset values
- explicit token-budget provenance is independent of reasoning-enabled
  provenance
- native/OpenRouter/Anthropic reasoning styles retain their correct request
  configuration
- configuration projection and reconstruction round-trip without silently
  changing intent

### Workspace And Project Semantics

- execution root, Penguin workspace, and project workspace remain distinct
- command options either work as documented or fail clearly
- project/task selection is deterministic and ambiguous names fail closed
- project and task commands delegate business logic rather than duplicating it
  in command bodies

### Command Dispatch

- Typer decorators and public command names remain stable during extraction
  unless a separate ergonomics PR intentionally changes them
- sync command wrappers invoke their async implementation exactly once
- command failures map to stable exit codes and actionable messages
- JSON or machine-readable output remains free of incidental Rich output
- command registration does not import or initialize unrelated heavy systems

### Interactive Shell And Streaming

- streamed content, reasoning, tool calls, and tool results remain ordered
- interrupt and cancellation restore terminal state and release active work
- empty or tool-only turns do not create misleading blank assistant output
- event handling and rendering do not persist or mutate business state
- session selection and continuation preserve the intended workspace and
  conversation scope

### Compatibility

- `penguin`, `penguin --help`, `penguin .`, direct-prompt modes, and supported
  command groups keep their current external contracts
- extracted modules do not introduce import cycles or package-source tests
- CLI code remains a consumer of core/web/project services, not a second
  implementation of their business rules

## Slice Plan

Work in bounded campaigns. Do not combine multiple high-risk slices merely to
reduce the line count faster.

### Slice 1: Model Startup And Configuration Projection

Candidate extraction target:

- `penguin/cli/model_runtime.py`

Move or replace:

- `_project_reasoning_config`
- `_resolve_cli_reasoning_config`
- model dictionary normalization inside
  `_initialize_core_components_globally(...)`
- target-model selection and model-override handling
- construction of the final `ModelConfig`

The extracted API should accept explicit inputs and return a complete
`ModelConfig` or a typed construction result. It must not depend on private
`ModelConfig` flags from the CLI boundary. If configuration provenance is part
of the contract, represent it with an explicit input schema or first-class
factory API.

Required characterization matrix:

- same model versus `--model` override
- reasoning-capable versus non-reasoning target
- `reasoning_enabled`: true / false / unset
- effort: valid / invalid / unset
- max-token budget: explicit / inferred / unset
- source and target across OpenAI, Anthropic, and OpenRouter styles
- qualified and unqualified model IDs
- static configuration versus provider-catalog metadata

Known regressions to capture before extraction:

- configured `gpt-4o` plus `--model gpt-5.6-sol` must recompute GPT-5.6
  capabilities instead of inheriting `supports_reasoning=False`
- configured GPT-5.6 plus `--model gpt-4o` must not carry GPT-5.6 capabilities
  into the target
- an explicit `reasoning_max_tokens: 8000` must not become an inferred 2000
  token budget merely because `enabled` was omitted

Acceptance:

- `cli.py` does not project or reconstruct reasoning/model capability fields
- target-model resolution happens before capability inference
- a table-driven test matrix proves explicit and inferred configuration
  precedence
- `_initialize_core_components_globally(...)` delegates model construction to
  the extracted module

### Slice 2: Startup And Dependency Composition

Candidate extraction target:

- `penguin/cli/bootstrap.py`

Move or wrap:

- `_initialize_core_components_globally(...)`
- config loading and compatibility conversion
- workspace-aware `PenguinCore` construction
- global compatibility assignment
- startup progress and failure reporting boundaries

Required tests:

- successful construction with fake config/core factories
- config-load failure, provider failure, and partial-construction cleanup
- repeated initialization behavior
- workspace override and model override propagation
- direct prompt and interactive startup parity
- no provider initialization for `--help` and other metadata-only commands

Acceptance:

- `cli.py` delegates startup to a focused bootstrap service
- bootstrap returns an explicit result instead of mutating many globals during
  intermediate phases
- compatibility globals are assigned in one small adapter after success

### Slice 3: Environment, Root, And Workspace Normalization

Candidate extraction target:

- `penguin/cli/environment.py`

Move or wrap:

- `_set_cli_workspace_path`
- `_preconfigure_cli_environment`
- execution-root normalization
- environment variable projection used only by CLI startup

Required tests:

- relative, absolute, missing, and symlinked paths
- explicit workspace versus current-directory defaults
- repeated calls and pre-existing environment variables
- project workspace remains distinct from execution root
- platform-specific path behavior where relevant

Acceptance:

- path/environment mutation is centralized and documented
- tests prove idempotence or explicitly document non-idempotent behavior
- command implementations no longer improvise workspace normalization

### Slice 4: Command Execution Services

Candidate extraction targets:

- `penguin/cli/commands/project.py`
- `penguin/cli/commands/task.py`
- `penguin/cli/commands/agent.py`
- `penguin/cli/commands/config.py`
- additional domain modules only when their boundaries are proven

Keep Typer registration thin. Extract command execution functions that accept
typed inputs and services, then return structured outcomes for rendering.

Required tests:

- public command names/options remain registered
- command services are unit tested without Typer or terminal state
- Typer contract tests cover parsing, exit codes, and output projection
- ambiguous selectors and service failures remain explicit

Acceptance:

- command bodies in `cli.py` are registration/delegation only
- project/task/agent business logic is not duplicated between CLI and backend
  services
- command output is rendered from structured results

### Slice 5: RunMode And Direct-Prompt Dispatch

Candidate extraction target:

- `penguin/cli/run_dispatch.py`

Move or wrap:

- `_run_penguin_direct_prompt`
- `_handle_run_mode`
- `_handle_session_management`
- top-level mode-selection decisions from `main_entry(...)`

Required tests:

- precedence among direct prompt, session management, RunMode, and interactive
  mode
- `--run`, `--247`, and `--continuous` dispatch contracts
- cancellation, non-terminal outcomes, and structured output
- invalid option combinations fail before core execution

Acceptance:

- `main_entry(...)` parses options and delegates to one dispatch policy
- RunMode lifecycle truth remains owned by runtime services
- CLI does not reinterpret pending-review, clarification, or blocked outcomes

### Slice 6: Rendering And Output Policy

Candidate extraction targets:

- existing `penguin/cli/renderer.py` and manager classes where suitable
- a focused output-policy adapter for plain, Rich, and JSON output

Move or consolidate:

- duplicated message and status rendering
- command result formatting
- reasoning and code-block display helpers
- machine-readable output policy

Required tests:

- golden or snapshot-like tests for stable structured fragments
- ANSI/no-ANSI behavior
- JSON output contains no incidental terminal decoration
- errors and warnings use consistent streams and exit behavior

Acceptance:

- rendering consumes outcomes and events; it does not perform domain actions
- duplicate formatting logic is removed only after parity tests pass
- interactive and command output share helpers where their contracts match

### Slice 7: Interactive Shell And Streaming Lifecycle

Candidate extraction targets:

- `penguin/cli/interactive.py`
- existing `DisplayManager`, `StreamingManager`, `SessionManager`, and
  `EventManager` boundaries after re-audit

Move or delegate:

- `PenguinCLI.chat_loop`
- interrupt and cancellation handling
- streaming finalization and terminal restoration
- session continuation and interactive input coordination
- residual display methods that belong to existing managers

Required tests:

- deterministic event-stream replay
- cancellation during content, reasoning, and tool execution
- tool-only and empty-turn finalization
- session switch/continue behavior
- terminal state cleanup after exceptions
- fault injection from renderer, event manager, and core process calls

Acceptance:

- the interactive shell is a coordinator over focused managers
- terminal state has explicit lifecycle ownership
- the legacy `PenguinCLI` class is small enough to audit or replaced by a
  focused interactive application object

### Slice 8: Registration And Compatibility Facade

Candidate end state:

- `penguin/cli/cli.py` contains Typer app/group registration, compatibility
  imports, and small delegation wrappers

Required tests:

- package entry points resolve
- `penguin --help` and command-group help work from an installed wheel
- public command names, options, and aliases match the frozen contract
- deprecated compatibility shims warn or delegate intentionally

Acceptance:

- `cli.py` is no longer the owner of configuration, runtime startup, rendering,
  or domain command policy
- file size is a consequence of clean ownership, not the primary metric

## Testing Pyramid For Each Slice

### Layer 0: Static Hygiene

```bash
uv run python -m compileall penguin/cli
uv run ruff check <touched files>
uv run ruff format --check <touched files>
git diff --check
```

Broader legacy lint debt should be reported, not silently mixed into a focused
extraction PR.

### Layer 1: Unit

Target pure projection, parsing, selection, rendering, and dispatch helpers.
Avoid constructing a real `PenguinCore` for decisions that do not require it.

### Layer 2: Property

Use Hypothesis where input combinations are broad:

- model/provider IDs and overrides
- tri-state reasoning fields and explicit-value precedence
- root/workspace path normalization
- command selector and status normalization
- output mode combinations

### Layer 3: State Machine

Use state-machine tests for:

- startup: uninitialized -> initializing -> ready/failed
- interactive lifecycle: idle -> requesting -> streaming/tooling -> idle
- interrupt/cancel/finalize transitions
- session select/switch/continue behavior

### Layer 4: Contract

Freeze:

- command names, arguments, options, and exit codes
- startup/model projection semantics
- structured command outcomes
- JSON output shapes
- event-to-terminal rendering contracts where public

### Layer 5: Hermetic Integration

Use:

- `typer.testing.CliRunner`
- fake config loaders and core factories
- fake providers and event buses
- temporary workspaces and credential stores
- deterministic async command services

No test in this layer should require a fixed port, real OAuth credentials, or a
live model.

### Layer 6: Installed-Artifact Smoke

Build and install the wheel into a clean environment, then verify:

```bash
penguin --help
penguin config --help
penguin project --help
penguin task --help
```

Add the narrowest useful direct-prompt or fake-provider recipe for the slice.

### Layer 7: Live Smoke

Opt-in only. Appropriate candidates:

- one direct prompt through a configured provider
- one interactive streamed turn
- one model override when the slice changes provider/model startup

Live checks supplement deterministic coverage and should record the exact
model, provider, date, and result.

### Layer 8: Fuzz And Fault Injection

Candidates:

- malformed configuration dictionaries
- command argument combinations
- terminal interruption timing
- partial startup failures
- event ordering and missing optional fields

### Layer 9: Mutation

Use only after extraction on small deterministic modules:

- model override precedence
- explicit/unset configuration decisions
- command dispatch precedence
- workspace selection and ambiguous identifier branches

## Default Verification Commands

Start targeted, then broaden:

```bash
uv run pytest -q tests/cli
uv run pytest -q \
  tests/test_cli_entrypoint_dispatcher.py \
  tests/test_cli_integration.py \
  tests/test_cli_surface_audit_regressions.py
uv run pytest -q tests -m "not live and not e2e and not slow"
```

For startup or packaging slices, also run the applicable release-runbook smoke
checks from `context/process/release-runbook.md`.

## PR Discipline

- one extraction slice per PR unless a shared characterization boundary already
  proves the combined move
- characterize first; do not move and redesign behavior simultaneously
- preserve Typer decorators until command execution is safely behind services
- avoid drive-by formatting of the 5,000-line file
- do not add new business logic to `cli.py` during the campaign unless it is a
  temporary compatibility shim with a deletion task
- every PR records lines moved, lines deleted, tests added, and residual risks
- commit unrelated user files neither accidentally nor “for convenience”

## ACBRA Checklist

For each slice:

- [ ] Audit responsibilities, call sites, globals, and side effects.
- [ ] Capture the current command/startup contract with characterization tests.
- [ ] Write invariants and explicit non-goals for the slice.
- [ ] Add unit tests for local decisions.
- [ ] Add property tests where configuration/input combinations are broad.
- [ ] Add state-machine tests where lifecycle or terminal state matters.
- [ ] Add contract tests for public command and output behavior.
- [ ] Refactor behind passing tests.
- [ ] Run the normal CLI recipe through `uv run` or an installed artifact.
- [ ] Run targeted and broader offline suites.
- [ ] Add fault injection or mutation checks if the extracted boundary is
      critical and deterministic.
- [ ] Record residual risks and the next slice.

## Definition Of Done

Short term:

- model startup/projection behavior is extracted and characterized
- model overrides recompute capabilities from the target model
- explicit reasoning effort and token-budget provenance survive startup
- CLI correctness fixes stop depending on private `ModelConfig` flags

Medium term:

- startup/composition, environment normalization, command execution, dispatch,
  and rendering have focused owners
- command bodies are thin registration/delegation wrappers
- interactive lifecycle behavior has replay and fault-injection coverage
- CLI-focused coverage reports are available per extracted subsystem

Long term:

- `penguin/cli/cli.py` is small enough to audit as an entrypoint and
  compatibility facade
- adding or changing a command no longer requires navigating unrelated model,
  streaming, and interactive-shell logic
- the ergonomics plan can proceed on stable service boundaries rather than
  adding more policy to the god file
- future agents can apply the CLI ACBRA protocol as a repeatable campaign rather
  than restarting decomposition from an archived plan

## Follow-Up: CLI Ergonomics

After the relevant structural boundaries are stable, resume
`context/tasks/cli-interface-ergonomics-plan.md` for:

- clearer command semantics and discoverability
- improved project/workspace/root UX
- higher-level project bootstrap workflows
- command naming and default-policy cleanup
- CLI/web/library workflow alignment

Do not treat this ordering as a blanket blocker on user-facing fixes. Fix
truthfulness and release blockers when they occur. The rule is narrower:
**do not use ergonomics work as justification to add substantial new policy to
`cli.py` while its responsibilities are being extracted.**

## Open Questions

- Should model/runtime startup extraction live under `penguin/cli/` or reuse a
  provider-neutral factory under `penguin/core_runtime/`?
- Should explicit configuration provenance become a public `ModelConfig`
  construction contract instead of CLI-owned projection metadata?
- Which legacy interactive `PenguinCLI` responsibilities still belong in the
  Python CLI now that Penguin TUI is the primary interactive surface?
- Which command groups should remain compatibility-only after the ergonomics
  campaign?
- What maximum size or dependency-count guard would prevent `cli.py` from
  becoming a god file again without encouraging artificial module splitting?
