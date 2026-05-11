# Penguin Testing Pyramid And Assurance Plan

## Objective

- Build a trustworthy, layered testing methodology for Penguin.
- Keep AI-assisted development velocity while reducing model drift between what
  contributors believe the code does and what it actually does.
- Borrow SQLite's safety-critical testing philosophy without trying to apply
  SQLite's exact 100% MC/DC standard uniformly across a fast-moving AI agent.
- Aggressively encode Penguin's critical invariants so future agent-generated
  changes are forced through executable checks.

## Why This Exists

Penguin is now evolving too quickly for one person to keep a complete mental
model of the codebase in sync with reality.

That is especially risky because Penguin is itself an AI coding agent. The same
AI-assisted development loop that makes large changes possible also increases
the chance of:

- stale assumptions
- hidden cross-module coupling
- provider-specific behavior leaking across boundaries
- test failures becoming normalized noise
- regressions in stateful flows that are hard to see manually
- tool, permission, session, or checkpoint behavior drifting from intent

The answer is not just "more tests." The answer is a procedural assurance
methodology: clean suite boundaries, explicit invariants, deterministic fake
providers, property tests, state-machine tests, fuzzing, mutation testing, and
formal verification where the model is small enough to be useful.

## Inspiration: SQLite

SQLite is the reference point for serious software assurance:

- private TH3 harness
- 100% branch coverage over core SQLite
- 100% MC/DC over core SQLite
- extensive fuzzing, crash tests, OOM tests, I/O failure tests, and mutation
  testing
- aviation-adjacent motivation through DO-178B-style validation needs

Penguin should copy the mindset, not the exact shape.

SQLite can justify maintaining 100% MC/DC across a compact C database engine
because it is infrastructure used everywhere and stores durable state. Penguin
has similarly high leverage, but the system surface is broader and more
dynamic: LLM providers, tool execution, web/TUI interfaces, sessions, project
orchestration, and multi-agent flows.

So Penguin's first target should be:

- 100% coverage of critical invariants
- clean and trusted default suites
- increasing package coverage by subsystem
- formal verification for crisp state machines
- live smoke tests only where real integration value exists

## Current Baseline

Observed local package coverage for `penguin`:

```text
covered lines: 23,038
statements:     57,876
missing lines:  34,838
coverage:       39.8058% -> 40%
```

This was not a clean full-suite run.

Known blockers encountered during measurement:

- `tests/api/test_github_app_auth.py` exits during collection without GitHub App
  environment variables.
- `tests/llm/conftest.py` defines `pytest_plugins` in a non-top-level conftest,
  which current pytest rejects.
- `tests/test_agent_lifecycle.py` imports stale `SecurityConfig` from
  `penguin.agent.schema`.
- Many API and performance tests assume an external server at
  `127.0.0.1:8000`.
- The adjusted run produced a coverage total but still had many failures and
  errors.
- `penguin/llm/test1.py` is unparsable as Python source and must be removed,
  moved, or excluded from coverage.

Before coverage gates matter, the suite needs to be made believable.

## Core Principle

A flaky or ambiguous test suite is worse than no suite in an AI-assisted
codebase because it trains humans and agents to discount failures.

Default tests must be:

- deterministic
- offline
- fast enough to run often
- clearly scoped
- clear about whether a failure is unit, integration, live-provider, or
  environment-related

## Target Pyramid

### Layer 0 - Static Hygiene

Purpose: catch cheap structural problems before runtime.

Targets:

- Ruff lint and format
- import hygiene
- package boundary checks
- public API export checks
- no tests inside `penguin/` runtime packages
- no invalid Python files under package source
- gradual type checking for stable subsystems

Example commands:

```bash
ruff check .
ruff format --check .
uv run python -m compileall penguin
```

### Layer 1 - Unit Tests

Purpose: fast, deterministic checks for isolated behavior.

Good targets:

- parser helpers
- schema validation
- provider normalization
- permission predicates
- path policy helpers
- service functions
- task state helpers
- event normalization
- small tool utilities

Rules:

- no network
- no real provider credentials
- no real web server process
- no dependence on test order
- use temporary directories and deterministic fixtures

### Layer 2 - Property Tests

Purpose: test classes of inputs, not just examples.

Use Hypothesis where input space is broad or easy to get subtly wrong.

High-value targets:

- ActionXML / CodeAct parsing
- tool argument parsing
- path normalization and sandbox checks
- permission engine decisions
- patch/edit payload parsing
- diff metadata
- provider event normalization
- conversation truncation, checkpoint, and replay edge cases
- task dependency graph validation

Examples of properties:

- parsing never crashes on arbitrary text
- malformed actions fail closed
- normalized paths never escape allowed roots
- permission denials remain denials after path spelling changes
- serialized event streams can round-trip through storage

