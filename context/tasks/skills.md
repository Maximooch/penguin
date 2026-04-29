# Penguin Skills Integration

## Status

MVP runtime and first CLI UX slice implemented in this branch. Web API, TUI, package-manager distribution, and eval runner remain deferred.

## Work Checklist

### Discovery And Planning

- [x] Cache Agent Skills documentation under `context/docs_cache/agent_skills/`.
- [x] Review Agent Skills specification and client implementation guidance.
- [x] Map Penguin integration points for tools, context injection, config, and context-window truncation.
- [x] Document package-manager distribution tradeoffs for `pip`, `uv`, `npm`, `npx`, git/archive, and OCI.
- [x] Create this task brief at `context/tasks/skills.md`.

### MVP Runtime

- [x] Add `penguin/skills/models.py`.
- [x] Add `penguin/skills/parser.py` with `SKILL.md` frontmatter validation.
- [x] Add parser tests for valid skills, missing fields, invalid names, long descriptions, malformed YAML, and optional fields.
- [x] Add `penguin/skills/discovery.py` for configured user/project scan paths.
- [x] Add discovery tests for nested skills, invalid skills, collisions, max depth, and disabled project trust.
- [x] Add `SkillManager` for catalog state, activation lookup, diagnostics, and per-session dedupe.
- [x] Add structured activation renderer with `<skill_content>` and `<skill_resources>`.
- [x] Add `list_skills` tool.
- [x] Add `activate_skill` tool.
- [x] Register skill tools in `ToolManager` registry and schema list.
- [x] Inject compact skill catalog into startup/session context.
- [x] Load activated skill content as `MessageCategory.CONTEXT` messages with skill metadata.
- [x] Add tests for activation dedupe and CONTEXT-category truncation behavior.

### CLI And UX

- [x] Add `penguin skill list`.
- [x] Add `penguin skill show <name>`.
- [x] Add `penguin skill activate <name>`.
- [x] Add `penguin skill doctor`.
- [x] Surface invalid skill diagnostics clearly.
- [x] Document manual install by copying folders into `~/.penguin/skills` or `.penguin/skills`.

### Prompting And Agent Behavior

- [x] Document skill-use rules in the generated tool guide.
- [x] Add workflow guidance for when to activate skills from explicit mentions or matching descriptions.
- [x] Instruct Penguin to activate the minimal relevant skill set, not every available skill.
- [x] Clarify activated skills are `CONTEXT`, not `SYSTEM`, and lower priority than Penguin's system/developer instructions.
- [x] Instruct Penguin to load referenced skill files progressively instead of bulk-loading resources.
- [x] Add prompt regression tests covering skill tool docs and workflow guidance.

### Web API Interface

- [x] Add `GET /api/v1/skills` for compact catalog and diagnostics.
- [x] Add `GET /api/v1/skills/{name}` for full `SKILL.md` inspection without activation.
- [x] Add `POST /api/v1/skills/{name}/activate` to load skill content as session-scoped `CONTEXT`.
- [x] Include duplicate activation status and skill metadata in activation responses.
- [x] Surface invalid skill diagnostics in structured JSON for web clients.
- [x] Emit SSE/OpenCode-compatible events when skills are activated or diagnostics change.

### TUI Interface

- [ ] Add a Skills panel/list using the web/API catalog endpoint.
- [ ] Show invalid skill diagnostics with actionable file paths and validation errors.
- [ ] Add explicit activation action that calls the web/API activation endpoint.
- [ ] Show whether a skill is already active in the current session.
- [ ] Display manual install guidance for user/project skill folders.
- [ ] Avoid auto-activating skills from UI selection; require explicit user action.

### Security And Trust

- [ ] Add config defaults for `skills.enabled`, scan paths, max scan depth, max skill dirs, and project-skill trust.
- [ ] Ensure project skills are disabled or require explicit trust by default.
- [ ] Ensure relative skill resource paths cannot escape the skill directory.
- [ ] Parse `allowed-tools` as advisory metadata only.
- [ ] Verify skill scripts still go through normal Penguin command/file/network permission gates.

### Deferred Distribution

- [ ] Add `penguin skill install <local-path|git-url>`.
- [ ] Evaluate Python entry point discovery via `penguin.skills`.
- [ ] Prototype optional `npx` installer that copies static skill directories into Penguin's user skill path.
- [ ] Decide whether installed package skills should be copied into Penguin-controlled storage or referenced in place.
- [ ] Defer marketplace/registry design until local usage proves demand.

### Evals Later

- [ ] Add `penguin skill eval <name>`.
- [ ] Support `evals/evals.json` test case discovery.
- [ ] Run with-skill and baseline/no-skill comparisons in isolated sessions or subagents.
- [ ] Capture token and duration metrics.
- [ ] Grade assertions with scripts where possible and LLM judges where needed.
- [ ] Add description trigger eval support.

