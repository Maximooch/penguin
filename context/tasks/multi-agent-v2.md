# Multi-Agent v2

Date: 2026-05-30
Branch: `main`
Status: draft task brief
Owner: Maximus / Penguin
Scope: `penguin/core.py`, `penguin/system/conversation_manager.py`, `penguin/multi/`, `penguin/tools/tool_manager.py`, `penguin/utils/parser.py`, `penguin/web/routes.py`, CLI/TUI/API docs

## Summary

Penguin already has useful sub-agent primitives: named agent conversations, isolated/shared context modes, background execution through `AgentExecutor`, and lightweight `MessageBus` routing.

The v1 surface works, but it has three sharp edges that will hurt users and future maintainers:

1. The public docs imply richer per-agent configuration than the current core path reliably enforces.
2. Stop/resume semantics are muddled between executor cancellation, pause metadata, and actual agent execution control.
3. Agent communication is push-only and mostly ephemeral, so delegation can look successful even when no recipient is truly listening.

Multi-Agent v2 should first close those truth gaps. Later improvements can add nicer orchestration, richer UI affordances, and higher-level planner/implementer/QA workflows. Do not build agent theater on a shaky floor.

## Current Runtime Truth

### Implemented Today

- `spawn_sub_agent` creates a child agent linked to a parent.
- Child agents can share the parent session, share only the parent context window, or use an isolated session/context window.
- Isolated child sessions receive copied `SYSTEM` and `CONTEXT` messages from the parent at creation time.
- `background=true` runs the child prompt via `AgentExecutor`.
- `get_agent_status` and `wait_for_agents` query the global background executor.
- `delegate(background=true)` runs a background task for an existing child through `AgentExecutor`.
- `delegate(background=false)` sends a message through `core.send_to_agent` / `MessageBus`.
- `send_message` publishes a `ProtocolMessage` to `MessageBus` and UI observers.
- `delegate_explore_task` is a special lightweight exploration loop, not a full persistent sub-agent session.

### Known Drift Between Docs And Code

- `architecture.md` still shows `core.register_agent(...)`, but `PenguinCore.register_agent()` now raises `NotImplementedError`; the current API is `ensure_agent_conversation()` / `create_sub_agent()`.
- `persona`, `model_config_id`, `model_overrides`, `model_output_max_tokens`, and `default_tools` are accepted by the tool schema, but the current `core.create_sub_agent(..., **kwargs)` path mostly ignores legacy kwargs except `system_prompt`.
- `default_tools` is described as available to a sub-agent, but current tool isolation is not clearly enforced as a security/runtime boundary.
- `stop_sub_agent` says pause/cancel in different places. In practice it cancels background executor work when possible and marks conversation metadata as paused.
- `resume_sub_agent` clears pause metadata, but does not restart a cancelled background task.
- `MessageBus` delivery is best-effort push routing. If no handler is registered, the message is effectively dropped after event fan-out/logging.
- `delegate_explore_task` branding can imply a normal sub-agent, but it currently uses a separate OpenRouter/Haiku loop with tiny local tools.

## Goals

1. Make agent configuration truthful and enforceable.
2. Separate lifecycle concepts: pause, cancel, resume, restart, delete.
3. Make delegation observable: callers should know whether a recipient existed, accepted work, completed work, or never handled the message.
4. Align docs, prompt instructions, CLI, TUI, web API, and code around one multi-agent contract.
5. Preserve simple workflows: spawning an isolated helper should remain easy.
6. Add regression tests for the exact blind spots before layering bigger orchestration.

## Non-Goals

- Do not build a full distributed actor framework.
- Do not invent autonomous agent societies before the lifecycle contract is correct.
- Do not require every sub-agent to run in the background.
- Do not make sub-agent context semantics special-case CWM v2; sub-agents should inherit normal context policy with explicit overrides/clamps.
- Do not promise tool sandboxing until tool access is actually enforced.

## Phase 0: Contract Audit And Vocabulary

### Deliverables

- Define canonical terms in one doc/source section:
  - agent
  - sub-agent
  - session sharing
  - context-window sharing
  - isolated session
  - background task
  - delegation
  - message
  - pause
  - cancel
  - resume
  - restart
