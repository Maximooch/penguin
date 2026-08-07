# Resolve Multi-Agent Execution

## Status: Corrected implementation in progress

> **Do not implement the historical Option A below.** A 2026-07-31 log and
> runtime audit disproved this document's original central diagnosis. The
> observed foreground child did execute: it made 45 LLM requests and 168 tool
> calls. The apparent lock came from the native async runtime entering the
> synchronous ToolManager bridge and blocking the server loop on
> `thread.join()`. Background children were the tasks actually stranded when
> the bridge closed its temporary event loop.

### Implemented containment milestone

- Provider-native calls prefer `ToolManager.execute_tool_async()` and await
  coroutine-backed tools on the owning event loop.
- The temporary-loop/thread bridge is rejected from running event loops.
- Provider-native background executors are ToolManager/core scoped rather than
  shared through the process-global executor; ActionXML/HTTP unification is
  still pending.
- Shutdown cancels and awaits owned child tasks; wait timeouts no longer cancel
  the child implicitly.
- Foreground child failures return structured tool errors.
- Explicit `subagents_enabled: false` removes native schemas and denies native
  and ActionXML dispatch before mutation.
- Duplicate sub-agent relationships fail before shared-session metadata can be
  relabelled, and `parentID == session.id` is rejected/sanitized through
  persistence, API, and TUI boundaries.
- Request-preloaded conversation managers remain stable across repeated Engine
  component resolution; unknown TUI agent labels normalize to `default`.
- MessageBus sends now acknowledge actual delivery instead of unconditionally
  reporting success.

### 2026-08-07 model-selection audit

Per-child model selection is exposed publicly but is not wired through the
current creation boundary:

- **Native/ActionXML schema mismatch:** `spawn_sub_agent` accepts and forwards
  `persona`, `model_config_id`, `model_overrides`,
  `model_output_max_tokens`, and `default_tools`, but
  `core_runtime.agent_lifecycle.create_sub_agent()` does not accept those
  arguments. A model-selecting spawn can therefore fail with an unexpected
  keyword argument instead of creating a child with the requested model.
- **HTTP model selection is dropped:** `AgentSpawnRequest.model_config_id` is
  required by the HTTP request model, and `model_overrides` is accepted, but
  `/api/v1/agents` passes neither value to child creation. The endpoint can
  therefore require a selection that has no effect while the child inherits
  the existing/default runtime model.

This is not just an API-shape defect: a child needs its resolved model config,
child-specific `APIClient`, Engine registration, context-window limits, and
persisted model metadata installed as one operation. Unknown model/persona IDs
must fail before session or parent-child state is mutated. The fix belongs in
the transactional admission service below rather than as separate native and
HTTP patches.

### Remaining implementation order

1. Move request serialization to the core boundary and key it by the resolved
   conversation resource.
2. Replace native, ActionXML, and HTTP creation with one transactional admission
   service and rollback contract. It must normalize and validate `persona`,
   `model_config_id`, `model_overrides`, `model_output_max_tokens`, and tool
   defaults; resolve the effective child model before mutation; install the
   child-specific API client/Engine/context-window state; and persist the
   effective model metadata consistently across every entry point.
3. Add explicit child iteration/wall-clock budgets and complete pause/resume,
   cancellation, run-ID, and terminal-state semantics.
4. Add dry-run persisted-data repair for already-corrupted session indexes.
5. Implement session-qualified durable inbox delivery; do not restore the old
   process-global MessageBus handler design.

Model-selection acceptance evidence for item 2:

1. Spawn native foreground and background children whose model differs from
   the parent and confirm `engine.llm_attempt.start` records the requested child
   model.
2. Repeat through ActionXML and HTTP using the same model config and confirm all
   three paths persist identical effective-model metadata.
3. Verify both a configured OpenRouter model ID and an inline override work
   (for example `deepseek/deepseek-v4-flash` or `openai/gpt-5.6-luna`).
4. Verify an unknown model/persona or invalid override returns a structured
   error and leaves no child session, relationship, API client, or executor
   residue.
5. Verify omitting model selection deliberately inherits the parent/default
   model and records that effective choice explicitly rather than by accident.

The remainder of this file is retained as historical incident evidence. Claims
that conflict with this correction are not current runtime truth.

## Problem

Sub-agents spawned via `spawn_sub_agent` (synchronous, non-background) create a session but never execute an LLM call. The session is created, the tool returns success, but zero LLM attempts are made on the sub-agent session. The sub-agent is effectively dead on arrival.

## Symptoms

- `spawn_sub_agent` returns `{"status": "ok"}` with a valid session ID
- No `engine.llm_attempt.start` log for the sub-agent session
- `get_agent_status` returns `no_executor=True` (for background agents)
- TUI shows the sub-agent session but it contains no assistant response
- Web server logs show `subagent.status.summary status=completed no_executor=True elapsed_ms=0.1`

## Root Causes

### Bug 1: Tool Visibility (FIXED)

**File:** `penguin/tools/tool_manager.py:2742-2800`

`get_responses_tools()` uses a hardcoded `default_allowed` allowlist that never included multi-agent tools. The tools were registered in the ToolManager with schemas and execution handlers, but were invisible to the model — the model could never call them.

**Fix applied:** Added 15 tools to `default_allowed`:
- Multi-agent: `spawn_sub_agent`, `stop_sub_agent`, `resume_sub_agent`, `get_agent_status`, `wait_for_agents`, `get_context_info`, `sync_context`, `delegate`, `delegate_explore_task`, `send_message`
- Memory: `add_summary_note`, `add_declarative_note`, `memory_search`, `reindex_workspace`
- Research: `perplexity_search`

