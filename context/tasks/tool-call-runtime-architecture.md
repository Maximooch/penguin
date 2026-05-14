# Tool Call Runtime Architecture

## Purpose

This document plans a long-term refactor of Penguin's model/tool control flow.

The current loop is built around assistant text containing custom ActionXML or
JSON-ish action blocks. That works, but it couples model prompting, parsing,
tool routing, result persistence, UI events, and loop control too tightly.

The target architecture is a provider-neutral tool-call runtime that can handle:

- Penguin's existing ActionXML/CodeAct format
- native OpenAI Responses tool calls
- future MCP/app/deferred tools
- one or more tool calls per model turn
- conservative serial execution first
- safe parallel execution later

This is not only for Codex parity. It should make Penguin's own tool loop more
reliable and easier to evolve.

## Current State

Penguin currently has two overlapping tool-call paths.

### ActionXML / CodeAct Path

The main loop asks the model for assistant text, then parses action tags out of
that text:

```text
assistant text
  -> parse_action()
  -> CodeActAction
  -> ActionExecutor.execute_action()
  -> ToolManager method
  -> action result persisted to conversation
  -> next model iteration
```

Important current behavior:

- `penguin/utils/parser.py` owns the `ActionType` enum and action parser.
- `ActionExecutor.execute_action()` owns a large action-to-handler map.
- `penguin/engine.py` intentionally executes only the first parsed action per
  iteration.
- action results are persisted as conversation action-result records.

### Responses Tool-Call Path

The newer Responses path captures a provider tool call and executes it after
the model step:

```text
Responses API tool call captured by provider adapter
  -> execute_pending_tool_call()
  -> ToolManager.execute_tool()
  -> action result persisted to conversation
```

This path is useful, but it is still shaped like a single pending tool call
side channel rather than a unified runtime.

## Upstream Codex Comparison

Codex treats tool calls as first-class response items from the model stream.

Conceptually:

```text
model stream
  -> ResponseItem::FunctionCall / CustomToolCall / LocalShellCall / MCP
  -> ToolCall { call_id, tool_name, payload }
  -> ToolRouter
  -> ToolInvocation { session, turn, cancellation, tracker, call_id, payload }
  -> tool result ResponseInputItem
  -> record result and continue
```

Key ideas worth borrowing:

- tool calls have stable call ids
- provider-native tool calls are not embedded in assistant prose
- each tool receives a turn/runtime context
- cancellation is part of the tool invocation
- read-only or explicitly safe tools can run in parallel
- mutating/unsafe tools are serialized
- model-visible tool specs are built from registry metadata
- result items are recorded with enough identity to reconstruct the turn

Penguin does not need to clone Codex internals, but it should adopt the same
separation of concerns.

## Reference Harness Takeaways

Local references reviewed:

- `reference/codex`
- `reference/opencode`

Useful design lessons for Penguin:

- Tool calls should be durable runtime objects, not assistant text conventions.
  Codex carries `call_id`, tool name, payload, session, turn context,
  cancellation token, and diff/output tracking through dispatch and persistence.
- Tool output truncation should be universal, explicit, and artifact-backed.
  OpenCode wraps tools with a default truncation layer, preserves the full
  output locally, and returns model-visible hints for reading/searching the
  saved output.
- Parallelism needs scheduler-owned metadata. Codex only runs calls in parallel
  when the configured tool explicitly supports it; other calls take an
  exclusive gate. Penguin should keep serial execution as the default until
  read-only, mutating, approval, streaming, and retry metadata are reliable.
- Permission checks belong in the runtime path. Codex and OpenCode both attach
  approval prompts, cached approvals, and permission context to tool execution
  rather than relying only on prompt instructions.
- Shell/process tools are a runtime family, not a generic function call. They
  need cwd/env tracking, timeout/cancellation, stdout streaming, sandbox and
  network approval, exit-code metadata, and persistent process state.
- Tool history replay must be provider-safe. Dangling or interrupted tool calls
  should replay as explicit error/cancelled tool results so providers with
  strict adjacency rules never receive unresolved tool-use blocks.
- Tool calls should be recorded before execution starts. Codex persists model
  output items before dispatching tools, which keeps recovery coherent if the
  process is cancelled, interrupted, or disconnected between call capture and
  result persistence.
- Provider quirks should stay at the adapter edge. Higher layers should see
  canonical tool calls/results/events, while adapters handle provider-specific
  tool-call IDs, message ordering, schemas, and finish reasons.
- File mutation tools should have a small, provable surface. Codex's
  `apply_patch` uses explicit old/context/new hunks instead of raw line
  coordinates, and OpenCode's `edit` tool requires exact old-string matches
  that fail when missing or ambiguous. Penguin should converge on those two
  shapes rather than preserving many overlapping edit primitives.