## Background

Agent Skills define a portable convention for packaging agent instructions and reusable resources:

```text
skill-name/
├── SKILL.md      # required: YAML frontmatter + Markdown instructions
├── scripts/      # optional executable helpers
├── references/   # optional detailed docs loaded on demand
├── assets/       # optional templates/resources
└── ...
```

Cached docs from `https://agentskills.io/home` live in `context/docs_cache/agent_skills/`.

Useful cached references:

- `context/docs_cache/agent_skills/specification.md`
- `context/docs_cache/agent_skills/client-implementation_adding-skills-support.md`
- `context/docs_cache/agent_skills/skill-creation_best-practices.md`
- `context/docs_cache/agent_skills/skill-creation_using-scripts.md`
- `context/docs_cache/agent_skills/skill-creation_evaluating-skills.md`
- `context/docs_cache/agent_skills/skill-creation_optimizing-descriptions.md`

## Core Thesis

Penguin should support Skills as a runtime capability, not just as prompt text.

Minimum useful flow:

1. Discover installed skills from configured directories.
2. Parse `SKILL.md` frontmatter into a compact catalog.
3. Expose only skill `name` + `description` at startup.
4. Activate a skill on demand through a dedicated tool.
5. Inject full skill instructions using structured tags.
6. List bundled resources without eagerly loading them.
7. Load activated skill instructions as `CONTEXT` messages, not `SYSTEM` messages.
8. Deduplicate already-activated skills per session.

Do not start with marketplaces, auto-install, or fancy package-manager support. Those are distribution questions layered on top of a local runtime contract.

## Penguin vs Codex Skills Comparison

Codex's local Skills support provides a useful reference implementation, but Penguin should not copy it blindly because Penguin has a different runtime shape: explicit tool orchestration, persistent conversations, context categories, and multi-agent execution.

### Codex Reference Behavior

Observed local reference files:

- `reference/codex/codex-rs/core/src/context/available_skills_instructions.rs`
- `reference/codex/codex-rs/core/src/context/skill_instructions.rs`

Codex does two important things:

1. It injects an available-skills developer-context block that lists skill name, description, and file path, plus trigger rules and progressive-disclosure instructions.
2. It wraps activated skill content as a separate user-context fragment under `<skill>` with `<name>`, `<path>`, and the skill body.

Codex's trigger model is explicit: use a skill when the user names it with `$SkillName`/plain text or when the task clearly matches a listed description. It also instructs the agent not to bulk-load `references/`, to resolve relative paths from the skill directory, and to use scripts/assets when relevant.

### Penguin Current Approach

Penguin's implementation is similar in intent but more runtime-oriented:

- Skill discovery and validation live under `penguin/skills/`, not only in prompt text.
- The compact skill catalog is injected into startup/session context.
- Activation goes through dedicated native tools: `list_skills` and `activate_skill`.
- Activated skill content is loaded as `MessageCategory.CONTEXT`, not `SYSTEM`.
- Activation is deduped per session by `SkillManager`.
- Activation output uses structured `<skill_content>` and `<skill_resources>` wrappers.
- Skill scripts still go through normal Penguin command/file/network permission gates.

This is the right divergence. Codex can rely heavily on file-read instructions because its reference implementation exposes file paths directly in contextual instructions. Penguin benefits from dedicated tools because it can attach metadata, dedupe activations, feed context-window accounting, and later emit web/TUI events.

### Practical Differences

| Area | Codex Reference | Penguin MVP |
|---|---|---|
| Catalog disclosure | Developer-context skill list with file paths | Compact skill catalog injected as `CONTEXT` |
| Activation path | Open `SKILL.md` or contextual injection | Dedicated `activate_skill` tool |
| Activated content rank | User-context `<skill>` fragment | `MessageCategory.CONTEXT` message |
| Dedupe | Runtime injection state in Codex skill system | Per-session `SkillManager` activation tracking |
| Resource loading | Progressive file reads from paths | Resources listed; normal file tools load specific files |
| Security posture | Prompt rules plus client file/tool policy | Prompt rules plus Penguin permission gates |
| UI/API future | Codex-specific client surface | CLI done; web/API and TUI explicitly deferred |

### Gap To Watch

Penguin now has prompt guidance equivalent to Codex's trigger/progressive-disclosure rules, but the web/API and TUI still need first-class skill visibility. Until those surfaces are implemented, CLI and model-tool usage are the strongest paths.


## Proposed Architecture

Add `penguin/skills/`:

- `models.py`
  - `Skill`
  - `SkillCatalogEntry`
  - `SkillResource`
  - `SkillDiagnostic`
