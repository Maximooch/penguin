# Penguin Prompt, Context, and Planning Overhaul

This document proposes a pragmatic overhaul of Penguin’s prompting, context assembly, and planning systems to reach and surpass Claude Code–style ergonomics while staying true to Penguin’s engineering-first ethos. It emphasizes deterministic behavior, safety, and fast feedback loops.

## Objectives
- P0: Deterministic prompt assembly with clear modes; safe, auditable edits; usable plans-as-data; dry-run by default.
- P1: Slot-based context assembler with token budgets; code-quality loop (lint/tests) integrated; lightweight subagents for review/run-tests.
- P2: Advanced retrieval heuristics and policies; hooks; future IDE selection context.

## Summary (First Principles)
- Prefer simple, composable rules over verbose personas.
- Encode “how to think and act” as small, testable prompt blocks.
- Treat context as a budgeted set of ranked slots, not an amorphous history.
- Plans are structured data that gate multi-file edits and anchor iteration.
- Safety is explicit: dry-run defaults, permission policy, and self-checks.

---

## Prompt Architecture

- Minimal core, modular assembly
  - Keep non-negotiables: safety, verify-before-act, action syntax, planning loop.
  - Remove heavy persona from the core; personality is opt-in via modes/profiles.
  - Include `MULTI_STEP_SECTION`, tool usage invariants, completion phrases, and context management as canonical blocks.

- Prompt builder
  - Introduce a composition layer (render-only) that assembles slots: core rules, tool usage, planning protocol, mode delta, project instructions, permission policy, and status-line hints.
  - Proposed files: `penguin/prompt/builder.py`, `penguin/prompt/profiles.py`.

- Modes (general + specific)
  - General: `default`, `explain`, `terse`, `review`, `learn`.
  - Specific: `implement`, `research`, `align` (can coexist with general modes; last write wins or combine additively where safe).
  - CLI/TUI: `/mode <name>` toggles prompt builder deltas (verbosity, structure, critic tone, output formatting expectations).

- Personality
  - Keep a light “Penguin DNA” by default (succinct, direct, friendly); persona flourishes are optional per mode/profile.
  - Personality is treated as a small mode delta, never diluting core safety/discipline.

- Tool invariants (authoritative, de-duplicated)
  - Acknowledge prior result, Verify → Act → Check, “no persistent cd”, “prefer apply_diff over overwrite”, backups and diffs, avoid destructive ops without confirmation.
  - Keep these in one canonical section referenced by builder.

- Reasoning controls
  - `/reflect` and a “reasoning budget” knob toggle `ModelConfig.reasoning_*`.
  - Builder adds a short “reflect” protocol when enabled (e.g., force a brief critic pass).

- Project instructions
  - Auto-load `PENGUIN.md` (repo root) and key `context/` files as a stable “Project Instructions” slot.
  - Summarize when large; include citations to paths.

---

## Context Engineering

- Context assembler pipeline (slots)
  - Priority-ordered slots with token budgets:
    1) System hard rules and tool invariants (highest)
    2) Task spec and acceptance criteria
    3) Current plan slice (top N actionable steps)
    4) Active diff under review or touched files summary
    5) Retrieval results (ranked snippets with path anchors)
    6) Project instructions (`PENGUIN.md`, docs excerpts)
    7) Conversation summaries (rolling, short)
    8) Diagnostics/status (tokens, model, budgets)
  - Deterministic merging, explicit budgets, and per-slot summarizers.

- Token budgeting and ranking
  - Extend `ContextWindowManager` to slot-aware budgeting with dynamic reallocation (mode-, phase-, and task-type aware).
  - Basic salience scoring: recency, filepath similarity to task/diff, dependency edges, and “touched” signal.

- Summarization and notes
  - Automatic micro-summaries after iterations; store “evidence bundles” (path + quoted lines) instead of long passages.
  - Keep a lightweight codebase map to bias retrieval (entry points, config, tests).

- Safety and policy-aware context
  - Directory allowlist/denylist; redact secrets; configurable “additionalDirectories”.
  - Respect permission policy for external fetch and sensitive file emission.

- IDE integration
  - Not prioritized now. Treat IDE active selection/open editors as a future slot.

---

## Planning System

- Plan as data
  - Pydantic model `Plan` with steps, dependencies, and verification checks; persisted at `context/PLAN.yaml` and surfaced in UI.
  - The assistant updates plan state before edits; diffs reference plan step IDs.

- Advisory gate (configurable)
  - “Plan required before multi-file edits” is advisory by default; enforceable via config.
  - The model must include a short “SELF_CHECK” prior to risky actions.

- Code quality loop
  - After edits, run lint/tests for touched paths (capped attempts N). If failures, triage and update the plan (next micro-step).

- Lightweight subagents
  - Reviewer (read-only, style/security checks) and Test Runner (exec tests; triage). Spawned via `Engine.spawn_child` with constrained prompts/tools.

---

## Permission Policy and Safety

- Policy model
  - `allow/ask/deny` per operation category (Bash, Edit, Read, WebFetch, Network, Git), per path/domain patterns.
  - Default safe: dry-run for write/edit; ask for destructive or cross-boundary ops.

- Dry-run default
  - All write tools run in dry-run by default, emitting planned diffs and summaries; “apply” requires explicit confirmation or CI `--assume-yes`.

- Config integration
  - Centralized config merges global/user/project/local overrides; permission engine reads effective policy.

---

## Changes by File (Proposed)

- `penguin/system_prompt.py`
  - Replace static `SYSTEM_PROMPT` construction with prompt builder output.
  - Keep core minimal; personality via profile/mode deltas.