## Target Architecture

Introduce a provider-neutral intermediate representation:

```python
ToolCall(
    id: str,
    name: str,
    arguments: dict[str, Any] | str,
    source: Literal["action_xml", "responses", "mcp", "internal"],
    raw: Any,
    mutates_state: bool,
    parallel_safe: bool,
    requires_approval: bool,
)
```

`mutates_state`, `parallel_safe`, and `requires_approval` need explicit
ownership before the scheduler consumes them. Until registry metadata exists,
adapters should use conservative defaults: assume calls mutate state, are not
parallel safe, and require approval when the current tool path would require
approval. A registry-backed classifier should replace those defaults before any
parallel scheduling policy is enabled.

And a corresponding result:

```python
ToolResult(
    call_id: str,
    name: str,
    status: Literal["completed", "error", "cancelled", "requires_approval"],
    output: str,
    structured_output: dict[str, Any] | None,
    started_at: float,
    ended_at: float,
    output_hash: str,
    output_path: str | None,
    truncated: bool,
)
```

The loop should become:

```text
provider output
  -> provider/action adapter extracts ToolCall[]
  -> scheduler chooses serial or parallel execution
  -> registry dispatches ToolCall to handler
  -> ToolResult[] persisted with call ids and arguments
  -> next model input is built from ToolResult[]
```

ActionXML should become one adapter into this runtime, not the runtime itself.

## Proposed Components

### 1. ToolCall Adapter Layer

Responsibilities:

- convert ActionXML/CodeAct tags into `ToolCall` objects
- convert Responses API tool calls into `ToolCall` objects
- preserve raw provider/tool metadata for debugging
- report malformed tool syntax without executing anything

Initial adapters:

- `ActionXmlToolCallAdapter`
- `ResponsesToolCallAdapter`

### 2. Tool Registry

Responsibilities:

- own tool names, schemas, handlers, metadata, and aliases
- replace the large `ActionExecutor` action map over time
- expose model-visible schemas where supported
- expose runtime metadata:
  - read-only vs mutating
  - parallel-safe
  - requires approval
  - long-running
  - streams output

This can wrap the current `ToolManager` initially. It does not need to replace
every tool implementation in the first phase.

### 3. Tool Scheduler

Responsibilities:

- accept a list of `ToolCall` objects from one model turn
- execute serially by default
- optionally execute safe read-only calls concurrently
- serialize mutating calls
- preserve deterministic result ordering
- support cancellation and timeouts
- enforce per-tool and aggregate output limits before model replay
- emit start/end UI events consistently

The first scheduler should be deliberately conservative:

- run all calls serially
- accept multiple calls per model turn
- persist all results with call ids

Parallel execution can be added once the metadata and persistence are reliable.

### 4. Tool Result Store / Conversation Integration

Responsibilities:

- persist tool call id, name, arguments, status, output, and output hash
- persist the call record before tool execution so cancellation/interruption can
  replay the call as a cancelled or failed result instead of losing it
- persist truncation metadata and a full-output artifact/reference when output
  is too large for model-visible replay
- distinguish assistant text from tool calls and tool results
- make repeated-loop detection use tool identity and arguments
- support reconstruction/debugging of a model turn
- replay interrupted, cancelled, or failed tool calls as explicit tool results
  rather than leaving provider-native tool calls dangling

This should avoid relying on the first 200 characters of output as the primary
identity for progress detection.

### 5. Loop Controller

Responsibilities:

- coordinate model step, tool extraction, scheduling, persistence, and follow-up
- decide whether a response is complete
- decide whether another model turn is needed
- handle malformed tool syntax repair
- handle empty tool-only loops based on `ToolCall`/`ToolResult` identity
- retry empty non-tool continuations after tool-heavy turns with bounded tool
  output before surfacing a terminal diagnostic

The loop controller should not know individual tool semantics. It should reason
about call/result metadata.

## Migration Plan

### Current Position

Penguin is implemented through the Phase 7 metadata foundation for the
first-class provider/tool runtime path:

- ActionXML and native provider tool calls both normalize into
  `ToolCall`/`ToolResult` before legacy action-result compatibility views are
  persisted.
- The current loop guard uses IR-aware identity rather than text previews.
- OpenAI/Codex, OpenRouter/OpenAI-compatible, and Anthropic native tool paths
  have provider-aware preparation, capture, and replay repair coverage.
- Phase 5.5 prompt guidance already prefers native provider tool calls when
  schemas are available, keeps ActionXML documented as fallback, and removes
  native `finish_response` exposure so normal turns end by returning text with
  no further tool calls.
- Phase 6.5 now persists lightweight first-class tool call/result session
  records for all tool paths, preserves those records through CWM trimming, and
  applies a shared artifact-backed per-tool model-output cap in the serial
  scheduler.
