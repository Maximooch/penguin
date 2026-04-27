# pi-mono Reference Review

Date: 2026-04-27

## Executive Take

`reference/pi-mono` is a strong reference for Penguin, but it should be treated as a catalog of runtime contracts and UI/runtime patterns, not as a codebase to copy wholesale.

The most valuable ideas are the explicit agent event stream, the separation between rich application messages and provider-ready LLM messages, disciplined tool execution semantics, append-only session trees, compaction metadata, and a broad extension surface that includes tools, commands, lifecycle events, keybindings, and UI primitives.

Penguin is already more ambitious in backend scope: multi-agent orchestration, project/task lifecycle, context-window categories, web/API surfaces, and durable runtime state. pi-mono's best role is to sharpen Penguin's public contracts so every surface tells the same runtime truth.

## High-Value Ideas For Penguin

### 1. Canonical Agent Event Stream

pi-mono documents a clean event sequence:

- `agent_start`
- `turn_start`
- `message_start`
- `message_update`
- `message_end`
- `tool_execution_start`
- `tool_execution_update`
- `tool_execution_end`
- `turn_end`
- `agent_end`

This is one of the highest-leverage references for Penguin. Penguin already has event buses, UI emission, SSE/WebSocket pathways, and task lifecycle events, but the risk is surface drift: CLI, web, TUI, and Python wrappers can accidentally expose different interpretations of the same run.

Recommendation: define one canonical Penguin runtime event envelope and adapt all interfaces from it. The envelope should support session id, agent id, task id, message id, turn id, lifecycle phase, payload type, and source timestamps.

### 2. AgentMessage vs LLM Message Boundary

pi-mono's `AgentMessage[] -> transformContext() -> AgentMessage[] -> convertToLlm() -> Message[] -> LLM` flow is a clean separation of concerns.

Penguin should keep rich internal messages for:

- UI-only notifications
- task/clarification events
- tool progress
- context artifacts
- memory notes
- multimodal attachments
- agent-to-agent messages

Only provider adapters should see the provider-ready message representation. This would reduce adapter leakage and make context-window policy easier to reason about.

Penguin already has category-aware context management; pi-mono's model reinforces that the provider boundary should be late, explicit, and testable.

### 3. Tool Execution Semantics

pi-mono's tool execution model is worth formalizing in Penguin:

- default parallel execution
- sequential preflight and validation
- allowed tool calls execute concurrently
- completion events emit in completion order
- persisted tool-result messages remain in assistant source order
- per-tool sequential override for unsafe tools
- `beforeToolCall` and `afterToolCall` hooks
- early termination only when all tool results in a batch agree

This is directly relevant to Penguin because file mutation, shell execution, and project state updates cannot be treated like arbitrary pure functions. File writes/patches should generally force sequential or queued execution. Read-only calls can be parallelized aggressively.

Recommendation: adopt explicit per-tool execution policies in Penguin's tool registry:

- `read_parallel_safe`
- `mutation_exclusive`
- `requires_confirmation`
- `cancel_safe`
- `streaming_result`
- `terminal_tool`

### 4. Append-Only Session Tree

pi-mono's session model has entries with ids and parent ids, including messages, model changes, thinking-level changes, compactions, branch summaries, labels, session info, custom entries, and custom messages.

This is a better conceptual primitive than treating history as just a flat message list plus side-channel metadata.

Penguin already has sessions, checkpoints, projects, todos, and memory. The useful reference is the append-only event-sourced flavor:

- replayable history
- branch/fork support
- custom extension data that does not enter LLM context
- custom message data that does enter LLM context
- labels/bookmarks on entries
- explicit compaction records

Recommendation: consider a unified append-only run/session ledger underneath Penguin sessions and task execution. Build projections for UI, context-window input, task state, and audit views from that ledger.

### 5. Compaction Metadata For File Continuity

pi-mono stores compaction details such as read files and modified files. That is simple but powerful.

Penguin's context window manager is already more sophisticated, but file-operation continuity should be first-class. A compacted session should retain enough structured facts to answer:

- What files were read?
- What files were modified?
- What commands/tests were run?
- What failed?
- What user decisions constrained the work?
- What acceptance criteria were satisfied?

Recommendation: add or standardize structured compaction artifacts in Penguin. Avoid only prose summaries; prose rots and is hard to verify.

### 6. Extension Surface

pi-mono's extension types cover lifecycle events, LLM-callable tools, commands, keybindings, CLI flags, and UI interactions. This is the right direction for Penguin as a platform.

Penguin's tool/plugin system can borrow the shape without copying implementation:

- lifecycle hooks
- command registration
- UI primitive abstraction
- autocomplete provider extension
- footer/header/widget injection
- session compaction hooks
- tool wrapping and policy hooks

The key is restraint. Penguin should not add a giant plugin API before stabilizing the core event/session/tool contracts.

### 7. TUI Ergonomics

pi-tui has serious terminal craftsmanship:

- differential rendering
- synchronized output
- overlay stack
- hardware cursor positioning for IME
- bracketed paste handling
- autocomplete and editor primitives
- inline image support

Penguin currently uses an OpenCode-derived sidecar path. That is a different architecture, so pi-tui is not directly portable. But the behavioral checklist is valuable for TUI quality audits.

Recommendation: use pi-tui docs/code as a regression checklist for Penguin TUI behavior, especially paste handling, resize behavior, cursor correctness, overlays, and terminal capability detection.

## Areas To Avoid Copying Blindly

### 1. Large God Files

Some pi-mono files are very large, including `agent-session.ts` and `editor.ts`. The behavior may be valuable, but the structure is not ideal as a target for Penguin. Penguin should keep runtime, persistence, UI, tool policy, and compaction concerns modular.

### 2. Token Estimation Heuristics

pi-mono uses approximate token estimation in parts of compaction. Penguin should prefer provider usage data, tokenizer-specific accounting where available, and category budgets already present in its CWM design.

### 3. Simpler Kernel Assumptions

pi-mono's agent loop is simpler than Penguin's architecture. Penguin has multi-agent orchestration, task/project lifecycle, clarification handling, API/TUI alignment, and persistent memory. pi-mono is useful as a primitive reference, not a replacement kernel.

### 4. License And Provenance Risk

Before copying code, verify license compatibility and provenance. Use ideas and interface patterns unless direct code reuse is explicitly safe.

## Recommended Penguin Follow-Ups

1. Write `context/review/runtime-event-contract.md` defining Penguin's canonical event model.
2. Audit web/API/TUI/Python surfaces against that event model.
3. Add per-tool execution policy metadata to the tool registry.
4. Introduce source-order vs completion-order semantics for parallel tool batches.
5. Define an append-only session/run ledger model and map current sessions/checkpoints/tasks to it.
6. Add structured compaction artifacts for file operations, commands, tests, errors, and acceptance criteria.
7. Use pi-tui behavior as a TUI quality checklist, not a frontend rewrite mandate.

## Bottom Line

pi-mono's leverage for Penguin is contract discipline. It shows how a relatively small runtime can become easier to reason about by making event flow, message conversion, tool execution, session persistence, and extension hooks explicit.

Penguin should absorb those contracts, then apply them at Penguin scale: multi-agent, task-aware, web/API aligned, and persistence-first.

The strategic move is not "port pi-mono." The move is: use pi-mono to harden Penguin's runtime truth so every interface becomes a projection of the same underlying system instead of a separate story.