### Layer 3 - State-Machine Tests

Purpose: validate stateful workflows under many transition sequences.

High-value targets:

- task lifecycle
- run mode
- ITUV phases
- conversation append/truncate/checkpoint flows
- fork/revert/unrevert
- multi-agent delegation
- tool-call lifecycle
- provider streaming lifecycle

These should model explicit states and transitions rather than only replaying
happy-path examples.

### Layer 4 - Contract Tests

Purpose: freeze cross-module and public behavior.

Targets:

- LLM provider contract matrix
- tool runtime call/result contract
- web service response shapes
- TUI-facing session payloads
- public `penguin` package exports
- event stream grammar
- checkpoint/fork/revert semantics

Related task docs:

- `context/tasks/llm-provider-contract.md`
- `context/tasks/llm-testing-suite-overhaul.md`
- `context/tasks/tool-call-runtime-architecture.md`
- `context/tasks/forking-checkpoints-testing.md`

Provider/tool reliability work should treat this layer as the primary
confidence gate. A provider integration is not "stable" because one live
request works; it is stable when the fake-provider contract suite proves the
normal, partial, failed, retried, and replayed states.

### Layer 5 - Hermetic Integration Tests

Purpose: test assembled Penguin runtime without external services.

Rules:

- use FastAPI/TestClient or equivalent in-process clients for web tests
- use fake LLM providers
- use fake SDK clients
- use fake or temporary filesystem roots
- use fake git repos where necessary
- no assumption that a server is running on port `8000` or `9000`

High-value targets:

- API routes through service layers
- engine loop with fake providers
- tool execution through registry/runtime
- session creation and persistence
- checkpoint/fork/revert flows
- TUI-compatible backend routes

### Layer 6 - E2E Smoke Tests

Purpose: catch wiring regressions across the real user surfaces.

Keep this layer small.

Candidate smoke paths:

- CLI starts and displays help/version
- web server starts on configured `HOST` / `PORT`
- one fake-provider chat flow through web API
- one TUI-compatible session list/get/message flow
- one checkpoint or fork/revert flow

These tests should not be the place where core behavior is proven. They should
prove that the assembled product still boots and routes correctly.

### Layer 7 - Live Provider Smoke Tests

Purpose: prove credentials, transport, provider catalogs, and cheap real
requests still work.

Rules:

- opt-in only
- env-gated
- rate-limited
- cheap models only
- never required for the default local suite
- failures clearly labeled as live-provider failures

This layer should supplement, not replace, deterministic provider contract tests.

### Layer 8 - Fuzzing

Purpose: attack parser and boundary-heavy inputs.

High-value targets:

- action parser
- XML/JSON-ish action payloads
- patch/edit tools
- tool argument schema coercion
- provider streaming chunks
- malformed conversation/history files
- path inputs
- event replay payloads

Fuzz results should be minimized into regression tests.

### Layer 9 - Mutation Testing

Purpose: prove that tests catch meaningful logic changes, not just execute code.

Start only on small, critical modules where mutation results are actionable.

Initial targets:

- permission engine
- path security utilities
- task state transitions
- parser decisions
- checkpoint/fork/revert state handling
- provider contract normalization

Do not run mutation testing across the entire repo initially. It will be noisy
and expensive.

### Layer 10 - Formal Verification

Purpose: verify design-level invariants for small state machines.

Good candidates:

- permission state and fail-closed behavior
- task lifecycle / ITUV gates
- DAG task claiming under concurrent agents
- checkpoint/fork/revert invariants
- tool-call lifecycle and unresolved-call replay
- session isolation

Poor candidates:

- whole `engine.py`
- UI rendering
- LLM quality
- broad web routing
- provider SDK behavior

Related task doc:

- `context/tasks/penguin_tla.md`

## Critical Invariants

These should drive test design more than raw line coverage.

### Tool Runtime

- Tool calls have stable IDs.
- Tool calls are executed at most once unless explicitly retried.
- Tool results are associated with the correct call ID.
- Unresolved provider-native tool calls replay as explicit error/cancelled
  results, not as dangling history.
- Mutating tools are serialized until safe parallel metadata exists.
- Approval and permission checks happen in the runtime path, not just in prompts.

### Permissions And Paths

- All permission checks fail closed.
- Workspace/root policy cannot be bypassed by path spelling, symlinks, `..`, or
  shell expansion.
- Read-only tools cannot mutate state.
- Approval grants are scoped and cannot accidentally authorize unrelated tools.

### Sessions And Conversations

- Session IDs do not bleed across users, agents, projects, or forks.
- Conversation state is append-only except through explicit checkpoint, revert,
  migration, or context-window-management truncation logic.