- `parser.py`
  - parse/validate `SKILL.md`
  - support YAML frontmatter
  - collect diagnostics without crashing the whole scan
- `discovery.py`
  - scan configured paths
  - enforce max depth and directory count
  - identify `SKILL.md` roots
- `manager.py`
  - maintain catalog
  - resolve name collisions
  - track activated skills per session/agent
  - render activation payloads
- `renderer.py`
  - compact catalog prompt text
  - structured `<skill_content>` activation wrapper
- `evals.py` later
  - trigger evals
  - output evals
  - baseline comparisons

## Tool Integration

Add native tools:

- `list_skills`
  - returns compact catalog and diagnostics
- `activate_skill`
  - input: `name`
  - returns structured skill content and resource listing
- optional later: `skill_resources`
  - returns resource listing for a skill without activation

Current hook points:

- Tool registry: `penguin/tools/tool_manager.py`
- Tool schema definitions: `ToolManager._define_tool_schemas()`
- Conversation context insertion: `penguin/system/conversation.py`
- Context-window truncation policy: `penguin/system/context_window.py`

## Activation Payload Shape

Use structured wrapping so the model and context manager can distinguish durable skill instructions from ordinary tool output:

```xml
<skill_content name="csv-analyzer">
# CSV Analyzer

[SKILL.md body]

Skill directory: /absolute/path/to/skill
Relative paths in this skill are relative to the skill directory.

<skill_resources>
<file>scripts/analyze.py</file>
<file>references/schema.md</file>
<file>assets/report-template.md</file>
</skill_resources>
</skill_content>
```

Resource files should be listed, not eagerly read. The agent can use normal file-read tools when the skill instructions tell it to load a specific file.

## Config Sketch

```yaml
skills:
  enabled: true
  trust_project_skills: false
  scan_paths:
    project:
      - .penguin/skills
      - .agents/skills
    user:
      - ~/.penguin/skills
      - ~/.agents/skills
      - ~/.claude/skills
  max_scan_depth: 6
  max_skill_dirs: 2000
  activation:
    dedicated_tool: true
    include_frontmatter: false
    list_resources: true
    max_resources: 200
```

Use existing config precedence: package defaults, user config, project config, project local overrides, `PENGUIN_CONFIG_PATH`.

## Security Model

Default stance: local skills are instruction bundles, not trusted code.

Rules:

- Do not auto-activate project skills from an untrusted repository.
- User-level skill directories can be enabled by default, but executable scripts remain governed by normal Penguin tool/security policy.
- Parse `allowed-tools` if present, but treat it as advisory until Penguin has a clear enforcement model.
- Skill scripts should not bypass `execute_command`, filesystem, network, or approval gates.
- Relative paths in skills must resolve inside the skill directory unless explicitly allowed.
- Name collisions should be surfaced clearly; deterministic precedence is mandatory.

## Context Window Requirements

Penguin does not have generic context compaction. Its `ContextWindowManager` performs category-based truncation: oldest messages in over-budget categories are trimmed first, while `SYSTEM` is preserved.

Skills should be loaded as `MessageCategory.CONTEXT` messages. They are reusable task instructions and references, but they are not as important as Penguin's agent system prompt and should not rank as `SYSTEM`.

Required changes:

- Add activated skill content through the existing context path, with metadata such as `{"type": "skill", "skill_name": "...", "skill_path": "..."}`.
- Keep skills in the normal `CONTEXT` budget/truncation lane unless empirical usage shows a separate sub-budget is needed.
- Do not create `MessageCategory.SKILL` for MVP.
- Do not append activated skills to the system prompt.
- Deduplicate activations so the same skill is not injected repeatedly.
- Add observability for when activated skill context is truncated, using existing truncation tracking patterns.
- If skill loss during long sessions becomes a practical issue, consider reactivation hints or a CONTEXT sub-budget later. Do not prematurely special-case it.

## Package Manager Distribution

Package-manager installation is possible, but should be deferred until the local runtime contract is stable.

Important distinction:

- **Skills format**: local directory with `SKILL.md` and optional resources.
- **Skills distribution**: how that directory gets onto disk.

Penguin is Python, but skill distribution is ecosystem-neutral if the final artifact is a directory. Installation can be handled by many package systems.

### Possible Distribution Channels

#### Python / pip

Examples:

```bash
pip install penguin-skill-csv-analyzer
uv tool install penguin-skill-csv-analyzer
```

A Python package could expose installed skill paths via entry points:

```toml
[project.entry-points."penguin.skills"]
csv-analyzer = "penguin_skill_csv:path"
```

Penguin would discover entry points, resolve package resource paths, and add them to the skill catalog.

Pros:

- Native fit for Penguin.
- Works with `pip`, `uv`, and Python packaging metadata.
- Can support lockfiles and enterprise mirrors.

Cons:

- Less natural for JS/TS skill authors.
- Python package resource paths can be awkward, especially for editable installs and zipped packages.

#### npm / npx

Examples:

```bash
npm install -g @penguin-skills/csv-analyzer
npx @penguin-skills/install csv-analyzer
```

Possible designs:

1. Global npm package installs skill files to an npm package directory, then Penguin discovers them through a generated registry file.
2. `npx` installer copies a skill directory into `~/.penguin/skills/<name>`.
3. A package exposes a manifest field pointing to skill directories.

Pros:

- Natural for frontend/web ecosystem skills.
- Easy one-shot installers with `npx`.
- Large package registry and existing versioning workflows.

Cons:

- Penguin would need cross-runtime discovery rules.
- Global npm paths vary by platform and toolchain.
- Running `npx` at activation time would be a security and reproducibility footgun.

Recommendation: if npm support is added, prefer `npx ... install` copying static files into `~/.penguin/skills/`, not dynamic runtime loading from arbitrary npm paths.

#### Standalone Git / Archive Install

Examples:

```bash
penguin skill install https://github.com/org/skill-repo
penguin skill install ./local-skill
penguin skill install skill.tar.gz
```

Pros:

- Ecosystem-neutral.
- Simple mental model.
- Good MVP after local discovery.

Cons:

- Needs checksum/signature story eventually.
- Needs update/remove metadata.

#### OCI / Artifact Registry Later

A skill bundle could be published as an OCI artifact.

Pros:

- Enterprise-friendly.
- Versioned, immutable, mirrorable.

Cons:

- Overkill for MVP.
- More moving parts than the feature deserves right now.

### Package Manager Recommendation

Defer package-manager installs.

Build the local substrate first:

1. Stable skill directory contract.
2. Parser/discovery/activation tools.
3. CONTEXT-category truncation observability.
4. CLI `skill list/show/activate/doctor`.
5. Manual install by copying folders into `~/.penguin/skills` or project `.penguin/skills`.

Then add distribution in this order:

1. `penguin skill install <local-path|git-url>`
2. Python entry point discovery via `penguin.skills`
3. Optional `npx` installer that copies skills into Penguin’s user skill directory
4. Registry/marketplace only after real usage proves the need

Bluntly: package manager support before runtime semantics is yak shaving with better branding.

## CLI Surface

Initial commands:

```bash
penguin skill list
penguin skill show <name>
penguin skill activate <name>
penguin skill doctor
```

Later:

```bash
penguin skill create <name>
penguin skill install <source>
penguin skill remove <name>
penguin skill eval <name>
penguin skill optimize-description <name>
```

## Evals

Use Agent Skills' eval pattern:

- `evals/evals.json` inside the skill directory.
- Each test case has prompt, expected output, optional files, later assertions.
- Run with and without skill, or current skill vs previous snapshot.
- Capture timing/token data.
- Grade assertions with scripts where possible, LLM judge where necessary.
- Use Penguin subagents to isolate each eval run.

This is a strong fit for Penguin's multi-agent runtime.

## Acceptance Criteria For MVP

- Penguin discovers valid skills from configured user/project paths.
- Invalid skills produce diagnostics, not crashes.
- Startup context includes compact skill catalog only.
- `activate_skill` injects full skill content once per session.
- Activation output lists resources without eager loading.
- Activated skill content is stored as `CONTEXT` with skill metadata.
- Project skills are disabled or require trust by default.
- Tests cover parser, discovery, collision behavior, activation dedupe, and CONTEXT-category truncation behavior.

## Non-Goals For MVP

- Public skill marketplace.
- Automatic remote install.
- Runtime execution through npm/npx/pip.
- Cross-machine sync.
- Full `allowed-tools` enforcement.
- UI-heavy skill browser.

## Open Questions

- Should the compact skill catalog be injected as one `CONTEXT` message or split into smaller per-skill `CONTEXT` messages for better truncation behavior?
- Should activated skill messages receive a small reserved CONTEXT sub-budget later, or is normal CONTEXT truncation acceptable?
- What is the cleanest trust UX for project skills?
- Should `allowed-tools` narrow available tools during skill execution, or only annotate expected tools?
- How should skill activation behave in shared-context subagents?
- Should installed package skills be copied to a Penguin-controlled directory or referenced in-place?

## First Implementation Slice

1. Implement `penguin/skills/parser.py` and tests.
2. Implement local discovery for `~/.penguin/skills` and `.penguin/skills`.
3. Add `SkillManager` with activation dedupe.
4. Add `list_skills` and `activate_skill` tools.
5. Add compact catalog injection.
6. Load activated skills as `CONTEXT` messages with skill metadata and truncation observability.
7. Add `penguin skill list/show/doctor` CLI commands.

Keep it boring. Boring means shippable.