- Update `architecture.md`, README references, prompt actions, CLI help, and web/API docs to match runtime truth.
- Replace stale `core.register_agent(...)` examples with `ensure_agent_conversation()` / `create_sub_agent()` or public API equivalents.

### Acceptance Criteria

- Grep for `core.register_agent(` in docs returns no public examples except migration notes.
- Public docs clearly state which fields are enforced vs metadata-only.
- `delegate_explore_task` is documented as a lightweight explorer, not a persistent normal sub-agent.

## Phase 1: Enforce Or Remove Sub-Agent Configuration Fields

Current schema accepts fields that are not reliably wired through. That is worse than not supporting them.

### Field Decisions

| Field | Desired v2 Behavior |
|---|---|
| `system_prompt` | Enforced immediately on child conversation. |
| `persona` | Either resolve to prompt/model/tool policy or reject with clear unsupported error. |
| `model_config_id` | Either create agent-scoped runtime model config or reject with clear unsupported error. |
| `model_overrides` | Same as above; no silent ignore. |
| `model_output_max_tokens` | Enforce on child LLM calls or reject. |
| `default_tools` | Enforce through tool policy or rename to `tool_hints` metadata. |
| `shared_context_window_max_tokens` | Keep; verify isolated CWM clamp behavior and tests. |

### Implementation Notes

- Prefer fail-fast validation over silent metadata sinks.
- Add a normalized `AgentProfile` / `AgentRuntimeConfig` boundary if one does not already own this cleanly.
- If full per-agent model/tool config is too large for the first PR, explicitly reject unsupported fields with actionable messages.

### Acceptance Criteria

- Spawning with unsupported config returns a structured error, not `status=ok`.
- Spawning with supported config changes the actual child runtime behavior in tests.
- Tests cover each public field in `spawn_sub_agent` schema.

## Phase 2: Lifecycle Semantics

The current lifecycle vocabulary is overloaded. Fix the contract.

### Proposed Semantics

| Operation | Meaning |
|---|---|
| `pause_sub_agent` | Mark agent unavailable for new delegated work; do not kill active background task unless explicitly requested. |
| `cancel_agent_task` | Cancel an active background task. |
| `resume_sub_agent` | Mark agent available again; does not restart cancelled work. |
| `restart_agent_task` | Start a new task using explicit content or a saved retry payload. |
| `delete_sub_agent` | Remove child relationship/session if safe. |

### Compatibility Path

- Keep `stop_sub_agent` as a compatibility alias for one release cycle.
- Return warnings that specify what it actually did: `paused`, `cancelled_task`, or both.
- Add explicit tools/routes for cancellation vs pause if not already present.

### Acceptance Criteria

- Cancelling a background task cannot be confused with pausing an agent.
- Resuming a cancelled task does not falsely report that work restarted.
- `get_agent_status` distinguishes agent availability from background task state.

## Phase 3: Delegation Acknowledgement And Durable Message State

`MessageBus` is currently best-effort push routing. Good for UI events, weak for work assignment.

### Required Improvements

- `send_message` / `delegate` should return delivery metadata:
  - recipient exists
  - handler registered
  - message published to event bus
  - handler invoked
  - handler accepted/rejected
- Add a durable message/task record for delegated work or explicitly document that messages are ephemeral.
- Consider a small per-agent inbox for unhandled messages if durable delegation is desired.
- Include `message_id`, `session_id`, `parent_agent_id`, `child_agent_id`, and `channel` consistently.

### Acceptance Criteria

- Delegating to a missing child returns a clear error or `delivered=false`.
- Delegating to a child with no handler does not look like success.
- UI/web can show whether delegation is queued/running/completed/failed.

## Phase 4: Executor And Task Model Cleanup

`AgentExecutor` is useful but global and task-lite. Make it explicit.

### Improvements

- Separate `agent_id` from `task_id`; one agent should be able to run multiple historical tasks even if only one active task is allowed.
- Store task creation time, start time, end time, duration, parent, session, directory, prompt hash/title, and terminal state.
- Add cleanup policy for completed tasks.
- Add per-task cancellation.
- Make timeout behavior consistent between `wait_for_agents` and lower-level executor waits.

### Acceptance Criteria