- Phase 7 now has a minimum model-visible schema contract and conservative
  runtime metadata extraction. The scheduler can consume that metadata later,
  but no parallel execution is enabled yet.
- A file-edit reliability rewrite is now the next highest-priority tool
  runtime slice. The existing line-coordinate edit surface is too easy for
  models to misuse after repeated reads/edits, and `.bak` files have proven
  more harmful than useful inside user repositories.

Phase 6 parallel tool execution remains blocked until the safe-tool audit,
approval semantics, cancellation behavior, and registry metadata are complete.
The remaining practical order is:

1. Rewrite the model-visible file edit surface around exact replacements and a
   Codex-style patch tool; retire unsafe line-coordinate edit paths.
2. Audit concrete first-pass tools for read-only and parallel-safe behavior.
3. Expand registry metadata coverage for approval, long-running/streaming
   process behavior, retry safety, provider support, and UI presentation.
4. Add runtime permission/approval outcomes as structured `ToolResult` statuses.
5. Defer aggregate per-turn model-visible tool-output caps until after the
   record/replay boundary remains stable under real workloads.
6. Enable Phase 6 parallel execution only for explicitly audited safe subsets.

### Phase 0: Document and Test Current Behavior

Goals:

- preserve current behavior while creating room to refactor
- add tests around current one-action-per-iteration behavior
- add tests for multiple ActionXML tags in one assistant response
- add tests for Responses tool-call execution
- add tests for repeated empty tool-only loop detection

Acceptance criteria:

- current behavior is explicitly covered by tests
- regressions during migration are visible

Phase 0 coverage added:

- `tests/test_tool_call_runtime_phase0.py` locks multiple ActionXML parsing,
  current one-action-per-iteration execution, Responses tool-call identity
  preservation, and empty tool-only loop detection/reset behavior.
- Existing Responses-path tests in `tests/test_engine_responses_tool_calls.py`
  and `tests/test_engine_responses_tool_action_results.py` continue to cover
  engine integration and persistence ordering.

### Phase 1: Introduce ToolCall / ToolResult IR

Goals:

- add internal dataclasses for `ToolCall` and `ToolResult`
- map ActionXML actions into `ToolCall`
- map provider-captured Responses calls into `ToolCall`
- map existing action results into `ToolResult`

Acceptance criteria:

- no user-visible behavior change required
- all current tool paths can produce normalized call/result records
- existing action result persistence still works

Phase 1 implementation note:

- `penguin.tools.runtime` defines additive `ToolCall` and `ToolResult`
  dataclasses plus compatibility helpers for current legacy action-result dicts.
- ActionXML and provider-captured Responses metadata now normalize through this
  IR internally before converting back to the existing persisted result shape.
- The initial metadata policy is conservative: calls default to mutating, not
  parallel safe, and approval-required until later registry metadata can refine
  those flags.

### Phase 1.5: Harden Current Loop Guard

Goals:

- improve the existing repeated-empty-tool guard before the full runtime
  migration
- include current action metadata such as tool name, arguments, file paths,
  ranges, limits, status, and output hashes in the guard signature
- keep the guard compatible with today's one-tool-at-a-time loop

Acceptance criteria:

- repeated reads of the same file with different ranges do not falsely trigger
  stale-loop detection
- truly identical empty tool-only loops still stop safely
- guard messages explain what happened and how to continue

Phase 1.5 implementation note:

- The current empty tool-only guard now hashes a deterministic signature built
  from tool name, normalized arguments, common file/range/limit fields, status,
  and full output hash.
- ActionXML and Responses execution paths attach runtime-only `tool_arguments`,
  `tool_call_id`, and `output_hash` metadata to action results so the existing
  loop can distinguish real progress without waiting for the scheduler refactor.
- Identical empty tool-only loops still stop after the current repeat threshold,
  while repeated reads/searches with different arguments are treated as progress.

### Phase 2: Add Serial Tool Scheduler

Goals:

- move execution orchestration into a scheduler
- execute one or more `ToolCall` objects serially
- keep the default behavior conservative
- preserve UI events and conversation persistence

Acceptance criteria:

- ActionXML responses with multiple actions can be represented
- runtime can choose to execute only one or all calls by policy
- all executed calls get stable ids and persisted results

Phase 2 implementation note:

- `execute_tool_calls_serially()` and `ToolExecutionPolicy` provide the first
  conservative scheduler layer for normalized `ToolCall` objects.
- The scheduler can execute every call in order or cap execution with
  `max_calls`; Penguin's ActionXML path currently uses `max_calls=1` to
  preserve existing one-action-per-iteration behavior.
- Responses tool-call execution also goes through the scheduler with a single
  call, keeping provider call ids and current persistence/UI behavior intact.

### Phase 3: Replace ActionExecutor Routing With Registry Routing

