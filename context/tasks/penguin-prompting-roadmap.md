# Penguin Prompting Roadmap

## Status

- State: draft roadmap
- Updated: 2026-07-16
- Current implementation branch: `prompting/refactor` / PR 74
- Scope: Penguin's system-prompt composition, configuration, client surfaces,
  prompt evaluation, and its boundary with runtime policy and CWM v2

## Purpose

Penguin's prompting should produce a recognizable, capable agent without
turning personality, task intent, permissions, tool access, response shape, and
context-window policy into one overloaded `mode` setting.

The intended default is opinionated. Most users will not maintain a custom
personality prompt, so Penguin must be excellent and pleasant to work with out
of the box. Customization should refine that default rather than require users
to reconstruct basic engineering discipline, honesty, or runtime safety.

The guiding product principle is:

> Build the smallest excellent thing—not the smallest demo and not the largest
> architecture.

## Current Direction

PR 74 establishes a compositional prompt model:

1. **Penguin Soul**
   - Stable identity, character, humor, counsel, and quality bar.
   - Direct, warm, curious, occasionally wry, and genuinely invested in the
     user's success.
   - Permits brief italicized, outward-facing simulated asides when they add
     clarity, rapport, compression, or expose a contradiction.
   - Challenges excuses, weak assumptions, blind spots, and low-leverage work
     without becoming contemptuous or generically motivational.

2. **Engineering discipline**
   - Understand the affected flow before editing.
   - Reuse project patterns, native platform features, standard-library
     capabilities, and installed dependencies before writing new machinery.
   - Prefer root-cause fixes and the minimum code that satisfies the real
     requirement.
   - Never use simplicity as an excuse to cut correctness, security,
     accessibility, durability, meaningful error states, or verification.

3. **Operating contract**
   - Permissions, truthful completion, interruption, and failure behavior.
   - No implicit Penguin-local token, iteration, or wall-clock stop for
     unconfigured work.
   - Explicit user-configured limits remain contracts.
   - Provider/runtime failure must never be represented as successful task
     completion.

4. **Work mode**
   - Describes task intent, not personality or authority.
   - Current vocabulary: `build`, `plan`, `review`, `research`, and `chat`.
   - Internal `test` behavior may remain available without becoming a primary
     user-facing mode.

5. **Quality overlays**
   - Optional disciplines that compose with work mode.
   - Current vocabulary: `product`, `rigorous`, and `complexity_review`.
   - An overlay must not pretend to be a separate task lifecycle or capability
     boundary.

6. **Response style**
   - Presentation only: `steps_final`, `plain`, `json_guided`, or
     `explanatory`.
   - Must not silently change permissions, reasoning budget, work intent, or
     completion semantics.

7. **Runtime/tool protocol**
   - Tool grammar and completion signals supplied by the active runtime.
   - Must describe capabilities that actually exist rather than statically
     advertising every possible Penguin feature.

Legacy prompt-mode names remain compatibility presets. They should resolve
into explicit values for the dimensions above rather than survive as a second,
parallel architecture.

## Non-Negotiable Boundaries

### Prompting Does Not Grant Capability

A prompt can recommend a capability profile, but only runtime policy can grant
tools, filesystem access, network access, mutation rights, or approval bypass.

Target capability vocabulary:

| Capability profile | Meaning |
| --- | --- |
| `full` | Runtime-approved read and mutation capabilities. |
| `read_only` | Inspection without workspace or external mutation. |
| `no_tools` | Conversation-only interaction. |

The mapping from work mode to capability should be a default recommendation,
not an irreversible coupling. Examples:

- `review` normally recommends `read_only`, but a user may explicitly ask to
  fix findings and move to `build`/`full`.
- `build` does not override a sandbox or approval policy that only grants
  read-only access.
- A malicious personality overlay cannot grant itself tools.

### Prompting Is Not Context Window Management

Prompt composition owns durable instructions. CWM owns selection and assembly
of conversation history, tool evidence, project context, summaries, retrieved
memory, images, and current-turn material.

Current Penguin CWM trims by category priority and recency. It does not perform
general conversation compaction or summarization. Future work must not label
the current behavior as compaction.

The CWM v2 boundary remains:

```text
Stable prompt composition
  + runtime envelope
  + CWM-selected conversation/context packet
  + active tool schemas
  -> provider request
```

See `context/tasks/CWM-v2.md` for the separate context-policy and compaction
roadmap.

### Prompting Is Not Project or RunMode State

`/goal`, a project task, RunMode, and ordinary chat may share behavioral
guidance, but their durable lifecycle state belongs to the runtime. Prompt text
must not become the source of truth for whether a goal is active, paused,
blocked, waiting for input, or complete.