- Penguin's CWM trims message categories by priority and recency; it does not
  summarize or compact conversation content.
- Forked sessions preserve lineage without mutating the source session.
- Revert/unrevert is deterministic and exposes correct metadata to the TUI.
- Checkpoint branches materialize as real sessions when exposed to user
  workflows.

### LLM Providers

- Provider adapters normalize onto one canonical contract.
- Streaming events preserve order, identity, finish reasons, usage, and
  reasoning metadata where available.
- Empty or malformed provider responses produce explicit diagnostics.
- Provider-specific quirks stay at adapter edges.
- Fake providers cover tool calls, empty responses, malformed chunks, duplicate
  call IDs, retries, partial failures, and CWM category-priority truncation.

### Provider And Tool Reliability Suite

This is the high-assurance suite needed for OpenAI/Codex, OpenRouter,
Anthropic, and future provider stability work. It should be deterministic and
offline by default, with live providers used only as opt-in smoke tests.

Codex reference patterns worth copying:

- fake SSE and HTTP provider servers
- captured request inspection
- incomplete-stream and retry tests
- stream-error turn-release tests
- tool replay and tool-output truncation tests
- rollout/history reconstruction tests
- permission, sandbox, shell/process, and TUI surface suites

Penguin should build equivalent Python fixtures rather than relying on real
provider traffic:

- fake Responses/OpenAI-compatible/Anthropic/OpenRouter stream emitters
- fault injection for dropped sockets, idle streams, malformed events,
  duplicate events, out-of-order events, partial tool-call deltas, and HTTP
  429/500/503 responses
- request capture helpers that assert provider-native tool adjacency,
  `previous_response_id` safety, reasoning payloads, usage metadata, and
  CWM-truncated history shape
- replay fixtures minimized from `context/bugs/*` and `misc/web-server-logs-*`

Critical provider lifecycle cases:

- terminal event with text
- terminal event with tool call
- terminal event with empty text and no tool call
- stream closes before terminal event with no output
- stream closes before terminal event after text output
- stream closes before terminal event after a tool call
- provider error before any stream event
- provider error after partial stream output
- retry succeeds
- retry is exhausted
- next user turn works after failure

Critical tool replay cases:

- completed tool call/result replay
- failed tool result replay
- cancelled tool result replay
- interrupted or dangling call repaired into explicit failure
- duplicate provider call IDs rejected or normalized
- large tool output truncated before model replay with full output persisted
- CWM category-priority truncation does not create unresolved provider-native
  tool calls

The success bar is "prove the failure modes," not only "cover the lines." For
provider/tool runtime changes, every bug fixed from logs should become a
minimal deterministic fixture.

Current provider-reliability progress:

- OpenAI/Codex OAuth has a reusable fake SSE/request-capture fixture module for
  hermetic lifecycle and request-shape tests.
- Codex tests now cover incomplete empty, partial text, partial native tool,
  mid-stream provider error, completed native tool, next-turn release, and
  CWM-truncated native tool replay shapes.

### Project And Run Mode

- Tasks cannot reach completed state without required validation gates.
- Dependency order is respected.
- A task cannot be claimed by two agents simultaneously.
- Missing evidence fails closed.
- Synthetic or continuous-mode tasks cannot escape the work graph silently.

### Web And TUI Surface

- Routes remain thin and delegate business logic into services.
- TUI-facing payloads remain stable.
- Auth-protected endpoints fail closed.
- SSE and websocket events are scoped to the correct session.

## Procedural Methodology

Apply this loop subsystem by subsystem:

1. Inventory the current tests and known failures.
2. Define the subsystem's invariants in plain language.
3. Add characterization tests for behavior that must be preserved.
4. Add focused unit tests for local decisions.
5. Add property tests for broad input spaces.
6. Add state-machine tests for lifecycle behavior.
7. Add contract tests for public or cross-module boundaries.
8. Refactor only after the harness is believable.
9. Add fuzz or mutation testing if the subsystem is critical.
10. Promote the resulting command into CI or a documented local gate.

This loop should be procedural enough that Penguin or another coding agent can
execute it repeatedly.

## Phase Plan

### Phase 1 - Make The Default Suite Trustworthy

- [ ] Fix collection blockers.
- [ ] Remove or move package-internal `test_*.py` files under `penguin/`.
- [ ] Remove or quarantine invalid source files such as `penguin/llm/test1.py`.
- [ ] Mark env-gated tests instead of exiting during collection.
- [ ] Replace server-assuming API tests with in-process clients or explicit
      integration markers.
- [ ] Add pytest markers for unit, contract, integration, e2e, live, slow,
      fuzz, mutation, and formal-adjacent tests.
