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
- completion-tool guidance does not conflict with native `finish_response` and
  `finish_task` calls

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
- apply a single truncation policy to all model-visible tool outputs
- preserve full raw output in a local artifact/result store when truncated
- include line count, byte count, truncation direction, output hash, and output
  artifact path/reference in `ToolResult`
- enforce an aggregate per-turn model-visible tool-output cap in addition to
  per-tool caps
- make provider replay reconstruct native tool-call and tool-result adjacency
  from persisted `ToolCall` / `ToolResult` records
- convert interrupted, pending, or cancelled historical tool calls into
  explicit error/cancelled tool results during replay

Acceptance criteria:

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

- Should the IR stay under `penguin/tools/` until shared runtime primitives
  justify introducing `penguin/runtime/`?
- Should ActionXML multiple-call execution remain opt-in at first?
- Which tools are safe enough to mark parallel-safe initially?
- Should model-visible tool schemas come entirely from the registry?
- How should long-running process tools stream output into `ToolResult` records?
- Should tool results be persisted as first-class session records rather than
  action-result messages?
- Should full tool output artifacts live in conversation storage, workspace
  artifacts, or a dedicated result store with retention cleanup?
- What aggregate per-turn model-visible tool-output cap should Penguin enforce
  by default?