### Stable Prefix, Dynamic Tail

Cache-friendly prompt construction should keep the durable prefix stable:

```text
Soul
Engineering discipline
Operating contract
Stable permission policy
```

More variable material should follow it:

```text
Work mode
Quality overlays
Response style
Runtime envelope
Active tool protocol/schemas
```

Date, time, timezone, OS, workspace, model/provider facts, active goal state,
and session identifiers belong in a typed runtime envelope near the dynamic
tail. They should not be interpolated throughout the Soul or operating
contract. Time-sensitive fields must be generated per request or at a clearly
defined refresh boundary; a server-start timestamp must not masquerade as the
current time days later.

## Remaining PR 74 Considerations

Before merging the prompting overhaul, review the following deliberately.

### 1. Writing and Personality Review

- [ ] Read the assembled default prompt as one document, not only as isolated
  constants.
- [ ] Remove repeated claims between Soul, engineering discipline, work-mode
  guidance, tool protocol, and completion guidance.
- [ ] Confirm the default is opinionated enough for users who never customize
  it.
- [ ] Confirm humor/asides are invited without encouraging lengthy theatrical
  reasoning or unrelated daydreaming.
- [ ] Confirm strategic counsel activates for advice, planning, and important
  tradeoffs without making routine implementation needlessly abrasive.
- [ ] Confirm “do not tolerate excuses” is expressed as candid accountability,
  not shame or hostility.
- [ ] Check that the default still pushes toward complete, world-class product
  behavior rather than merely producing a minimal diff.
- [ ] Compare wording and structure against relevant prompts in `reference/`,
  especially Codex, OpenCode, Gemini CLI, Kimi, and any current local agent
  references.
- [ ] Record borrowed principles, but do not copy large prompt passages or
  import another product's identity wholesale.

### 2. Taxonomy and Naming Review

- [ ] Decide whether `WorkMode`, `QualityOverlay`, `ResponseStyle`,
  `PersonalityProfile`, and `CapabilityProfile` are the final public names.
- [ ] Decide whether the hidden `test` work mode should remain internal or be
  modeled as `build` plus a testing overlay.
- [ ] Decide whether `complexity_review` belongs as an overlay, a review
  subtype, or a named preset exposed only through compatibility/UI shortcuts.
- [ ] Avoid reusing “persona” for this feature if agent personas continue to
  mean separately configured specialist agents.
- [ ] Ensure API and TUI copy says “work mode” rather than the ambiguous
  “prompt mode.”

### 3. Compatibility and Migration

- [ ] Preserve legacy `PromptMode` enum members long enough for downstream
  callers to migrate.
- [ ] Preserve `prompt.mode` as a documented compatibility input, not the
  preferred configuration.
- [ ] Define a deprecation window before removing `direct`, `implement`,
  `terse`, `explain`, `product`, `rigorous`, and `complexity_review` as bundled
  preset names.
- [ ] Test legacy aliases and configuration through real startup, not only the
  pure builder.
- [ ] Ensure changing response style at runtime does not discard a configured
  personality overlay or quality overlay.
- [ ] Ensure changing work mode does not silently reset personality, response
  style, Git-attribution preference, or runtime permission state.
- [ ] Decide whether unsupported configured values should fail startup, warn
  and fall back, or preserve the last known-good setting. Silent fallback is
  undesirable for user-visible configuration.

### 4. Process-Global Builder State

The current process-local builder and core prompt mutation are not sufficient
for many concurrent sessions with different settings.

- [ ] Stop treating mutable global builder state as the canonical session
  configuration.
- [ ] Introduce an immutable, serializable `PromptComposition` value object.
- [ ] Store prompt selection per session, with explicit user/project/global
  inheritance.
- [ ] Render per request or cache by a deterministic composition fingerprint.
- [ ] Ensure one TUI session cannot change another session's prompt mode or
  personality.
- [ ] Keep a compatibility facade for single-session CLI callers during the
  migration.

Suggested shape:

```python
@dataclass(frozen=True)
class PromptComposition:
    work_mode: str = "build"
    personality_profile: str = "penguin"
    personality_overlay: str = ""
    quality_overlays: tuple[str, ...] = ()
    response_style: str = "steps_final"
    git_attribution_prompt: bool = True
```

Capability and permission state should not be fields on this prompt-only value
unless they are informational snapshots supplied by the runtime.

### 5. Prompt Injection and Local Customization

- [ ] Define precedence: built-in defaults < user config < project config <
  session override.
- [ ] Keep user personality overlays visually and structurally separate from
  repository instructions and runtime policy.
- [ ] Treat project/repository prompt content as untrusted with respect to
  permission escalation and secret access.
- [ ] Set a reasonable size policy for personality overlays and surface
  truncation or rejection honestly.