- [ ] Document the default local command.

Target command:

```bash
uv run pytest tests -q -m "not live and not e2e and not slow"
```

### Phase 2 - Establish Baseline Reporting

- [ ] Add a project coverage config.
- [ ] Define omitted files intentionally rather than accidentally.
- [ ] Generate package and subsystem coverage reports.
- [ ] Track coverage by subsystem instead of relying only on one global number.
- [ ] Add an initial non-blocking coverage report in CI.

Target command:

```bash
uv run pytest tests -q --cov=penguin --cov-report=term-missing
```

### Phase 3 - Protect Critical Invariants

- [ ] Permission/path policy invariant suite.
- [ ] Tool-call lifecycle invariant suite.
- [ ] Provider fake-contract suite.
- [ ] Provider/tool reliability suite covering incomplete streams, retries,
      turn release, native tool replay, and CWM category-priority truncation.
- [ ] Session/fork/revert/checkpoint invariant suite.
- [ ] Project/task lifecycle invariant suite.
- [ ] Web/TUI payload contract suite.

### Phase 4 - Add Property And State-Machine Testing

- [ ] Hypothesis tests for parser inputs.
- [ ] Hypothesis tests for path policy.
- [ ] Hypothesis tests for tool argument coercion.
- [ ] State-machine tests for tasks/run mode.
- [ ] State-machine tests for session fork/revert/checkpoint.
- [ ] State-machine tests for tool-call lifecycle.

### Phase 5 - Add Fuzz And Mutation Gates

- [ ] Add fuzz harnesses for parser and patch/edit surfaces.
- [ ] Convert fuzz discoveries into regression tests.
- [ ] Add mutation testing for permission/path policy.
- [ ] Add mutation testing for parser decisions.
- [ ] Add mutation testing for task state transitions.
- [ ] Keep mutation jobs opt-in or scheduled until they are cheap enough.

### Phase 6 - Formal Verification For Small State Machines

- [ ] Choose one first TLA+ target from `context/tasks/penguin_tla.md`.
- [ ] Keep the spec small and directly mapped to implementation.
- [ ] Encode invariants before implementation changes.
- [ ] Add implementation tests that mirror the formal spec's key traces.
- [ ] Treat formal specs as design verification, not as pytest replacement.

### Phase 7 - CI And Agent Workflow Enforcement

- [ ] Define required checks for normal PRs.
- [ ] Define expanded checks for high-risk subsystems.
- [ ] Add a testing checklist to agent task templates.
- [ ] Require agents to state which test layer they changed or exercised.
- [ ] Add coverage/invariant deltas to PR summaries where practical.

## Suggested Markers

```ini
unit: isolated deterministic tests
contract: public or cross-module behavioral contracts
integration: local hermetic integration tests
e2e: assembled product smoke tests
live: real provider/network tests
slow: too slow for the default loop
fuzz: fuzz/property-discovery tests
mutation: mutation testing entrypoints
formal: implementation traces derived from formal specs
```

Default local development should run `unit`, `contract`, and fast hermetic
integration tests.

Live, E2E, fuzz, mutation, and formal model-checking jobs should be explicit.

## Concrete First PR Candidates

1. Fix pytest collection blockers.
   - Replace import-time `sys.exit()` in GitHub App tests with proper skip/mark.
   - Move `tests/llm` plugin declaration to a top-level conftest or remove it.
   - Fix or delete stale `SecurityConfig` import test.

2. Clean package-source test artifacts.
   - Move `penguin/llm/test_*.py` and similar runtime-package tests into
     `tests/` or `misc/tests/`.
   - Remove or quarantine invalid Python files.

3. Split API tests.
   - Unit/service tests use in-process clients.
   - Server-required tests get an explicit marker and documented startup path.

4. Add pytest marker taxonomy.
   - Register markers in `pyproject.toml`.
   - Update docs with default and expanded commands.

5. Add the first invariant suite.
   - Recommended first target: permission/path policy.
   - Reason: small, high-risk, deterministic, and a good mutation-testing
     candidate.

## Success Criteria

Short term:

- `pytest` collection is clean.
- Default offline suite passes.
- Coverage report runs without special manual exclusions.
- Test failures clearly identify their layer.

Medium term:

- Critical subsystems have explicit invariant suites.
- Fake providers cover normal and pathological model behavior.
- Property tests protect parser/path/tool boundaries.
- Coverage improves by subsystem with meaningful gates.

Long term:

- Penguin has a repeatable assurance process that agents can apply
  procedurally.
- Critical state machines have formal specs or model-derived tests.
- High-risk modules are mutation-tested.
- AI-assisted development remains fast without relying on stale human memory as
  the main correctness mechanism.
