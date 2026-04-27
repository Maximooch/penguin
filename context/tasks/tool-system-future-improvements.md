# Tool System Future Improvements

## Purpose

This document captures tool-system ideas that are adjacent to, but not required
for, the current tool-call runtime refactor.

The current runtime work is focused on first-class `ToolCall` / `ToolResult`
flow, native provider tool calls, serial scheduling, and later safe parallel
execution. This follow-up plan is about making Penguin's tools more useful,
observable, and Codex-like after that foundation is stable.

This is explicitly future work for a later tool-focused PR.

## Guiding Direction

Penguin should not only have more tools. It should have tools with:

- lifecycle state
- stable identity
- risk metadata
- cancellation and timeout behavior
- replayable or inspectable results
- UI-visible progress
- provider-neutral model feedback

That moves Penguin away from a larger ActionXML toolbox and toward a runtime
where tools are durable execution units.

## Priority 1: Terminal And Process Handling

Terminal handling is likely the highest-leverage improvement after the core
runtime refactor.

Current shell-style tools are useful, but many agent workflows need a persistent
process abstraction rather than one-shot command capture.

Target capabilities:

- create persistent PTY sessions
- run commands in a named session
- send stdin to a running process
- poll recent output without ending the process
- stream output incrementally to the UI
- interrupt or kill a process
- distinguish running, exited, timed out, and cancelled states
- preserve cwd and env per session
- track command exit code, duration, and truncation status
- support dev servers, REPLs, test watchers, debugger sessions, and long builds

Codex parity angle:

- closer to `exec_command` plus `write_stdin`
- smoother handling for long-running commands
- fewer cases where the model reruns commands because process state is opaque

## Priority 2: Tool Result Identity And Observability

The `ToolCall` / `ToolResult` refactor creates the right foundation. Follow-up
work should make result identity and observability more complete.

Target capabilities:

- stable call id for every tool invocation
- normalized tool name and arguments hash
- result hash for repeated-loop detection
- started and ended timestamps
- duration and timeout metadata
- cwd and environment summary for process tools
- exit code for command tools
- truncation metadata
- persisted full output reference when model-visible output is truncated
- UI status for pending, running, completed, cancelled, timed out, and failed

Loop-control angle:

- repeated-loop guards should reason from tool identity and result hashes, not
  text previews
- empty tool-only turns should be explainable from structured state

## Priority 3: Approval, Risk, And Capability Metadata

Before broad parallel execution or richer tool suites, Penguin needs a stronger
tool metadata model.

Useful metadata:

- read-only
- writes workspace
- mutates external state
- network access
- destructive potential
- long-running
- streams output
- parallel-safe
- requires approval
- can be retried safely

Ownership:

- metadata should live in a registry or tool descriptor layer
- adapters should not guess safety when registry metadata exists
- conservative defaults should remain the fallback

Scheduler angle:

- safe parallelism depends on this metadata
- provider `parallel_tool_calls` should only be enabled when Penguin can honor
  the same safety contract locally

## Priority 4: Truncation, Paging, And Result Reuse

Large tool outputs need first-class handling.

Target capabilities:

- preserve full output locally when model-visible output is truncated
- include clear truncation markers and byte/line counts
- expose a follow-up tool to read more from a previous result id
- support paging by line range or byte range
- allow summarizing large output without discarding the source
- avoid rerunning expensive commands just to recover truncated output

Potential tools:

- `read_tool_result`
- `summarize_tool_result`
- `search_tool_result`

## Tool Suite Ideas

### Debugger Suite

Debugger tools could be a major differentiator because many coding agents still
fall back to tests, logs, and print statements.

Python targets:

- launch script or test under `debugpy`
- attach to a running debug session
- set and clear breakpoints
- continue, step, next, and pause
- inspect stack frames
- inspect locals and globals
- evaluate expressions
- stop on exception

TypeScript / JavaScript targets:

- launch Node with inspector
- connect via Chrome DevTools Protocol
- set breakpoints
- inspect stack and scopes
- evaluate expressions
- capture console output and runtime exceptions

Initial version can be deliberately small:

- Python-only `debugpy` launch and attach
- breakpoint, continue, stack, locals, evaluate
- no UI polish required beyond structured tool results

### Dev Server And Process Suite

Common app workflows need process lifecycle tools.

Target capabilities:

- start dev server
- wait for port or health endpoint
- tail logs
- restart server
- stop server
- detect existing server ownership
- avoid stealing reserved or user-owned ports
- expose server URL to the UI

This should build on the terminal/process abstraction rather than separate
ad-hoc subprocess handling.

### Test Intelligence Suite

Testing tools should move beyond raw test command execution.

Target capabilities:

- run impacted tests for changed files
- parse failures into file, line, assertion, and traceback sections
- rerun failed tests
- detect deterministic vs flaky failures where possible
- collect coverage around touched files
- suggest likely owning code paths
- preserve full test output with model-visible summaries

This suite should remain deterministic and should not invent test results.

### Code Navigation Suite

Penguin already has LSP-adjacent surfaces. A stronger code navigation suite
would reduce brute-force grep and repeated file reads.

Target capabilities:

- symbol search
- definition lookup
- references lookup
- file outline
- workspace dependency graph
- call graph where supported
- diagnostics by file
- formatter and lint status by file

Implementation should reuse existing LSP/indexing work where possible.

### Patch And Edit Suite

Codex has a strong patch primitive. Penguin should eventually have similarly
structured edit operations.

Target capabilities:

- apply structured patch
- dry-run patch
- validate patch against current file hashes
- report conflicts without partial writes
- format touched files after patch where configured
- summarize resulting diff
- associate edits with tool call ids

This should remain separate from bulk refactors or automatic code generation.

### Browser And Runtime Inspection Suite

For web apps, runtime inspection can catch issues tests miss.

Target capabilities:

- open local page
- take screenshot
- capture console logs
- capture network errors
- inspect DOM text and selectors
- query accessibility tree
- click, type, and navigate
- record short interaction traces

This can initially target local development URLs and should respect Penguin's
existing port and server ownership rules.

## Suggested Sequencing

1. Finish the current serial native-tool runtime and provider tool support.
2. Add terminal/session/process lifecycle as first-class tools.
3. Add tool metadata for risk, approval, streaming, and parallel safety.
4. Add truncation, paging, and result reuse.
5. Build debugger and dev-server suites on top of the process abstraction.
6. Expand test intelligence and code navigation suites.
7. Add safe parallel scheduling once metadata and lifecycle behavior are stable.

## Non-Goals For The Next Tool PR

- Skills
- MCP integration
- replacing every existing tool implementation
- enabling provider parallel tool calls before local scheduling is ready
- building a full IDE debugger UI

## Open Questions

- Should persistent process sessions live under `penguin/tools`, a new
  `penguin/runtime`, or a dedicated `penguin/process` package?
- Should full tool output be stored in conversation history, local artifacts, or
  a separate result store?
- Which metadata fields are required before Phase 6 parallelism should proceed?
- Should debugger support start Python-only, or should Node inspector support be
  designed at the same time?
- How should the TUI represent long-running tool calls without overwhelming the
  conversation transcript?
