# Penguin Responses Streaming TODO

Date: 2025-10-30

Purpose: Track the plan and progress for migrating Penguin streaming to pause/resume around tool usage using OpenRouter Responses API, including a bridge from Penguin XML action tags to Responses tool_choice. This is the single canonical markdown for this effort.

## Goals
- Pause streaming when an action/tool is needed, execute via ToolManager, and resume with full context.
- Prefer OpenRouter Responses API tool calling; bridge Penguin XML action tags → tool_choice.
- Keep incremental execution: one action per iteration for predictable UX.
- Use Responses web-search; keep Penguin-specific tools for file/code/command.
- Add timeouts/circuit breakers, telemetry, and robust error handling.

## Scope
- Primary: `openrouter_gateway.py`, `engine.py`, `model_config.py`, `api_client.py`, `tool_manager.py`, `parser.py`, `core.py`.
- Out of scope (initial): browser automation and process management tools as Responses tools.

## Decisions (confirmed)
- Tool surface: include only file/code/command edits/executions (exclude browser/process mgmt by default).
- tool_choice: default to auto; allow force-per-call override for the tag→tool bridge.
- Web search: prefer Responses API web-search.
- Output bounding: future consideration; for now summarize large outputs when feasible.
- Timeouts/circuit breakers: add and return structured error summaries; continue loop.
- Telemetry: log SSE interrupts (reason, streamed-bytes), tool latencies, resumes; expose counters.
- Reasoning streaming: keep separate from content; finalize before inserting tool results.
- Fallbacks: retain Penguin XML tags and legacy chat.completions where needed.

## Task List
- [x] Draft this plan file
- [x] Add ModelConfig flags: `use_responses_api`, `interrupt_on_action`, `interrupt_on_tool_call`
- [x] Gateway: detect complete Penguin action tags during SSE; abort stream; return partial; telemetry
- [x] Bridge: map Penguin XML tags → Responses `tool_choice`; re-issue request (forced tool when applicable)
- [x] Engine: enforce one action per iteration; finalize streaming message between iterations
- [x] Map curated `ToolManager` tool schemas to Responses tools (file/code/command only)
- [x] Responses web-search wiring; prefer over custom
- [x] Timeouts/circuit breakers for tool execution; structured error return
- [x] Telemetry counters and logging surfaces (interrupts, streamed-bytes, tool latency, resumes)
- [x] Tests: streaming interrupt (unit-level detection), tag→tool bridge (unit coverage), web-search presence, timeout/error path
- [x] Update references (no new summary markdowns beyond this file)

## Implementation Notes (by file)

### `penguin/llm/model_config.py`
- Add flags: `use_responses_api: bool = False`, `interrupt_on_action: bool = True`, `interrupt_on_tool_call: bool = False`.
- Parse env overrides; expose via `get_config()` for diagnostics.

### `penguin/llm/openrouter_gateway.py`
- In `_handle_streaming_response`: accumulate `full_content`; detect complete Penguin XML action tags; if found and `interrupt_on_action=True`, abort SSE and return `full_content` (UI already streams chunks).
- Telemetry: count streamed bytes, mark interrupt reason (“penguin_action_tag”), record timing.
- Phase 2: handle Responses tool_call SSE items similarly when `interrupt_on_tool_call=True`.

### `penguin/engine.py`
- In `_llm_step`: execute only the first parsed action per iteration (incremental). Persist action result via `cm.add_action_result(...)` and emit UI event.
- Ensure `finalize_streaming_message()` is called between iterations to keep UI blocks separated.

### `penguin/llm/api_client.py`
- Plumb `ModelConfig` flags to gateway calls as needed (no behavior change required initially).

### `penguin/tools/tool_manager.py`
- Build curated Responses-tool registry from existing schemas for file/code/command tools only.
- Add per-tool timeouts and circuit breakers; on failure, return structured error `{ error, tool, duration_ms }`.

### `penguin/utils/parser.py`
- Keep strict, complete-tag parsing. No change needed; used for tag detection and engine execution.

### `penguin/core.py`
- No functional change; ensure streaming finalization + message persistence is invoked by Engine.

## Telemetry & Observability
- Counters: `responses_interrupts_total`, `streamed_bytes_total`, `tool_latency_ms`, `resume_requests_total`.
- Structured logs on interrupt (reason, bytes, elapsed_ms).

## Testing
- Unit: tag detection (partial vs complete), single-action enforcement, timeout path returns structured errors.
- Integration: SSE interrupt mid-stream → tool exec → resume; Responses web-search path.
- Regression: large outputs summarized (future) and UI separation of reasoning/content/tool blocks.

## Milestones
- Phase 1 (Incremental): Tag-based interrupt + one-action-per-iteration + telemetry + tests.
- Phase 2 (Responses tools): Map curated tools, bridge tag→tool_choice, handle tool_call SSE, tests.
- Phase 3 (Refine): Output bounding, richer policies, metrics surfacing.

## Progress Log
- 2025-10-30: Created plan file and aligned decisions with product direction.
- 2025-10-30: Added ModelConfig flags (use_responses_api, interrupt_on_action, interrupt_on_tool_call).
- 2025-10-30: Implemented streaming interrupt on Penguin action tags (SDK + Direct API paths).
- 2025-10-30: Enforced one action per iteration in Engine.
- 2025-10-30: Wired curated Responses tools and enabled built-in web_search; tool_choice bridge added.
- 2025-10-30: Added timeouts/circuit breakers for execute_command, code_execution, diff/apply/edit/analyze tools with structured errors.
- 2025-10-30: Added basic interrupt on tool_call SSE (SDK + Direct API) as groundwork for phase 2.
- 2025-10-31: Implemented phase 2 tool_call execution/resume via gateway → engine bridge.
- 2025-11-01: Fixed critical indentation error in openrouter_gateway.py:456 preventing module loading.
- 2025-11-01: Fixed Claude 4 reasoning detection pattern in model_config.py (changed "4." to "claude-4").
- 2025-11-01: Added comprehensive test coverage - 13 tests total in test_parser_and_tools.py covering streaming interrupts, telemetry, timeouts, tool calls, action tag consistency, and reasoning config.
- 2025-11-01: Fixed conversation flow issue - increased default max_iterations from 5 to 15 in web/api routes.
- 2025-11-01: Implemented final summary generation in engine.py to handle max_iterations edge case while executing tools.
- 2025-11-01: **Implementation complete** - All tasks checked off, all tests passing, streaming interrupt flow working end-to-end with proper resume/continue logic.