Goals:

- move the action-to-handler map into a registry
- keep legacy action aliases
- allow model-visible schemas to come from one source
- reduce coupling between parser, executor, and ToolManager

Acceptance criteria:

- adding a tool requires one registry entry, not parser/executor/UI edits in
  several places
- `ActionExecutor` becomes a compatibility wrapper or is removed
- `ToolManager` becomes an implementation backend, not the public routing API

Phase 3 implementation note:

- `penguin.tools.action_registry` introduces `ActionToolRegistry` and
  `ActionToolRoute` for ActionXML routes that can already be expressed as
  ToolManager calls.
- `ActionExecutor` now lets the registry override canonical ToolManager-backed
  actions such as command execution, search, read/write, and patch operations;
  the legacy handler map remains as fallback for UI-heavy and manager-specific
  actions.
- Legacy edit aliases remain registered with canonical action metadata, keeping
  old tags compatible while moving routing ownership out of the parser module.

### Phase 4: Replace Loop Guards With IR-Aware Control

Goals:

- make loop guards inspect `ToolCall` and `ToolResult` identity
- account for tool args, file paths, ranges, limits, output hashes, and status
- distinguish legitimate exploration from stale repeated output
- add user-visible continuation behavior when a guard stops a run

Acceptance criteria:

- repeated reads of the same file with different ranges do not falsely trigger
  stale-loop detection
- truly identical empty tool-only loops still stop safely
- guard messages explain what happened and how to continue

Phase 4 implementation note:

- `ToolLoopIdentity` now captures a stable fingerprint, per-tool identity
  entries, and a compact summary for each empty tool-only iteration.
- Loop fingerprints include tool name, status, normalized arguments, file/range
  fields, and output hashes while ignoring volatile provider call ids, so
  repeated native calls can still be detected as stale.
- `LoopState` tracks the last repeated tool identity summary, and the terminal
  stall note now names the repeated tool result and tells the user to continue
  with a new file, range, query, or command.

### Phase 5: Native Tool-Call First Providers

Goals:

- treat OpenAI Responses/Codex function calls as first-class tool calls
- avoid converting native provider tool calls into ActionXML concepts
- support multiple provider tool calls from a single response
- preserve provider call ids in persisted records

Acceptance criteria:

- Codex/OpenAI native tool calls and ActionXML calls use the same scheduler
- provider-specific parsing is isolated in adapters
- the loop controller is provider-neutral

Phase 5 implementation note:

- OpenAI/Codex Responses function calls are now captured as a pending list in
  the adapter, preserving each provider `call_id`/item id instead of reducing
  the turn to a single last call.
- `execute_pending_tool_calls()` drains those native calls into `ToolCall`
  records and executes them through the serial scheduler, keeping execution
  order deterministic while Phase 6 parallel policy remains disabled.
- Engine tool handling is plural internally, while the old singular helper
  remains as a compatibility shim for existing callers and tests.
- This matches the OpenAI Responses function-calling contract: provider
  function calls are app-executed and returned as tool outputs by call id,
  without translating native calls through ActionXML.

### Phase 5.5: Update Model-Facing Tool Instructions

Goals:

- make prompts describe the native tool-call path clearly
- keep ActionXML documented as the compatibility/fallback protocol
- avoid telling native-tool providers to print XML tags when schemas are
  available
- keep completion guidance correct for both native tools and ActionXML

Acceptance criteria:

- system/tool prompts say to use the provider tool channel when tools are
  exposed natively
- ActionXML remains documented for providers or modes without native tool
  support
- normal conversation turns complete by returning assistant text with no tool
  calls, while formal task runs still use `finish_task`
- native provider schemas do not expose `finish_response` as a model-callable
  stop tool

Phase 5.5 implementation note:

- `penguin.prompt_actions` now presents native provider tools as the preferred
  path when schemas are available and labels ActionXML as the compatibility
  fallback path.
- Native provider schemas now omit `finish_response`; this matches Codex,
  OpenCode, and Hermes-style loops where "no tool calls" is the normal
  conversation-turn completion signal. `finish_response` remains available as a
  legacy ActionXML compatibility signal.
- Completion guidance now reserves native `finish_task` for formal task work
  and avoids telling normal conversation turns to call a stop tool.
- `tests/test_prompt_actions.py` covers native-tool preference, fallback
  wording, alias rendering, and completion-tool guidance.
- `tests/test_engine_responses_tool_calls.py` covers provider schema filtering
  so OpenAI/Codex, OpenRouter, and Anthropic native schemas do not advertise
  `finish_response`.

### Phase 5.6: Extend Native Tool Support Across Providers

Goals:

- inventory `penguin/llm` provider runtimes for native tool-call capability
- add provider-specific extraction/adaptation for OpenRouter and other
  OpenAI-compatible tool-call responses