Allowlist went from 35 → 50 tools. Verified working: logs confirm `schemas=50` sent to model.

**Note:** `todowrite`, `todoread`, and `question` are NOT registered as tool schemas in ToolManager. They use a separate ActionXML/action-mapping path in `core.py:5550-5586`. Adding them to the allowlist would be a no-op. Separate fix needed if native tool exposure is desired.

### Bug 2: Synchronous Sub-Agent Execution (NOT FIXED)

**File:** `penguin/tools/tool_manager.py:4107` (`_execute_async_tool`)

The `spawn_sub_agent` execution handler is wrapped in `_execute_async_tool()`, which runs the coroutine in a **new thread with a new event loop**. This breaks the sub-agent's LLM execution because:

1. **ContextVar not propagated:** The Engine uses `_CURRENT_ENGINE_RUN_STATE` (a ContextVar) to track the current agent, API client, and model config. ContextVars are thread-local — the new thread starts with an empty run state.

2. **Event loop isolation:** `run_agent_prompt_in_session()` → `process()` → `engine.run_response()` depend on the main event loop's async infrastructure (API client connection pools, streaming callbacks). Running on a new event loop means these connections are unavailable.

3. **Engine instance state clobbering:** Even if the thread issue were fixed, `engine.run_response()` uses instance variables (`self.current_iteration`, `self.start_time`) that would be clobbered by re-entrant use from within the parent's tool execution.

4. **Silent failure:** The exception from the failed LLM call is caught and logged as a warning (`tool_manager.py:6497`), making this hard to diagnose.

### Bug 3: MessageBus Handler Missing (Legacy, partially masked)

**File:** `penguin/engine.py:952-990` (`setup_message_bus`)

The Engine only registers a MessageBus handler for `"human"` recipients. No handler is registered for sub-agent IDs. The original synchronous path (before `run_agent_prompt_in_session` was added) used `send_to_agent()` → `route_message()` → `MessageBus.send()`, but messages to sub-agents were silently dropped — no handler existed to receive them.

This was partially addressed by commit `2e960c7b0` (Mar 21 2026) which added `run_agent_prompt_in_session()` as the preferred path, but that introduced Bug 2.

## Git History

| Date | Commit | Change |
|------|--------|--------|
| Nov 2, 2025 | `ee274986a` | `default_allowed` allowlist created without multi-agent tools. Tools registered but never exposed to model. |
| Mar 9, 2026 | `7c1ddb9f0` | Synchronous sub-agents used `send_to_agent()` → MessageBus. No handler registered for sub-agents — messages silently dropped. |
| Mar 21, 2026 | `2e960c7b0` | Added `run_agent_prompt_in_session()` as preferred synchronous path. Introduced thread/event-loop isolation bug via `_execute_async_tool`. |

## Proposed Fix Options

### Option A: Use Background Executor with Synchronous Wait (Recommended)

The background path (`AgentExecutor.spawn_agent()`) already works correctly — it was designed for isolated agent execution. Make the synchronous path use it and block:

```python
# In _execute_spawn_sub_agent, synchronous branch:
# Instead of run_agent_prompt_in_session, use executor + wait
executor = get_executor() or AgentExecutor(self._core)
set_executor(executor)
await executor.spawn_agent(agent_id, initial_prompt, metadata={...})
# Block until the background agent completes
result = await executor.wait_for_agent(agent_id, timeout=...)
```

**Pros:** Reuses tested code path, proper isolation, no thread/event-loop issues.
**Cons:** Requires `AgentExecutor` to support synchronous waiting (may need `wait_for_agents` integration).

### Option B: Run on Same Event Loop

Modify `_execute_async_tool` to detect when it's already in an async context and run the coroutine directly via `asyncio.ensure_future()` or similar, rather than spawning a new thread.

**Pros:** Minimal change, preserves existing architecture.
**Cons:** Risk of re-entrant Engine state clobbering. Engine is not designed for concurrent use.

### Option C: Subprocess/Multiprocessing Model

Spawn each sub-agent as a separate process with its own Engine instance.

**Pros:** Full isolation, no shared state issues.
**Cons:** Heavyweight, complex IPC, significant refactoring. Overkill for most use cases.

## Verification

After fixing Bug 2, verify:
1. Spawn a synchronous sub-agent with an `initial_prompt`
2. Check logs for `engine.llm_attempt.start` on the sub-agent session
3. Confirm the sub-agent session has an assistant response
4. Confirm the parent receives the sub-agent's response in the tool result

## Related Files

- `penguin/tools/tool_manager.py:2742` — `get_responses_tools()` allowlist (Bug 1, fixed)
- `penguin/tools/tool_manager.py:4107` — `_execute_async_tool()` (Bug 2, not fixed)
- `penguin/tools/tool_manager.py:6274` — `_execute_spawn_sub_agent()` (entry point)
- `penguin/tools/tool_manager.py:6485` — synchronous execution branch (Bug 2)
- `penguin/core.py:1503` — `run_agent_prompt_in_session()` (called but fails in thread)
- `penguin/core.py:2895` — `process()` (called by run_agent_prompt_in_session)
- `penguin/engine.py:2012` — `run_response()` (LLM loop, needs main event loop)
- `penguin/engine.py:952` — `setup_message_bus()` (Bug 3, only registers human handler)
- `penguin/multi/executor.py` — `AgentExecutor` (background path, works correctly)