- Status APIs can answer both “what agents exist?” and “what background tasks exist?”
- Completed task results remain inspectable until cleanup policy removes them.
- Duplicate background delegation to an already-running agent gives a deterministic error with task metadata.

## Phase 5: Context Sharing Hardening

Sub-agent value depends on predictable context boundaries.

### Improvements

- Add focused tests for:
  - shared session means same transcript object/session id
  - shared context window means same CWM object but independent session where applicable
  - isolated child receives only intended initial categories
  - `shared_context_window_max_tokens` clamps isolated child CWM
  - `sync_context` replace vs merge semantics
- Add diagnostics to `get_context_info`:
  - parent id
  - session id
  - context-window identity/sharing group
  - token budget/clamp
  - copied categories at spawn time

### Acceptance Criteria

- A user can tell from one status call whether an agent is isolated, session-shared, or CWM-shared.
- Context sharing tests prevent accidental cross-session bleed.

## Phase 6: API/TUI/CLI Product Surface

Once the contract is true, make it usable.

### Improvements

- CLI:
  - `penguin agent list`
  - `penguin agent tree`
  - `penguin agent tasks`
  - `penguin agent pause/resume/cancel/delete`
- Web/TUI:
  - show child-session task cards for isolated spawns
  - show background task status and terminal result
  - show delegation failures visibly
- Python API:
  - `spawn_sub_agent(...)`
  - `delegate(...)`
  - `wait_for_agent_task(...)`
  - `list_agent_tasks(...)`

### Acceptance Criteria

- Same lifecycle state is visible through tool calls, CLI, TUI, web API, and Python API.
- TUI does not render failed delegation as a successful helper task.

## Phase 7: Higher-Level Orchestration Later

Only after the lower layers stop lying.

### Candidates

- Planner / implementer / reviewer recipes.
- Map-reduce style exploration workflows.
- Parallel code review agents with final synthesis.
- Agent capability registry.
- Per-agent budget policies.
- Work-stealing or task queues.
- Agent memory summaries across sessions.

### Guardrail

Every higher-level workflow must compile down to the same explicit primitives:

```text
spawn/configure -> delegate/start task -> observe/wait -> collect evidence -> synthesize
```

If the primitive contract cannot explain the workflow, the workflow is too magical.

## Testing Plan

### Unit Tests

- Tool schema validation for `spawn_sub_agent` fields.
- `ConversationManager.create_sub_agent()` sharing modes.
- `AgentExecutor` state transitions and cancellation.
- `MessageBus` handler present/missing cases.
- `delegate` delivery metadata.

### Integration Tests

- Spawn isolated child with `initial_prompt`, verify child session and parent linkage.
- Spawn background child, wait for completion, inspect result.
- Delegate to existing child synchronously and verify delivery status.
- Delegate to missing child and verify non-success.
- Pause/resume/cancel behavior matrix.
- TUI/web session-created event for isolated child.

### Regression Scenarios

- Unsupported config cannot silently succeed.
- `resume_sub_agent` cannot restart a cancelled task by implication.
- `default_tools` cannot imply sandboxing unless enforcement exists.
- `delegate_explore_task` does not create fake persistent child-session expectations.

## Documentation Checklist

- `architecture.md`
- `README.md`
- `docs/docs/advanced/sub_agents.md`
- `penguin/prompt_actions.py`
- CLI command help
- Web/API route docs
- MCP tool descriptions if exposed

## Open Questions

1. Should per-agent model/tool config live in `AgentManager`, `EngineAgent`, or a new `AgentRuntimeConfig` object?
2. Should delegated messages become durable project tasks, lightweight inbox messages, or remain ephemeral with explicit delivery metadata?
3. Should `stop_sub_agent` be renamed now or kept indefinitely as compatibility sugar?
4. Should one agent be allowed multiple concurrent background tasks, or should active work remain one-task-per-agent?
5. What is the minimum tool-policy enforcement needed before `default_tools` can be called real?

## First PR Recommendation

Be boring and ruthless:

1. Update docs to remove stale `register_agent` examples.
2. Make unsupported `spawn_sub_agent` config fields fail loudly.
3. Add tests proving supported fields are actually applied.
4. Split cancellation language from pause/resume language in tool responses.
5. Add delivery metadata for missing/no-handler delegation.

That closes the credibility gap. Then build the shiny orchestration layer.