- normalize non-OpenAI provider tool metadata into `ToolCall` records
- keep unsupported providers on the ActionXML fallback path

Acceptance criteria:

- OpenRouter/OpenAI-compatible tool-call responses can flow through the same
  plural pending-call runtime when the upstream model supports tools
- provider capability checks prevent sending native tool payloads to models or
  endpoints that do not support them
- provider contract tests cover text, reasoning, streaming, and tool-call
  behavior without relying on live provider responses

Phase 5.6 implementation note:

- Native tool preparation is now provider-aware in `penguin/llm/runtime.py`.
  OpenAI/Codex keeps the Responses tool schema, OpenRouter receives regular
  Chat Completions `tools`/`tool_choice`, and Anthropic receives Messages API
  client-tool schemas with `input_schema`.
- OpenRouter remains on the regular Chat Completions tool contract for now,
  even though OpenRouter also exposes a Responses API beta. This keeps the
  implementation aligned with Penguin's existing OpenRouter gateway and avoids
  mixing two OpenRouter transport contracts in one phase.
- OpenRouter tool-call capture is plural and preserves multiple pending
  `tool_calls`, while retaining the singular getter as a compatibility shim.
- Anthropic maps Penguin assistant `tool_calls` metadata into `tool_use`
  content blocks and maps Penguin `role: tool` messages into user
  `tool_result` blocks. Consecutive tool results are grouped into one user
  message so Anthropic's immediate tool-result ordering rule is preserved.
- Follow-up: provider-native tool support is separate from provider
  reasoning-control support. OpenRouter logs can show `reasoning payload`
  disabled because Penguin did not send an explicit reasoning config, while
  the provider/model may still report reasoning-token usage. Audit provider and
  model capability metadata later so controllable reasoning config is applied
  only where the selected provider contract supports it.
- Provider capability metadata now exists in `LLMProviderCapabilities` and is
  attached to prepared provider requests. The remaining audit is model-level:
  verify which specific endpoints/models should set native-tool, reasoning,
  vision, resumable, and background flags.
- LiteLLM, Gemini, Ollama, and other providers intentionally remain on the
  ActionXML fallback path until their native tool contracts are audited and
  tested.

### Phase 6: Safe Parallel Tool Calls

Status:

- Deferred until Phase 7 metadata exists.
- Do not send provider `parallel_tool_calls` just because a model supports it.
  Penguin must first know which tools are safe to run concurrently and how to
  order, cancel, persist, and replay each result.

Goals:

- add parallel execution only for tools marked safe
- keep mutating tools serialized
- support per-tool and per-provider parallel settings
- send `parallel_tool_calls` only when Penguin can honor it

Acceptance criteria:

- read-only tools can run concurrently without corrupting state
- mutating tools never run concurrently unless explicitly safe
- result ordering is deterministic
- cancellation and errors are handled per call

Related future work:

- Broader tool-system improvements that are adjacent to this runtime refactor
  are tracked in `context/tasks/tool-system-future-improvements.md`, including
  terminal/session handling, debugger tools, dev-server process tools, result
  paging, richer metadata, and test/code-navigation suites.

### Phase 6.5: Universal Tool Output Truncation And Replay Safety

Goals:

- persist native/provider tool-call records before dispatching tools
- persist lightweight first-class tool call/result session records for all
  tools, not only native provider tools
- apply a single truncation policy to all model-visible tool outputs
- preserve full raw output in a local artifact/result store when truncated
- include line count, byte count, truncation direction, output hash, and output
  artifact path/reference in `ToolResult`
- leave room for an aggregate per-turn model-visible tool-output cap, but defer
  enforcement until durable records and replay are stable
- make provider replay reconstruct native tool-call and tool-result adjacency
  from persisted `ToolCall` / `ToolResult` records
- convert interrupted, pending, or cancelled historical tool calls into
  explicit error/cancelled tool results during replay

Acceptance criteria:

- every tool execution has a stable call/result record with id, tool name,
  normalized argument hash, status, timing, output hash, truncation metadata,
  and optional artifact reference
- legacy action-result messages remain as compatibility views until UI, TUI,
  and replay consumers move to first-class records
- if Penguin stops between tool-call capture and tool completion, replay can
  reconstruct the pending call and emit an explicit cancelled/failed result
- large command/read/search outputs do not get injected wholesale into the next
  model turn
- the model receives a concise truncation notice plus a safe way to inspect the
  full output by result id or artifact path
- empty-response recovery after tool-heavy turns retries once with bounded
  recent tool output before returning a structured diagnostic
- OpenAI/Codex, OpenRouter/OpenAI-compatible, and Anthropic replay tests cover
  completed, failed, cancelled, and interrupted tool calls
- repeated-loop detection uses normalized arguments and output hashes from
  `ToolResult`, not text previews

