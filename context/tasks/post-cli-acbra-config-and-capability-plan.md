# Post-CLI ACBRA Configuration And Capability Plan

## Purpose

Use the boundaries created by the CLI ACBRA campaign to replace Penguin's
implicit, mutable configuration web with one typed, provenance-aware contract
shared by CLI, web, TUI, Python API, agents, and background execution.

This is a follow-up campaign, not part of the CLI extraction stack. The CLI
work exposed the seams and supplied deterministic bootstrap/model-projection
tests; this plan changes the underlying configuration architecture in bounded
ACBRA slices.

## Inputs Reviewed

- `features.md`, especially its recommendations around model capability
  gating, per-tool policy, worktree/execution-environment lifecycle, skills,
  agent modes, automation, and cross-surface runtime truth.
- `context/tasks/cli-acbra-testing-refactor.md` and the extracted CLI modules.
- `context/tasks/model-config-mutation-state-leak.md`.
- `context/tasks/skills.md`, `context/tasks/resolve-multi-agents.md`, and
  `context/tasks/cli-interface-ergonomics-plan.md`.
- Current configuration consumers in CLI, core, web services, tools, memory,
  projects, security, and agents.

No repository-level `references/` directory existed on August 7, 2026. The
only directory with that name was inside an installed FastAPI skill dependency,
so it was not treated as Penguin design input.

## Current Evidence

`penguin/config.py` is 1,747 lines and currently combines responsibilities that
need different lifecycle and ownership rules:

- source discovery and precedence across package, user, project, local, and
  explicit files
- YAML reading/writing and dotted-key mutation
- deep merge policy, including special additive security lists
- setup-wizard triggering and import-time environment behavior
- secret/environment loading and compatibility globals
- path/root discovery and creation of workspace directories
- immutable startup settings and mutable runtime observer state
- diagnostics/logging side effects
- model, persona, security, output, API, and audit schemas
- legacy constants and two different classes named `Config`
- compatibility projections between dictionaries and typed objects

There are roughly 60 direct `penguin.config` consumers under `penguin/` and
`tests/`. Additional configuration truth exists in:

- `penguin/llm/model_config.py` (946 lines)
- CLI `model_runtime.py` and the bootstrap `_ConfigWrapper`
- web configuration, provider catalog, credential, and auth services
- orchestration and plugin configuration modules
- module-level globals such as `WORKSPACE_PATH`, `config`, API keys, model
  defaults, and conversation paths

The result is observable ambiguity:

- a value's source and explicit/unset status are usually lost after merging
- provider catalog metadata, credentials, user intent, and inferred runtime
  capabilities can be mistaken for one another
- `Config.model` manufactures a dictionary containing a callable `get` value
- `Config.to_dict()` is a compatibility payload rather than a stable inverse
  of loading
- constructors and imports may read or mutate environment and filesystem state
- runtime changes are projected back through environment variables
- consumers accept a mix of raw mappings, typed dataclasses, wrappers, and
  module globals
- caller-owned `ModelConfig` objects can be contaminated by transport/runtime
  resolution, as tracked in `model-config-mutation-state-leak.md`

## Target Contract

Introduce `penguin/configuration/` while retaining `penguin/config.py` as a
temporary, explicitly tested compatibility facade.

Proposed ownership:

```text
penguin/configuration/
  schema.py          # Pydantic input/effective schemas; no I/O
  sources.py         # discover and read config sources
  merge.py           # deterministic merge rules and origin tracking
  resolution.py      # validate raw layers into EffectiveConfig
  provenance.py      # source, explicitness, and derivation metadata
  secrets.py         # credential references and explicit env/store lookup
  paths.py           # user/project/workspace path policy; no mkdir on import
  runtime.py         # mutable RuntimeSettings and change events
  serialization.py   # stable public/redacted/compatibility projections
```

Core types:

- `ConfigLayer`: source id, scope, path, precedence, and raw mapping.
- `ValueOrigin`: source, explicit/inferred/default state, and optional
  derivation reason.
- `EffectiveConfig`: validated, immutable startup configuration.
- `ResolvedValue[T]` or an equivalent origin map for fields where provenance
  changes behavior, especially model/reasoning/tool policy.
- `RuntimeSettings`: the narrow set of settings that can change after startup;
  changes emit typed events and never silently rewrite process environment.
- `ConfigResolution`: effective config plus diagnostics, origins, and the
  ordered source list.

Rules:

- Loading and merging are pure with injected filesystem/environment snapshots.
- Validation happens once after merge; consumers receive typed settings.
- User intent, catalog metadata, credentials, and runtime derivation are
  separate inputs.