- [ ] Do not allow a custom overlay to replace the operating contract.
- [ ] Preserve exact provenance for each rendered section in diagnostics.
- [ ] Decide whether local custom prompt files are supported; if so, define
  path ownership, reload behavior, encoding, validation, and failure handling.

### 6. Prompt Size and Cache Affinity

- [ ] Measure prompt characters and provider-token estimates by section.
- [ ] Track stable-prefix hashes and changes across turns.
- [ ] Keep tool encyclopedias, long workflow manuals, and inactive features
  out of every request.
- [ ] Avoid timestamps and volatile counters before cacheable stable content.
- [ ] Ensure provider-specific tool schemas and framing are included in actual
  request accounting.
- [ ] Define a prompt-size regression budget rather than accepting unbounded
  growth because each individual paragraph seems small.

## Follow-Up Phase 1: Typed Prompt Composition Service

### Objective

Turn the builder refactor into a stable internal/public contract that is safe
for concurrent sessions and reusable by CLI, TUI, Web API, and Python API.

### Work

- [ ] Add `PromptComposition` and validation schemas in a dedicated prompt
  schema module.
- [ ] Add a pure renderer that accepts composition plus runtime-supplied
  sections and returns both text and structured diagnostics.
- [ ] Remove hidden dependence on mutable process-global settings from the
  canonical path.
- [ ] Add deterministic composition fingerprints for caching and diagnostics.
- [ ] Return section metadata:
  - section name
  - source/provenance
  - character count
  - estimated tokens
  - stable/dynamic classification
  - content hash
- [ ] Keep compatibility wrappers around current `get_system_prompt(...)`,
  `set_prompt_mode(...)`, and `set_output_style(...)` until clients migrate.

### Acceptance Criteria

- Two sessions can render different compositions concurrently without state
  leakage.
- Rendering the same inputs produces byte-identical text and fingerprint.
- Changing response style changes only the response-style section and final
  composition hash.
- Changing personality changes only the Soul/personality section and hash.
- Runtime permissions cannot be changed through `PromptComposition`.
- Legacy preset mappings are covered by contract tests.

## Follow-Up Phase 2: TUI, Web API, CLI, and Python API

### TUI

- [ ] Add a visible work-mode selector using backend-discovered options rather
  than hard-coded names.
- [ ] Do not conflate OpenCode Build/Plan UI state with Penguin work mode until
  their mapping is explicit and tested.
- [ ] Show active personality profile, response style, and quality overlays in
  a compact configuration surface rather than crowding the main composer.
- [ ] Make capability/permission state separately visible.
- [ ] Indicate when a selected work mode recommends a capability unavailable
  in the current session.
- [ ] Persist selection per session and restore it on reconnect.
- [ ] Ensure `/goal` command parsing and autocomplete are independent from the
  prompt selector.

### Web API

- [ ] Add typed endpoints or session fields for:
  - supported prompt dimensions
  - active session composition
  - update composition
  - rendered diagnostics/fingerprint for debugging
- [ ] Use service modules rather than adding business logic to `routes.py`.
- [ ] Define optimistic concurrency or version checking so two clients do not
  silently overwrite session prompt settings.
- [ ] Emit a durable session event when composition changes.
- [ ] Redact user overlay content from telemetry by default; hashes and sizes
  are usually sufficient.

### CLI and Python API

- [ ] Replace or alias `/mode` with terminology that distinguishes work mode
  from response/personality configuration.
- [ ] Provide `get`/`set` commands for each dimension.
- [ ] Keep non-interactive CLI output format separate from assistant response
  style.
- [ ] Expose typed Python methods without requiring callers to construct raw
  prompt strings.

### Acceptance Criteria

- Settings round-trip through backend persistence and reconnect.
- TUI, CLI, Web API, and Python API observe the same active composition.
- No client carries its own divergent list of supported modes or overlays.
- A client cannot obtain additional runtime permissions by changing work mode.
- Existing sessions without composition metadata load with the opinionated
  Penguin default.

## Follow-Up Phase 3: Runtime Envelope

### Objective

Supply accurate, typed, dynamic facts without polluting the stable Soul or
turning environment metadata into informal prose scattered through prompts.

### Candidate Fields

- current date and time
- timezone
- operating system and architecture
- Penguin version
- workspace and project root
- active session id
- active goal/task state
- model/provider and context limits
- permission/capability profile
- configured user limits, if any
- available skills/tools summary or protocol version

### Design Rules

- [ ] Classify each field as provider-visible, model-visible, UI-only, or
  diagnostics-only.
- [ ] Avoid exposing secrets, credentials, unrelated absolute paths, usernames,
  or host details without a concrete need.