Provider replay progress note:

- `ToolResult` now carries byte count, line count, truncation direction,
  output hash, and optional artifact path metadata, and
  `prepare_model_visible_tool_output` provides a deterministic per-tool preview
  plus full-output artifact write path.
- `ToolCallRecord` and `ToolResultRecord` are lightweight first-class session
  records. They store call id, name, source, normalized arguments/hash, status,
  timing, output hash, byte/line counts, truncation metadata, bounded previews,
  and optional artifact references without making full output a required
  conversation payload.
- ActionXML and native provider tool paths persist the call record before
  dispatch and the result record after scheduler completion. Legacy
  `role=tool` action-result messages are still written as the compatibility
  view for existing UI, TUI, adapter, and history consumers.
- `ConversationSystem.get_formatted_messages()` can repair provider-native
  replay metadata for tool result messages from first-class records when an
  assistant tool-call message was trimmed or historical metadata is incomplete.
- The serial scheduler can apply a shared per-tool model-visible output policy.
  Penguin defaults to a generous 24k-character per-tool cap, can disable it
  with `PENGUIN_TOOL_OUTPUT_MAX_CHARS=0`, and writes full truncated outputs to
  workspace-local `conversations/tool-results/<session-id>/` artifacts when a
  conversation manager has a workspace path.
- Context-window trimming preserves provider lifecycle records and first-class
  tool call/result records even when lower-priority messages are dropped.
- Tool-output truncation has unit/property coverage for deterministic caps,
  artifact writes, metadata preservation, and artifact-safe IDs.
- Anthropic now marks `error`, `failed`, `cancelled`, and `interrupted`
  historical tool results as provider-native `is_error` tool results.
- OpenRouter/OpenAI-compatible chat replay now repairs CWM-truncated native
  tool history at the adapter edge: complete assistant-tool/tool-result pairs
  are preserved, orphaned assistant tool calls are flattened, and
  metadata-rich tool-result-only records synthesize a valid assistant tool call
  before replaying the tool result.

Reference points:

- OpenCode's tool wrapper truncates all tool outputs and stores full output
  under a local tool-output directory.
- Codex's `ToolOutput` boundary owns conversion to provider response items and
  truncates function output before model replay.

### Phase 7: Runtime Permissions And Tool Metadata

Goals:

- move read-only/mutating, approval, external-state, network, destructive,
  long-running, streaming, retry-safe, and parallel-safe metadata into the
  registry/descriptor layer
- make scheduler decisions consume registry metadata rather than adapter
  guesses
- require permission/approval checks in the runtime dispatch path
- cache approvals by normalized tool name, arguments, cwd, sandbox/network
  scope, and affected paths where applicable
- surface permission-required and approval-denied outcomes as `ToolResult`
  statuses that can be replayed to the model

Acceptance criteria:

- provider adapters only extract calls; they do not decide tool risk
- mutating/unsafe calls are serialized by default
- approval-denied and permission-required paths produce structured results and
  UI events
- tests cover denied, approved-once, approved-for-session, and unavailable-tool
  behavior

Phase 7 implementation note:

- `penguin.tools.schema_contract` defines the minimum model-visible tool schema
  contract: canonical name, description, input schema, and concise generated
  usage guidance.
- `ToolManager.get_model_visible_tools()` exposes that normalized contract
  without changing the legacy `get_tools()` schema shape that existing edit
  registry and UI tests compare exactly.
- `ToolRuntimeMetadata` extracts conservative runtime flags from tool schemas:
  mutating by default, approval-required by default, not parallel-safe by
  default, plus placeholders for risk, long-running, streaming, and retry-safe
  behavior.
- This metadata is intentionally observational for now. It does not enable
  parallel scheduling, bypass approval checks, or mark any unaudited tool safe.

### Phase 7.5: File Edit Tool Reliability Rewrite

Goals:

- replace the model-visible edit surface with one exact replacement tool and
  one Codex-style patch/hunk tool
- make every edit preflight against the current file contents before any write
- compute new file contents and diffs in memory, then write each changed file at
  most once per tool call
- remove `.bak` creation from edit tools entirely; if persistent recovery is
  needed later, store recovery artifacts under Penguin workspace storage, not in
  the target repository
- make `verify` mean expected old content or context matched before writing
- retire or hide `replace_lines`, `insert_lines`, `delete_lines`, and unsafe
  structured same-file `patch_files` from model-visible schemas
- preserve temporary compatibility wrappers only where required, and have them
  route through safe implementations or fail with clear deprecation errors

Acceptance criteria:

- `edit_file` accepts `path`, `old_string`, `new_string`, and optional
  `replace_all`; it fails when `old_string` is missing or ambiguous unless
  `replace_all` is explicit