- Effective startup config is immutable. Runtime request configs are derived
  copies, never mutations of caller-owned config.
- Secrets are references or redacted values in configuration projections; raw
  credentials are resolved only at the provider boundary.
- Importing a configuration module does not prompt, create directories, load
  dotenv, configure logging, or mutate environment.
- CLI, web, TUI, and Python API expose the same redacted effective-config and
  provenance contracts.

## Capability Boundaries Enabled By This Work

The configuration refactor should provide typed policy inputs for these
features without implementing the features inside configuration code:

1. Model capability gating
   - Resolve model identity first, then combine provider/catalog capability
     metadata with explicit user overrides.
   - Gate reasoning, verbosity, service tier, vision, and parallel tool-call
     options from the resolved target model.

2. Agent modes and subagents
   - Small named modes/personas can bind model, prompt, toolset, permissions,
     concurrency/depth limits, and sandbox inheritance.
   - CLI, HTTP, ActionXML, and internal spawning consume one resolution API.

3. Per-tool execution policy
   - Typed metadata can express `read_parallel_safe`, `mutation_exclusive`,
     `requires_confirmation`, `cancel_safe`, `streaming_result`, and
     `terminal_tool`.
   - Surface-specific overrides remain policy layers, not conditionals spread
     across tool implementations.

4. Execution environments and worktrees
   - Configuration selects backend and policy; runtime state owns lifecycle.
   - Local, worktree, container, and future remote backends share a typed
     immutable startup specification.

5. Skills, hooks, messaging, and automation
   - Source/scope rules support user, project, local, and managed policy.
   - Platform profiles can enable bounded toolsets and delivery channels
     without giving every surface the same risk profile.

6. Cross-surface truth
   - Stable redacted projections let CLI diagnostics, web endpoints, TUI, and
     SDK clients explain both the effective value and why it won.

The canonical runtime-event ledger, evidence-backed completion, and background
control plane from `features.md` remain separate runtime projects. They should
consume the typed settings/events produced here rather than being added to the
config loader.

## ACBRA Slice Plan

### Slice 0: Freeze Compatibility And Inventory Consumers

- Add `__all__` to the compatibility facade and classify every exported name.
- Inventory consumers as schema, source/merge, path, secret, runtime-mutable,
  constant, or legacy-only.
- Characterize imports, filesystem/environment side effects, source
  precedence, security-list merging, and current serialized payloads.
- Add an architecture test preventing new direct consumers of legacy globals.

Acceptance:

- Every compatibility export has an owner and migration destination.
- Import-side effects and currently relied-on quirks are visible in tests.

### Slice 1: Pure Sources, Merge, And Provenance

- Extract source discovery and YAML reading behind injected dependencies.
- Extract deep merge into a pure function with declared per-field strategies.
- Preserve an origin map through every layer.
- Return structured diagnostics for missing, invalid, or unreadable sources;
  do not swallow broad exceptions.

Required tests:

- table-driven precedence across package/user/project/local/explicit layers
- property tests for determinism, idempotence, non-mutation, and associative
  behavior where a merge strategy promises it
- additive security-list order/deduplication tests
- malformed YAML and fault-injected filesystem errors

### Slice 2: Typed Effective Configuration

- Move dataclass/schema definitions out of `config.py` into dedicated schema
  modules, using Pydantic validation where user input requires coercion and
  actionable errors.
- Eliminate the duplicate `Config` class name.
- Define one canonical `EffectiveConfig` and explicit public/redacted
  serialization shapes.
- Remove dictionary tricks such as embedding a callable `get` entry.

Required tests:

- load/serialize/reload round trips
- invalid type and unknown-key diagnostics
- compatibility snapshots for CLI/web/API payloads
- explicit false/zero/empty versus unset handling

### Slice 3: Model Intent, Catalog, And Runtime Derivation

- Make configured model intent a typed part of `EffectiveConfig`.
- Keep provider catalog capability metadata and credentials separate.
- Move CLI reasoning provenance into the shared resolution contract.
- Complete `model-config-mutation-state-leak.md`: derive request/transport
  configs from copies and prohibit provider handlers from mutating source
  settings.

Required tests:

- provider/model qualification matrix
- explicit/inferred reasoning, token budget, service tier, and vision matrix
- catalog unavailable/stale/malformed behavior
- repeated client/handler construction from one config with no state bleed
- parity across CLI bootstrap, core model switch, agent spawn, and HTTP request

### Slice 4: Paths, Environment, Secrets, And Side Effects