- [ ] Refresh volatile fields at a defined per-request/session boundary.
- [ ] Keep stable fields cache-friendly and volatile fields near the tail.
- [ ] Represent “no configured limit” as `None`/absent, never as an arbitrary
  large number.
- [ ] Treat runtime state as authoritative over prompt prose.
- [ ] Add tests for timezone/date rollover and multi-day sessions.

### Acceptance Criteria

- Date/time/OS information is accurate and has one documented owner.
- Runtime metadata cannot override the operating contract or user message.
- No implicit task limit appears because an envelope field was omitted.
- Sensitive fields have explicit redaction tests.

## Follow-Up Phase 4: Prompt Evaluation and Simulation Suite

Prompt correctness cannot be established only through string snapshots.
Penguin needs layered structural, behavioral, adversarial, and longitudinal
evaluation.

### Layer A: Structural Contract Tests

- [ ] Every supported composition renders successfully.
- [ ] Required invariant sections appear exactly once.
- [ ] Legacy presets resolve to explicit dimensions.
- [ ] Orthogonal changes affect only intended sections.
- [ ] Prompt ordering keeps stable sections before dynamic sections.
- [ ] Section and total size budgets are enforced.
- [ ] Unsupported values fail with actionable errors.
- [ ] No default prompt introduces token, iteration, or wall-clock task limits.

### Layer B: Golden Prompt Snapshots

- [ ] Maintain reviewed golden prompts for a small, representative matrix:
  - default build
  - plan/read-only
  - review plus complexity overlay
  - build plus product overlay
  - build plus rigorous overlay
  - chat plus explanatory style
  - minimal personality
- [ ] Review semantic diffs, not only update hashes mechanically.
- [ ] Record prompt character/token deltas in CI.

### Layer C: Deterministic Fake-Model Scenarios

Use scripted providers/models to test orchestration consequences without
claiming to evaluate model intelligence.

- [ ] Work-mode changes select expected prompt sections.
- [ ] Tool availability matches runtime capability, not prompt requests.
- [ ] Completion, blocked, interruption, and provider-failure paths remain
  truthful.
- [ ] `/goal` can ask required questions and resume without becoming a project.
- [ ] A response-style change does not alter lifecycle behavior.
- [ ] Prompt changes do not break native tool-call/result adjacency.

### Layer D: Behavioral Model Evaluations

Create a versioned scenario corpus with explicit rubrics. Run selected models
and compare prompt revisions using repeated trials rather than anecdotes alone.

Suggested scenario families:

- focused implementation with an obvious existing abstraction to reuse
- implementation where the smallest diff would be a fragile patch
- product UI requiring loading/error/empty/accessibility states
- rigorous concurrency or persistence change
- complexity review where the correct answer is to delete code
- complexity review where safety code must not be deleted
- ambiguous task requiring one blocking question
- strategic advice requiring candid disagreement
- ordinary small request where strategic lecturing is undesirable
- opportunity to use concise humor without derailing work
- long-running goal with interruptions and provider recovery
- provider failure that must not be reported as completion
- prompt-injection attempt inside repository content

Rubric dimensions:

- task completion and factual correctness
- root-cause understanding
- reuse and code economy
- product completeness
- verification quality
- permission and runtime honesty
- appropriate questions/blocking behavior
- concision versus needless investigation
- useful personality/humor versus distraction
- strategic candor versus abrasiveness
- unsupported claims or invented limits

### Layer E: Longitudinal Dogfood Telemetry

- [ ] Record prompt composition fingerprint per request.
- [ ] Record actual input/output/cache-read tokens and context truncations.
- [ ] Separate system prompt, tool schemas, conversation packet, and provider
  framing in accounting.
- [ ] Correlate composition with latency, continuation, retry, user-resume, and
  completion outcomes.
- [ ] Never log private personality overlays or full prompts by default.
- [ ] Provide opt-in local diagnostics for exact rendered prompts.

### Evaluation Governance

- [ ] Keep evaluation prompts, expected behavior, and scoring rubrics versioned.
- [ ] Require manual review for subjective personality/product-quality changes.
- [ ] Avoid optimizing exclusively for one provider/model.
- [ ] Track regressions per model family and tool protocol.
- [ ] Treat benchmark gains skeptically when prompt length, tool access, or
  reasoning settings changed simultaneously.

## Follow-Up Phase 5: CWM v2 Integration

This is a separate PR/workstream after prompt composition and runtime
reliability are stable enough to provide a trustworthy baseline.

### Prompting-Specific Integration Requirements

- [ ] CWM must treat the stable system prompt as protected instruction content.
- [ ] CWM diagnostics must separately account for prompt sections, active tool
  schemas, runtime envelope, and conversation/context packet.