- `penguin/prompt_workflow.py`
  - Canonical blocks: core principles, multi-step process, completion phrases, tool usage, context management, large-codebase guidance.
  - Split into importable sections consumed by builder.

- `penguin/prompt_actions.py`
  - Authoritative action syntax and invariants (single source of truth). Trim duplication.

- `penguin/system/context_loader.py`
  - Load `PENGUIN.md` and configured `context/` files for “Project Instructions” slot.

- `penguin/system/context_window.py`
  - Add slot budgets and ranking hooks; export standardized usage for status line and Engine stop-conditions.

- `penguin/core.py`, `penguin/engine.py`
  - Inject mode/phase into builder; enable token-budget stop where useful. Preserve stream → finalize → tool-result ordering.

- `penguin/run_mode.py`
  - Gate multi-file edits on plan presence (advisory by default). Publish status updates for TUI (model, tokens, phase).

- New modules
  - `penguin/prompt/builder.py` – Prompt assembly orchestrator.
  - `penguin/prompt/profiles.py` – Pydantic models for PromptProfile/ModeProfile/ContextProfile.
  - `penguin/system/context_assembler.py` – Slot-based assembler feeding `ConversationManager`.
  - `penguin/cognition/planning.py` – `Plan` model + persistence helpers.

---

## Modes (Details)

- General modes: `default`, `explain`, `terse`, `review`, `learn`.
- Specific modes: `implement`, `research`, `align`.
- Combination rules: apply general then specific deltas; conflicts resolved by specific mode (or last applied).
- Example deltas
  - `terse`: fewer narrative lines, keep headlines and fenced code; suppress optional commentary.
  - `review`: add checklists, risk callouts, STRICT diffs with justifications.
  - `implement`: prioritize actionable diffs; enforce code-quality loop.
  - `research`: permit `web.fetch` within policy; require source citations.
  - `align`: reflect on acceptance criteria and restate plan before acting.

---

## Configuration (Sketch)

```yaml
modes:
  default: terse+implement  # composition supported
  enabled: [default, explain, terse, review, learn, implement, research, align]

edits:
  dry_run_default: true
  require_plan_for_multiedit: advisory   # values: off|advisory|enforced

permissions:
  default: ask
  allow:
    - op: Read
      paths: ["./**"]
    - op: Edit
      paths: ["src/**", "penguin/**"]
  ask:
    - op: Bash
      commands: ["pytest", "ruff"]
  deny:
    - op: Network
      domains: ["*"]

context:
  slots:
    system: {budget: 0.1}
    task: {budget: 0.1}
    plan: {budget: 0.15}
    diffs: {budget: 0.15}
    retrieval: {budget: 0.25}
    project_instructions: {budget: 0.1}
    summaries: {budget: 0.1}
    diagnostics: {budget: 0.05}
```

---

## Implementation Roadmap

- Phase 1 (P0)
  - Prompt builder + profiles; rewire `SYSTEM_PROMPT` to include workflow and tool guidance.
  - Modes: implement `default|explain|terse|review|learn|implement|research|align` as deltas; `/mode` in CLI.
  - Plan model + `context/PLAN.yaml`; advisory gate for multiedit; dry-run default for write tools.
  - Context assembler skeleton with fixed slots and budgets; load `PENGUIN.md`.

- Phase 2 (P1)
  - Ranking heuristics, dynamic reallocation; code-quality loop (ruff/pytest) with capped retries; subagents (Reviewer, Test Runner).
  - Status line feed (tokens, model, budgets) for TUI; permission policy enforcement paths.

- Phase 3 (P2)
  - Advanced retrieval (dependency graph, blame/log signals); configurable hooks; managed enterprise policy.
  - Future: IDE selection/open editors as a first-class slot.

---

## Success Criteria
- Prompt assembly is deterministic; switching modes predictably changes tone/format without breaking safety rules.
- Edits default to dry-run with clear diff previews; “apply” requires confirmation (or CI flag).
- Multi-file edits are preceded by a visible plan with step IDs and verification checks.
- Post-edit code-quality loop runs on touched files; failures surface with next-step updates in plan.
- Context fits budget via slots; assembler can show how many tokens went to each slot.
- Permission policy is respected and observable (logs and UI summaries).

---

## Risks and Mitigations
- Too many modes → confusion: ship small, opinionated defaults and concise help.
- Builder drift → conflicting deltas: keep deltas minimal; test assembly snapshots in CI.
- Over-trimming context → lost detail: preserve evidence bundles and project instructions; allow manual include.

---

## Future Considerations
- IDE integrations (VS Code/JetBrains): active selection and open editors as high-priority context slots; inline diff apply UX.
- Multi-user and managed policy layers: enforced deny rules and audit logs.
- Deeper retrieval: PR history, blame, test coverage maps to guide salience.

---

## Notes From Maintainer Q&A
- Modes: include both general and specific (`implement`, `research`, `align`) alongside `default|explain|terse|review|learn`.
- Personality: keep a small amount of Penguin’s old personality DNA as default; persona is otherwise optional via profiles.
- Plan gate: advisory by default with a config toggle to enforce.
- IDE selection context: defer to future considerations (not in initial scope).
- Dry-run default: Yes; behavior governed by the permission engine config.

---

## Quick Start (Developer Checklist)
- Add builder and profiles; rewire `SYSTEM_PROMPT`.
- Implement `/mode` CLI and simple deltas.
- Introduce `Plan` model; persist `context/PLAN.yaml` and gate multiedit (advisory).
- Switch write tools to dry-run by default; add “apply” confirmation.
- Create context assembler skeleton; add `PENGUIN.md` and fixed slots with budgets.