- Consolidate root/workspace/config path policy under `configuration.paths`.
- Pass an explicit environment snapshot into resolution.
- Move directory creation to startup services that own the directories.
- Resolve credentials at provider construction and redact them everywhere else.
- Remove dotenv/setup/logging behavior from module import.

Required tests:

- POSIX/Windows/XDG path matrices, symlinks, missing roots, and permissions
- no prompt, mkdir, env mutation, credential read, or logging setup on import
- credential source precedence and redaction
- concurrent resolutions with different env/cwd snapshots remain isolated

### Slice 5: Runtime Settings And Change Events

- Define the narrow mutable subset: active root, execution mode, selected
  runtime profile, and explicitly approved toggles.
- Replace observer strings with typed change events.
- Make update operations transactional: validate, publish, or leave state
  unchanged.
- Remove environment variables as the synchronization bus.

Required tests:

- state-machine tests for valid/invalid updates and observer failures
- concurrent reader/update behavior
- rollback on validation or subscriber failure according to a documented rule
- CLI/web/TUI update parity

### Slice 6: Migrate Consumers And Shrink The Facade

Suggested order:

1. CLI bootstrap and config commands
2. web configuration/provider endpoints
3. core and agent/model resolution
4. security/tools/projects
5. memory/conversation/path consumers
6. plugins and compatibility-only imports

Each migration removes raw dictionary and module-global access from that
consumer. `penguin/config.py` delegates with deprecation warnings where safe;
widely imported constants remain shims until all consumers move.

Acceptance:

- all primary surfaces resolve one `EffectiveConfig`
- no `_ConfigWrapper` remains in CLI bootstrap
- no new business module imports mutable global `config`
- the compatibility facade is small, documented, and has a removal issue for
  each remaining export

### Slice 7: Productize The Unlocked Policies

Deliver as separate feature PRs after their config contracts are stable:

- explainable `penguin config sources|effective|why <key>` diagnostics
- capability-gated model option UX
- surface-specific agent/tool permission profiles
- worktree/execution-backend profiles
- skills/hooks scope and managed-policy layers
- automation/messaging delivery profiles

Do not couple these product changes to the core loader migration.

## Test And Verification Pyramid

- Static: compile, Ruff, public `__all__`, dependency-cycle checks.
- Unit: pure source discovery, merge, validation, redaction, derivation.
- Property: merge laws, provenance preservation, serialization round trips.
- State machine: runtime updates and subscriber lifecycle.
- Contract: CLI/web/TUI/Python effective-config parity and stable redaction.
- Hermetic integration: temporary config trees, fake env, fake credential
  stores, fake provider catalog, concurrent isolated bootstraps.
- Artifact: installed wheel imports with an empty home/config and runs config
  diagnostics without prompting or creating unrelated files.
- Fault injection: unreadable files, malformed layers, missing catalog,
  credential-store failure, subscriber exception, partial startup.
- Mutation: precedence, explicit/unset handling, model capability gating, and
  redaction branches.

Live provider tests remain opt-in smoke tests and are never proof of config
resolution correctness.

## Proposed PR Stack

1. Characterization, consumer inventory, and compatibility `__all__`.
2. Pure source/merge/provenance package.
3. Typed effective schemas and serialization.
4. Model intent/capability derivation and mutation-leak fix.
5. Paths/secrets/import-side-effect removal.
6. Runtime settings/events.
7. Consumer migrations in two or more bounded stacks.
8. Compatibility-facade reduction and docs.

Each PR records source precedence, compatibility exports changed, side effects
removed, test evidence, and the next consumers to migrate.

## Non-Goals

- No new settings UI framework in the loader PRs.
- No provider discovery network calls during configuration resolution.
- No runtime event-ledger or background scheduler implementation here.
- No wholesale YAML schema redesign before existing keys are characterized.
- No removal of compatibility globals without consumer and installed-artifact
  evidence.
- No use of configuration code as a service locator.

## Definition Of Done

- One immutable typed effective configuration is used across primary surfaces.
- Source and explicit/inferred provenance are inspectable for behaviorally
  significant values.
- Provider metadata, credentials, user intent, and derived request settings
  have separate owners.
- Configuration imports are free of prompting, filesystem creation,
  environment mutation, credential loading, and logging setup.
- Runtime mutations are narrow, transactional, typed, and session-safe.
- Caller-owned model/config objects are not mutated by resolution or provider
  construction.
- CLI/web/TUI/Python expose equivalent redacted effective-config truth.
- `penguin/config.py` is a small compatibility facade with an explicit removal
  path, not a second implementation.