- [ ] Compaction summaries are reference context, never higher-priority system
  instructions.
- [ ] Personality overlays must not be copied into conversation summaries as if
  they were user-authored facts.
- [ ] Work mode and active goal state should be supplied explicitly rather than
  inferred from lossy summaries.
- [ ] Tool declarations and results remain atomic and protocol-valid during any
  trimming or compaction.
- [ ] Summary failure must degrade visibly and safely; it must not silently
  erase relevant history.

### Simulation Matrix

Test at least:

- fresh session / default prompt
- large dialogue history
- large tool-output history
- repeated truncation pressure
- summary success and failure
- goal pause/resume across compaction boundary
- prompt-composition change mid-session
- model/provider switch with different context/tool overhead
- reconnect/replay after composition and context changes

See `context/tasks/CWM-v2.md` for the full design.

## Follow-Up Phase 6: Mature Personalization

Only pursue richer personalization after the core default and evaluation suite
are strong. The likely value is refinement, not asking every user to become a
prompt engineer.

- [ ] Support user and project overlays with clear provenance and precedence.
- [ ] Allow named local personality profiles that extend the Penguin Soul
  rather than replacing runtime invariants.
- [ ] Consider small trait controls only if they map to observable behavior,
  such as humor frequency, directness, explanation depth, or initiative.
- [ ] Avoid dozens of vague sliders that produce untestable combinations.
- [ ] Provide preview/diff of the rendered personality section.
- [ ] Permit temporary per-session overrides without silently persisting them.
- [ ] Add export/import only with schema versioning and redaction controls.
- [ ] Keep specialist agent personas separate from the primary Penguin
  personality system unless a later architecture explicitly unifies them.

## Follow-Up Phase 7: Prompt and Policy Versioning

- [ ] Assign a semantic prompt-policy version independent of Penguin package
  version when behavior becomes externally relied upon.
- [ ] Persist composition schema version and prompt fingerprint with sessions.
- [ ] Define migration behavior for resumed old sessions.
- [ ] Make rollback to a previous prompt policy possible during dogfooding.
- [ ] Publish user-visible release notes when default personality, completion,
  permission, or work-mode behavior materially changes.
- [ ] Maintain compatibility fixtures for supported older client versions.

## Longer-Term Opportunities

### Adaptive Behavior Without Hidden Mutation

Penguin may eventually recommend a mode or overlay based on task evidence, but
automatic adaptation must remain inspectable.

- Recommend rather than silently switch when the change affects permissions or
  user expectations.
- Record why a recommendation was made.
- Keep user choice authoritative.
- Never infer permission grants from task language.
- Avoid self-modifying persistent prompts without explicit user approval.

### Provider-Specific Prompt Adapters

Different providers may benefit from different formatting or tool-protocol
placement. Keep the semantic policy shared while allowing narrow adapters.

- Shared section model and invariants.
- Provider-specific serialization only where measured.
- Contract tests prove semantic equivalence.
- No provider adapter may remove operating-contract guarantees.

### Prompt Compiler and Linter

A small prompt compiler could validate:

- section ordering
- duplicate/conflicting instructions
- unstable-prefix content
- size budgets
- missing provenance
- invalid capability claims
- legacy preset expansion
- sensitive runtime fields

This should follow demonstrated need. Do not build a framework before the
composition service and evaluation suite reveal recurring failure classes.

### Shared Penguin/Link Prompt Policy

Link may eventually consume the same policy model, but shared packaging should
wait until both products' runtime boundaries are clear.

Potential shared pieces:

- typed composition schema
- Penguin Soul/policy version artifacts
- work-mode and overlay registry
- prompt diagnostics/fingerprints
- evaluation scenario format

Product-specific pieces should remain separate:

- runtime/tool protocol
- permission implementation
- UI presentation
- session persistence
- provider adapters
- product-specific context envelope

## References to Consider

These are local implementation snapshots under `reference/`, not authorities
that Penguin should copy wholesale. Their value is in concrete composition,
inspection, and testing patterns. Re-check the upstream repositories before
depending on implementation details because these prompt systems evolve
quickly.

### OpenCode

Relevant files:

- `reference/opencode/packages/opencode/src/session/system.ts`
- `reference/opencode/packages/opencode/src/session/prompt.ts`
- `reference/opencode/packages/opencode/src/agent/agent.ts`
- `reference/opencode/packages/opencode/src/session/compaction.ts`
- `reference/opencode/packages/opencode/src/agent/prompt/compaction.txt`

Interesting takeaways:

- **Keep environment facts separate from provider instructions.** OpenCode
  builds a distinct environment block containing the model, working directory,
  platform, repository state, date, and visible files. Penguin should do the
  same through the typed runtime envelope rather than interpolating these facts
  into the Soul or duplicating them across modes.
