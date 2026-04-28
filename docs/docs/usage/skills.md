---
sidebar_position: 6
---

# Agent Skills

Penguin includes an initial Agent Skills runtime for discovering reusable instruction bundles from local folders and loading selected skills into a conversation.

Skills are based on the portable Agent Skills convention: each skill is a directory with a required `SKILL.md` file containing YAML frontmatter plus Markdown instructions.

```text
my-skill/
├── SKILL.md      # required: frontmatter + instructions
├── scripts/      # optional helper scripts
├── references/   # optional detailed docs
└── assets/       # optional templates/resources
```

## Current Status

Implemented so far:

- Local skill discovery from configured user/project scan paths
- `SKILL.md` frontmatter validation
- Compact skill catalog loading as `MessageCategory.CONTEXT`
- Explicit skill activation through runtime tools
- Activated skill content loaded as `MessageCategory.CONTEXT`
- Per-session activation dedupe
- CLI commands for listing, inspecting, activating, and diagnosing skills

Not implemented yet:

- Web API skill endpoints
- TUI skill panel/actions
- Package-manager based skill installation
- Skill eval runner
- Automatic skill-trigger heuristics

## Skill File Format

A minimal valid skill:

```markdown
---
name: csv-cleanup
description: Clean, validate, and summarize CSV files.
---

# CSV Cleanup

Use this skill when the user asks to clean or analyze CSV data.

1. Inspect the CSV headers.
2. Check for missing values and inconsistent types.
3. Produce a cleaned output file and a short summary.
```

Required frontmatter fields:

| Field | Notes |
|---|---|
| `name` | Stable skill identifier. Use a lowercase slug such as `csv-cleanup`. |
| `description` | Short catalog description used to help decide when the skill is relevant. |

Optional frontmatter fields may be preserved as metadata. `allowed-tools`, when present, is treated as advisory metadata only; it does not bypass Penguin's normal tool permissions.

## Manual Installation

For now, install skills by copying folders into a local skill directory:

```bash
# User-level skills
mkdir -p ~/.penguin/skills
cp -R ./my-skill ~/.penguin/skills/my-skill

# Project-level skills
mkdir -p .penguin/skills
cp -R ./my-skill .penguin/skills/my-skill
```

Project skills are intentionally trust-sensitive. Penguin should not treat arbitrary repository-owned instructions as trusted just because a folder exists. Enable or trust project skill loading deliberately in configuration when using project-local skills.

## CLI Commands

Skills are exposed through the headless CLI command group:

```bash
# List discovered skills and diagnostics
penguin-cli skill list
penguin-cli skill list --json

# Show full SKILL.md content for a discovered skill
penguin-cli skill show csv-cleanup
penguin-cli skill show csv-cleanup --json

# Activate a skill for the current runtime session
penguin-cli skill activate csv-cleanup
penguin-cli skill activate csv-cleanup --show-content
penguin-cli skill activate csv-cleanup --json

# Validate discovered skill directories and show install guidance
penguin-cli skill doctor
penguin-cli skill doctor --json
```

The default `penguin` launcher now routes the `skill` subcommand to the headless CLI path, so `penguin skill list` also works. For scripts, prefer `penguin-cli` because it is explicitly non-interactive.

## Runtime Behavior

At startup/session initialization, Penguin loads a compact skill catalog into conversation context when valid skills are found. The catalog contains the skill names, descriptions, sources, and paths. It does **not** load full instruction bodies.

When a skill is activated, Penguin renders structured content similar to:

```xml
<skill_content name="csv-cleanup">
...
</skill_content>
<skill_resources>
...
</skill_resources>
```

That rendered activation is added as a `MessageCategory.CONTEXT` message with skill metadata. Skills are not loaded as system prompts and do not outrank Penguin's system instructions.

Penguin's context window manager uses category-based truncation. Since skills are `CONTEXT`, old skill catalog/activation messages can be truncated under normal `CONTEXT` pressure. That is intentional for the MVP; future work may add richer observability or a reserved `CONTEXT` sub-budget if real usage proves it is needed.

## Tool Interface

The runtime exposes two model-callable tools:

| Tool | Purpose |
|---|---|
| `list_skills` | Return the current skill catalog and validation diagnostics. |
| `activate_skill` | Load a named skill into the active session as `CONTEXT`. |

Activation is explicit and deduped per session. Re-activating the same skill returns an `already_active` style result instead of repeatedly appending duplicate context.

## Diagnostics

Invalid skills are not silently ignored. Parser/discovery diagnostics include severity, code, source, path, and message. Use:

```bash
penguin-cli skill doctor
```

to inspect malformed frontmatter, invalid names, missing required fields, collisions, and ignored project skills.

## Security Notes

Skills are instruction bundles, not permission grants.

- Do not auto-trust project skills from arbitrary repositories.
- Treat `allowed-tools` as a hint, not an authorization bypass.
- Scripts inside skill folders still need to go through Penguin's normal command/file/network permission model.
- Package-manager installation is deferred; install by copying folders until local runtime semantics are stable.

## Planned Interfaces

### Web API

Planned endpoints:

- `GET /api/v1/skills` for compact catalog and diagnostics
- `GET /api/v1/skills/{name}` for full `SKILL.md` inspection without activation
- `POST /api/v1/skills/{name}/activate` to load skill content into a session as `CONTEXT`

### TUI

Planned TUI work:

- Skills catalog panel
- Invalid skill diagnostics display
- Explicit activation action
- Active/already-active status per session
- Manual install guidance

The TUI should not auto-activate a skill merely because the user selected it. Activation should remain explicit.