- `apply_patch` accepts a strict Codex-style patch grammar with add, delete,
  update, move, and contextual hunks; missing context fails before writing
- multi-edit behavior is atomic per tool call: if any operation fails preflight,
  no file is written
- no successful or failed edit creates a `.bak` file in the target repository
- returned tool results include changed files, compact diff summary, structured
  failure reason, and enough metadata for first-class `ToolResult` records
- markdown-heavy edits reject or warn on obvious structural damage such as
  unbalanced fences, duplicated adjacent headings, or broken table headers
- tests cover stale line-coordinate reproduction, exact replacement ambiguity,
  missing context, rollback/no-write behavior, no-`.bak` behavior, and markdown
  table/heading preservation

File-by-file checklist:

- `penguin/tools/editing/contracts.py`
  - [x] Add typed request/result envelopes for exact replacements and
        Codex-style patch hunks.
  - [x] Mark legacy line-coordinate operations as compatibility-only.
- `penguin/tools/editing/service.py`
  - [x] Implement in-memory preflight/apply/write-once flow for exact
        replacements and patch hunks.
  - [x] Remove in-repo backup path expectations from edit results.
  - [x] Add optional markdown sanity checks for `.md`/`.mdx` targets.
- `penguin/tools/core/support.py`
  - [x] Remove direct `.bak` creation from legacy edit helpers; old `backup`
        arguments are compatibility-only and rollback uses in-memory snapshots.
  - [x] Keep low-level diff generation helpers side-effect free.
- `penguin/tools/tool_manager.py`
  - [x] Expose only `edit_file` and `apply_patch` as preferred model-visible
        mutation tools.
  - [x] Remove or hide line-coordinate schemas from model-visible output.
  - [x] Keep legacy aliases only as deprecation wrappers during migration.
- `penguin/tools/runtime.py`
  - [ ] Preserve edit metadata in `ToolResult` records: changed files, diff
        hashes, structured failure reasons, and truncation/artifact references.
- `penguin/engine.py`
  - [ ] Ensure edit failures are recoverable tool results, not assistant
        completion failures or loop-stall false positives.
- `tests/tools/test_edit_service.py`
  - [x] Cover exact replacement success, missing string, ambiguous string,
        replace-all, no-write-on-failure, and no `.bak` creation.
  - [x] Cover Codex-style patch success and missing-context failure.
  - [x] Cover markdown sanity checks for headings, tables, and fences.
- `tests/test_edit_contract_aliases.py`
  - [x] Update model-visible schema expectations for `edit_file` and
        `apply_patch`.
  - [x] Cover legacy alias deprecation wrappers.
- `tests/test_parser_edit_handlers.py`
  - [x] Update ActionXML/parser compatibility mapping to prefer the new
        canonical edit tools.
- `tests/test_core_tool_mapping.py`
  - [x] Update action-to-tool mapping tests for safe edit surfaces.

Current status:

- Phase 7.5 model-visible rewrite landed for `edit_file` and `apply_patch`.
- Legacy `patch_file`, `patch_files`, `replace_lines`, `insert_lines`,
  `delete_lines`, `regex_replace`, and `apply_diff` remain callable only as
  compatibility/deprecation paths; they are hidden from model-visible schemas
  and fail without writing through the edit service.
- Direct legacy support helpers no longer create repository `.bak` files; legacy
  multi-edit rollback uses in-memory snapshots.

Implementation guidance:

- Start exact and conservative. Do not add fuzzy matching in the first rewrite.
- Prefer refusing an edit over applying an unprovable mutation.
- Do not enable parallel edit execution.
- Do not keep `.bak` files as a default safety mechanism. Git, in-memory
  preflight, and structured failure behavior should carry the migration.
- Treat deletion of dead edit code as part of the reliability work once tests
  prove the replacement surface.

### Phase 8: Terminal/Process Runtime Foundation

Goals:

- define shell/process tool calls as a runtime family with lifecycle state
- support persistent PTY/process sessions, stdin writes, output polling,
  cancellation, interrupt/kill, cwd/env tracking, and exit-code/duration
  metadata
- stream stdout/stderr progress to UI events without dumping unbounded output
  into conversation history
- integrate sandbox, network approval, and permission metadata with process
  execution
- keep one-shot command execution as a compatibility wrapper over the process
  runtime where practical

Acceptance criteria:

- long-running commands can remain running without blocking or losing process
  identity
- process output is page-able/reusable by result/session id
- command timeout, cancellation, and user abort are distinguishable statuses
- dev-server/test-watcher/REPL workflows do not require rerunning commands just
  to recover state

Related plan:

- Larger terminal/process, debugger, dev-server, test-intelligence, and
  code-navigation tool suites remain tracked in
  `context/tasks/tool-system-future-improvements.md`. This phase only builds
  the runtime foundation those suites need.