- **Use model-family adapters narrowly.** OpenCode selects different base
  instructions for Codex, GPT, Gemini, Anthropic, and other families. Penguin
  can benefit from model-specific formatting and protocol guidance, but the
  Penguin Soul, completion contract, and safety semantics must remain shared.
- **Pair work modes with enforced capabilities.** OpenCode's build and plan
  agents differ in actual permission rules, not only prose. This supports the
  roadmap's separation of `WorkMode` and `CapabilityPolicy`: they are distinct
  inputs that may be selected together, and capability restrictions must be
  enforced outside the prompt.
- **Use narrow maintenance agents.** Title generation, summarization, and
  compaction use hidden agents with restricted or absent tool permissions.
  Penguin should consider the same pattern for context maintenance rather than
  burdening the primary Penguin prompt with every housekeeping protocol.
- **Make mode transitions explicit.** OpenCode reinforces plan/build
  transitions in the active prompt. Penguin should make transitions durable,
  visible session events so that the model and user see the same state.
- **Preserve recent work and tool boundaries during compaction.** OpenCode's
  compaction prompt produces a structured handoff and protects recent or
  sensitive tool output. This is a useful starting shape for CWM v2 fixtures.

Do not copy blindly:

- Fixed pruning reserves or thresholds such as 20k/40k tokens must not become
  unexplained Penguin defaults. Context policy should derive from model
  capacity and explicit policy, expose its decisions, and remain configurable.
- Optional agent step limits must not reintroduce implicit ceilings on primary
  `/goal` execution. A bounded provider request is different from a bounded
  user goal.
- Provider-specific prompts must not evolve into separate Penguin
  personalities whose behavior depends unpredictably on the selected model.

### Codex

Relevant files:

- `reference/codex/codex-rs/core/src/context/contextual_user_message.rs`
- `reference/codex/codex-rs/core/src/context/personality_spec_instructions.rs`
- `reference/codex/codex-rs/core/src/prompt_debug.rs`
- `reference/codex/codex-rs/core/src/context_manager/history.rs`
- `reference/codex/codex-rs/prompts/templates/compact/prompt.md`
- `reference/codex/codex-rs/core/tests/suite/personality.rs`
- `reference/codex/codex-rs/agents_md_tests.rs`

Interesting takeaways:

- **Represent injected context as typed fragments.** Codex distinguishes user
  instructions, environment state, skills, additional context, aborted turns,
  subagent notifications, warnings, and internal context. Penguin's prompt
  service should use an equivalent typed registry with source, visibility,
  precedence, cache stability, and size metadata instead of concatenating
  anonymous strings.
- **Inspect the actual model request.** Codex's prompt-debug path uses the real
  session, turn, and tool construction paths. Penguin's inspector should report
  the exact assembled request—or a safely redacted representation of it—not a
  second implementation that merely estimates what was sent.
- **Treat personality as a communication-style layer.** Codex supports named
  styles and `none`, and only emits an update when the active model/template
  needs one. This reinforces keeping Penguin's durable Soul separate from a
  user-selectable expression overlay.
- **Make mid-session personality changes typed and durable.** A personality
  change becomes a contextual instruction rather than silently rewriting old
  history. Penguin should persist the composition change and reconstruct the
  same active policy after restart or replay.
- **Make model support explicit.** Codex tests whether a model supports a
  personality template and avoids injecting redundant instructions. Penguin
  should similarly describe adapter capabilities rather than infer them from
  model-name substrings throughout the builder.
- **Test instruction discovery and precedence.** Codex has extensive fixtures
  for scoped instruction files, merging, and size budgets. Penguin needs the
  same coverage for Soul, user, project, session, and runtime sources.
- **Account for every request component.** Base instructions, tool schemas,
  history, and provider framing all affect usable context and cache reuse.
  Prompt fingerprints should participate in request-reuse and cache-affinity
  decisions.

Do not copy blindly:

- A model catalog may choose how a personality fragment is serialized, but it
  must not determine Penguin's core identity or silently remove Soul
  invariants.
- Internal contextual messages need a clear visibility contract. They must not
  leak into the TUI as user dialogue or become misattributed during summaries.

### Hermes Agent

Relevant files:

- `reference/hermes-agent/agent/system_prompt.py`
- `reference/hermes-agent/agent/prompt_builder.py`
- `reference/hermes-agent/agent/prompt_caching.py`
- `reference/hermes-agent/website/docs/user-guide/features/personality.md`
- `reference/hermes-agent/website/docs/developer-guide/context-compression-and-caching.md`

Interesting takeaways:

- **Organize prompt material by cache stability.** Hermes divides the prompt
  into stable identity/tool guidance, contextual caller/project material, and
  volatile memory/session/runtime material. Penguin should formalize a similar
  `stable`, `scoped`, and `volatile` classification and keep volatile facts at
  the end of the request where provider caching benefits.
- **Separate Soul, project rules, and temporary personality.** Hermes uses
  `SOUL.md` for durable identity, `AGENTS.md` for project instructions, and a
  session personality overlay for temporary expression. This is the closest
  reference match to Penguin's proposed architecture.
- **Include guidance only for active tools.** Tool-specific prose is omitted
  when the tool is not loaded. Penguin should derive tool guidance and schemas
  from the same capability snapshot so the prompt never advertises unavailable
  actions.
- **Load local instructions with provenance and defenses.** Hermes discovers
  repository-local context files, strips metadata, applies size controls, and
  scans injected prompt files for suspicious instructions. Penguin should show
  the origin and status of every local overlay, and block or warn visibly
  rather than silently accepting promptware.
- **Keep provider cache controls pure and testable.** Hermes applies
  provider-specific cache markers without mutating the caller's messages. This
  is a useful boundary for Penguin's provider adapters.
- **Compact in stages.** Deterministic old-tool-output reduction before a
  structured model summary is a useful CWM v2 experiment, provided tool units
  remain atomic and the transformation is observable.

Do not copy blindly:

- Hermes documents a failure path where unsuccessful summarization can drop
  the middle of history without a valid summary. Penguin must fail visibly and
  preserve recoverable source history; it must never turn summary failure into
  silent information loss.
- Fixed compression percentages, protected-message counts, and file limits are
  implementation choices, not universal truths. Penguin should justify,
  measure, document, and expose any default context policy.
- A large novelty-personality catalog would make Penguin harder to evaluate.
  Establish one excellent default and a small set of behavioral overlays before
  considering decorative personas.

### OpenClaw / Clawdbot Snapshot

The local checkout is named `reference/clawdbot`; it represents the
OpenClaw/Clawdbot lineage available when this roadmap was written.

Relevant files:

- `reference/clawdbot/docs/concepts/system-prompt.md`
- `reference/clawdbot/docs/concepts/context.md`
- `reference/clawdbot/src/agents/pi-embedded-runner/system-prompt.ts`
- `reference/clawdbot/src/agents/system-prompt-report.ts`
- `reference/clawdbot/docs/reference/templates/SOUL.md`
- `reference/clawdbot/docs/reference/templates/IDENTITY.md`
- `reference/clawdbot/docs/reference/templates/USER.md`
- `reference/clawdbot/docs/reference/session-management-compaction.md`

Interesting takeaways:

- **Make context costs user-visible.** `/context list` and `/context detail`
  report the run-built system prompt, raw versus injected file sizes,
  truncation, skill-list overhead, and per-tool schema size. Penguin should
  offer an equivalent TUI/API diagnostic and distinguish measured request data
  from estimates.
- **Capture reports from the real run.** OpenClaw prefers the latest persisted
  run-built report and labels a reconstructed report as an estimate. This is a
  strong contract for Penguin's prompt and CWM diagnostics.
- **Use smaller prompts for specialist agents.** Subagents receive a minimal
  prompt without primary-agent identity, messaging, memory, and heartbeat
  material. Penguin should define specialist prompt profiles explicitly rather
  than send the full primary Penguin Soul everywhere.
- **Load skills on demand.** The base prompt contains compact skill metadata
  and file locations, while full skill instructions are read only when needed.
  The same progressive-disclosure pattern can reduce Penguin's steady prompt
  overhead.
- **Separate identity, user knowledge, and operating rules.** `SOUL.md`,
  `IDENTITY.md`, `USER.md`, and `AGENTS.md` have different owners and purposes.
  Penguin may not need four public files, but its internal schema should retain
  those provenance boundaries.
- **Keep cache-stable time data stable.** OpenClaw places the user timezone in
  the prompt and obtains the current clock through runtime status when needed.
  Penguin should avoid changing the stable prefix every second merely to expose
  time.
- **Treat Soul changes as observable.** The reference explicitly tells the
  agent to notify the user if it edits its Soul. Penguin should go further:
  persistent Soul changes require explicit user approval, versioning, and a
  visible diff.

Do not copy blindly:

- Per-file character ceilings such as `bootstrapMaxChars=20000` are useful
  safeguards but still require an explicit Penguin policy, truncation marker,
  diagnostic report, and configuration path.
- Silent `NO_REPLY` housekeeping and pre-compaction memory-flush turns add
  hidden state mutation and failure modes. Penguin should prefer explicit
  runtime events and deterministic persistence; any model-assisted maintenance
  must be observable in diagnostics even when it produces no chat message.