## Non-Goals

- Do not remove ActionXML before a replacement path is stable.
- Do not enable provider parallel tool calls before the scheduler can handle
  them safely.
- Do not rewrite every tool implementation as part of the early IR/scheduler
  phases.
- Do not make the engine depend on OpenAI/Codex-specific types.
- Do not preserve the current giant action map as the long-term routing layer.
- Do not build debugger/dev-server/test-intelligence suites before the process
  runtime and tool-result persistence are stable.

## Risks

### Tool Persistence Drift

Changing how tool results are represented can break conversation history,
frontend timelines, or TUI rendering.

Mitigation:

- keep compatibility fields during migration
- add conversion helpers at the boundary
- test session message rendering and SSE events

### Permission and Safety Regression

Parallel or unified execution could accidentally bypass existing permission
checks.

Mitigation:

- put permissions in the scheduler/registry path
- make mutating tools serialized by default
- test denied, approval-needed, and read-only paths

### Tool Output Pressure

Large or noisy tool outputs can destabilize provider continuations, especially
after read/search/command-heavy turns.

Mitigation:

- enforce per-tool and aggregate model-visible output caps
- persist full output outside conversation history
- expose paging/search-by-result-id tools before encouraging large-output
  workflows
- add empty-response recovery for tool-heavy turns

### Provider Replay Drift

Native providers have different tool-call adjacency and id constraints.
Incomplete or malformed replay can turn successful tool execution into provider
errors or empty continuations.

Mitigation:

- persist canonical call/result pairs with stable ids
- persist call records before execution starts
- make adapters reconstruct provider-specific replay at the edge
- synthesize explicit failed/cancelled results for interrupted tool calls
- keep provider contract tests for replay ordering and id normalization

### Over-Abstracting Too Early

A generic runtime can become another abstraction layer without removing the old
coupling.

Mitigation:

- start with minimal IR and serial scheduler
- migrate one path at a time
- delete compatibility layers when their callers are gone
- keep the near-term tool-call IR under the tool runtime unless shared
  cross-domain execution primitives justify a broader runtime package

## Future Consideration: Shared Runtime Package

Do not introduce a generic `penguin/runtime/` package just to make the tool-call
IR feel more general. Keep the current work scoped to the tool-call execution
runtime until Penguin has shared lifecycle primitives that are useful across
tools, LLM/provider continuations, process sessions, sub-agents, approvals, and
replay.

A broader runtime package may make sense later if it can own concrete
cross-domain primitives such as:

- durable result records and artifact references
- cancellation tokens
- persistent process/session handles
- approval records and cached permission decisions
- execution leases
- replay records for interrupted, failed, cancelled, or resumable work

Until those primitives exist, `penguin/runtime/` risks becoming a vague bucket.
The safer near-term boundary is:

- `penguin.tools.runtime`: tool-call IR, tool-result IR, scheduling, truncation,
  replay, and dispatch-facing policy
- `penguin.llm.runtime`: provider/request helpers, native tool kwargs,
  provider-output diagnostics, and adapter-adjacent logic
- event/message buses: observation and routing, not execution lifecycle
  ownership

## Open Questions

Working decisions:

- Keep the near-term IR under `penguin.tools.runtime`. Revisit
  `penguin/runtime/` only when shared cross-domain primitives exist.
- Keep ActionXML multiple-call execution opt-in at first.
- Treat parallel-safe tool metadata as audit-required. No tool should become
  parallel-safe by default.
- Enforce a minimum registry contract before model-visible schemas come from
  the registry: canonical name, description, input schema, and concise
  model-facing usage guidance. Additional runtime fields such as handlers,
  aliases, risk metadata, approval policy, output policy, provider support,
  and UI presentation can remain incremental, but the minimum model-visible
  surface should be testable for every exposed tool.
- Adopt first-class session records as the long-term tool-result direction for
  all tools. Start with lightweight envelopes for every tool execution and
  store full outputs only when needed for truncation, artifacts, native replay,
  or process/session-backed workflows.
- Store full tool-output artifacts near Penguin workspace/conversation storage,
  with a dedicated result/artifact namespace and retention cleanup when the
  storage policy exists.
- Long-running process output should not be solved with one fixed output
  limit. It needs process/session records, pageable output, cancellation, and
  model-visible `ToolResult` references to current output slices.
- Defer aggregate per-turn model-visible tool-output caps until the first-class
  record and replay boundary is stable. When implemented, express the policy as
  a percentage of usable provider context plus an absolute ceiling, but split it
  into a later PR because it is less urgent than durable records and replay
  correctness.

Remaining questions:

- Which concrete first-pass tools are read-only enough to mark parallel-safe
  after audit?
- Which registry fields are required before model-visible schemas can come
  entirely from the registry beyond the minimum model-visible contract?