- Bootstrap hooks that can replace Soul or project files are powerful but
  enlarge the prompt-injection and reproducibility surface. Defer general hooks
  until composition provenance, authorization, fingerprints, and tests exist.
- Fragmenting configuration across many editable identity files can obscure
  precedence. Penguin should expose a coherent composition view even if it
  supports multiple storage sources.

### Cross-Reference Synthesis for Penguin

The recurring ideas above should become concrete roadmap requirements:

- [ ] Define a typed prompt-fragment registry with source, owner, precedence,
  visibility, cache class, token estimate, and policy version.
- [ ] Classify rendered sections as stable, scoped, or volatile and test their
  ordering for prompt-cache stability.
- [ ] Build a prompt/context inspector from the actual request assembly path,
  including prompt sections, injected files, tool schemas, provider overhead,
  truncations, and measured-versus-estimated labels.
- [ ] Keep Soul semantics shared while model/provider adapters control only
  serialization, protocol hints, and evidence-backed compatibility details.
- [ ] Persist mid-session composition changes as typed events and include them
  in replay, prompt fingerprints, and cache invalidation.
- [ ] Derive prompt tool guidance, exposed schemas, and enforced permissions
  from one immutable capability snapshot.
- [ ] Add instruction-precedence fixtures covering global Soul, user overlay,
  project instructions, session override, work mode, and runtime envelope.
- [ ] Give maintenance and specialist agents deliberately reduced prompts and
  capabilities instead of inheriting the full primary-agent prompt.
- [ ] Require all truncation, pruning, summarization, and local-file rejection
  to produce inspectable diagnostics and preserve a recoverable source of
  truth.
- [ ] Prohibit unconfigured goal/iteration/wall-clock ceilings from entering
  through agent profiles, provider adapters, or copied reference defaults.

The architectural principle is: borrow mechanisms that improve observability,
scope, and reproducibility; do not borrow another project's arbitrary policy.

## Recommended PR Sequence

1. **PR 74: Prompt composition and writing baseline**
   - Soul, engineering discipline, operating contract, work modes, overlays,
     response styles, compatibility presets, focused tests, and docs.

2. **Prompt composition state/service PR**
   - Immutable per-session composition, schema, fingerprints, section
     diagnostics, and removal of process-global canonical state.

3. **Prompt surface PR**
   - TUI/Web/CLI/Python API discovery and per-session configuration.

4. **Runtime envelope PR**
   - Typed date/time/OS/session/model/permission facts with privacy and cache
     tests.

5. **Prompt evaluation harness PR**
   - Golden matrix, fake-model scenarios, behavioral rubric runner, and prompt
     size/cache telemetry.

6. **CWM v2 PR(s)**
   - Context policy, deterministic tool-output slimming, assembler,
     summarization/compaction, retrieval, and simulations.

7. **Personalization and policy-versioning PRs**
   - Only after default behavior and measurement are mature.

The exact boundaries may change, but TUI controls, CWM v2, and behavioral
evaluation should not be folded into PR 74 merely because they all influence
what the model receives.

## Definition of Done for the Prompting Program

- Penguin has a reviewed, opinionated default Soul that users recognize across
  models and surfaces.
- Task intent, personality, capability, quality discipline, response style,
  runtime state, and context policy are distinct concepts in code and UI.
- Prompt selection is per session and concurrency-safe.
- Runtime permissions are enforceable independently of prompt text.
- TUI, Web API, CLI, and Python API share one typed discovery/configuration
  contract.
- Date/time/OS and other dynamic facts have a typed, privacy-reviewed runtime
  envelope.
- Prompt and context token accounting matches provider-visible requests closely
  enough to explain cost, latency, cache hits, and truncation.
- Structural, deterministic, behavioral, adversarial, and longitudinal tests
  detect regressions.
- CWM v2 can compact/select history without corrupting instructions or native
  tool protocol.
- Legacy prompt modes have a documented migration and removal path.
- Prompt changes can be compared, rolled back, and explained with versioned
  fingerprints and evidence.

## Immediate Review Questions

1. Is `work mode` the right user-facing term, or should the UI use a simpler
   label while retaining `WorkMode` internally?
2. Should `test` remain an internal work mode or become a quality overlay on
   `build`?
3. Should `complexity_review` be directly selectable, or offered as a named
   review preset that expands to `review + complexity_review`?
4. Should local personality customization initially support only an inline
   config overlay, or also a referenced Markdown file?
5. Which five to ten dogfood scenarios should become the first behavioral
   evaluation corpus?
6. Should prompt composition state be persisted in the session document or in
   a separate versioned session-settings record?
7. Which runtime-envelope fields are genuinely useful to the model, rather
   than merely useful to UI diagnostics?
