# Penguin ACP (Agent Client Protocol) implementation

Status: phased implementation in progress. Date: September 28, 2026.

Current local baseline: uncommitted ACP adapter and its in-process tests were already present when this checklist was created. This plan does not claim that code as completed end-to-end. Independent additions in this phase: subprocess SDK wire tests in `tests/integrations/test_acp_wire.py`. Installed SDK tested: `agent-client-protocol==0.12.1` on Python 3.12. **Version gap:** the published v1 schema now requires prompt `resource_link`, but this installed SDK's `PromptRequest` union does not include it. Resolve by upgrading to a compatible SDK or explicitly implementing/version-negotiating the missing wire shape before claiming published v1 conformance; do not mark resource links supported based on the current SDK. `pytest -q tests/integrations/test_acp_server.py tests/integrations/test_acp_wire.py`: 7 passed; full matrix, live editor, and actual CLI startup remain unverified.

## Contract and scope

Build a **Penguin-as-agent** adapter for editor/client-facing ACP; this is independent of the A2A agent-to-agent server in PR #105 (merged). Target the stable **ACP v1** schema and official Python SDK, pin and test the chosen SDK/schema version before implementation. Do not conflate ACP with IBM's former Agent Communication Protocol or with MCP. Support every applicable v1 capability below or explicitly document a principled unsupported decision; never advertise a capability before its behavior and tests exist. Track v2/draft features separately; they are not acceptance criteria for v1.

Primary sources (recheck versions before each phase):
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/overview.mdx
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/session-setup.mdx
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/schema/v1/schema.json
- https://github.com/agentclientprotocol/python-sdk/blob/main/docs/quickstart.md

### v1 wire inventory (checked against the published v1 schema, September 28, 2026)

The checklists below are the implementation work; this inventory is the completeness audit. "Optional" means an honest unsupported capability/explicit error is acceptable, not that it can be silently ignored. v1 **agent methods**: `initialize`, conditional `authenticate` and `logout`, `session/new`, conditional `session/load`, `session/list`, `session/delete`, `session/resume`, `session/close`, `session/set_mode`, `session/set_config_option`, `session/prompt`. **Agent-to-client notification**: `session/update`; **client-to-agent notifications**: `session/cancel`, `$/cancel_request`; **client RPCs** the agent may invoke: `session/request_permission`, `fs/read_text_file`, `fs/write_text_file`, `terminal/create`, `terminal/output`, `terminal/release`, `terminal/wait_for_exit`, `terminal/kill`, `elicitation/create`; **client-to-agent notification**: `elicitation/complete`. Condition each invocation on advertised peer capabilities and schema support.

Capability families to verify: `AgentCapabilities.loadSession`, `promptCapabilities` (image/audio/embeddedContext), `mcpCapabilities` (http/sse; stdio server descriptors exist independently), `sessionCapabilities` (list/delete/additionalDirectories/resume/close), `auth`; `ClientCapabilities.fs`, `terminal`, `session` (including boolean config options where negotiated), `auth`, `elicitation` (form/url). Session updates: `user_message_chunk`, `agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`, `plan`, `available_commands_update`, `current_mode_update`, `config_option_update`, `session_info_update`, `usage_update`. Prompt block types: text/resource_link (both required baseline inputs), image/audio/resource (conditional on support and negotiation). Stop reasons: `end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`. Check each variant's required fields, absolute-path and 1-based-line invariants, size and security constraints against the pinned SDK rather than treating this paragraph as a schema substitute. `session/fork` and `session/set_model` are **not** in the published v1 schema.

Local seams: `penguin/cli/entrypoint.py`, `penguin/core_runtime/process_facade.py`, `penguin/core_runtime/streaming_facade.py`, `penguin/core_runtime/stream_events.py`, `penguin/security/tool_approval.py`, `penguin/integrations/mcp/config.py`. The A2A HTTP handler is **not** an ACP backend; reuse Penguin core APIs rather than calling A2A endpoints or routing through the web server.

## Phase 0 — contract, ownership, and test harness

- [ ] Inventory stable v1 schema methods, capability flags, content block and update variants, stop reasons, error codes and SDK version; the wire inventory above covers method/capability/variant names but not the pinned SDK version or detailed error/schema requirements.
- [x] Choose optional dependency (`agent-client-protocol`) and isolate its Pydantic 2 requirement in the `acp` extra; compatibility across the supported Python/Pydantic matrix remains unverified.
- [x] Choose `penguin acp` as stdio entry point; verify stdout cleanliness with a subprocess wire test (including startup failures) before checking off transport correctness.
- [ ] Decide one ACP session = one Penguin conversation + immutable effective roots + per-session runtime state; document lifecycle after process exit/reconnect and per-session concurrency policy.
- [ ] Complete subprocess wire tests using the official SDK/client and deterministic fake core/provider, including malformed JSON-RPC, version negotiation, disconnect, and clean stdout; SDK-based subprocess tests now cover valid/invalid handshake, sessions, multi-turn updates and unsupported input with a fake core, but not malformed frames, disconnect, startup, or actual CLI startup.

## Phase 1 — runnable baseline (do not claim full ACP yet)

- [x] Add opt-in stdio agent entry point and initialize handshake with minimal advertised capabilities; no HTTP listener or A2A dependency. Wire and version-negotiation tests still pending.
- [x] Implement basic `session/new`: absolute existing authorized `cwd`, independent conversation ID; explicitly reject requested MCP servers and additional directories until supported.
- [x] Implement basic `session/prompt` with text blocks and existing `core.process` path using a scoped conversation/working directory context; verify continuation and path policy end to end.
- [ ] Support baseline `resource_link` prompt blocks safely (path/URI parsing and authorized resource handling). The present text-only adapter rejects them; do not call v1 input coverage complete yet.
- [ ] Emit correctly ordered `session/update` agent text chunks and one terminal `session/prompt` response with valid stop reason; distinguish normal end, provider failure, user cancellation and incomplete work without inventing a success message.
- [ ] Harden existing `session/cancel` against quiet provider/tool phases and completion races; prove the session remains usable and final status reflects actual stop.
- [ ] Harden existing fail-closed validation for missing sessions, wrong request shape, unsupported content blocks and concurrent prompts; a process-wide execution lock currently serializes turns to protect shared conversation state.
- [ ] Test new → two prompts → updates → final, two interleaved sessions, cancellation races, tool/provider errors, EOF/restart and stderr/stdout separation; exercise a real ACP client/editor.

## Phase 2 — sessions, persistence, and complete lifecycle

- [ ] Implement `session/load` and advertise `loadSession` only after restoring Penguin conversation/context and replaying **all retained history** as ordered `session/update` notifications *before* returning; preserve role, tool, and reasoning visibility rules.
- [ ] Implement optional v1 `session/resume` without replay, `session/list` with stable metadata/filter/pagination, `session/delete`, and `session/close` with cancellation/cleanup; advertise each only when actually supported by the pinned v1 schema and runtime. `session/fork` is **not** in the current v1 schema; evaluate it separately as an extension or future version, not a v1 gate.
- [ ] Validate session ownership/workspace roots on load/resume; prevent cross-session/cross-root reads, stale IDs, privilege escalation on reload, and duplicate execution after reconnect.
- [ ] Decide and implement `additionalDirectories` only with explicit path validation and policy integration; advertise only if supported. Use session `cwd` as relative-path base, not the process launch directory.
- [ ] Test restart/replay with user, assistant, tool calls/results, interrupted and failed turns; concurrent sessions; close while busy; session IDs and path changes after restart.

## Phase 3 — editor-grade progress and user interaction

- [ ] Bridge runtime tool start/progress/update/finish into ACP tool-call updates with stable IDs, names, kind, locations and bounded content; every started tool reaches a terminal status, including denied/interrupted tools.
- [ ] Send plan updates, meaningful usage/cost and mode/model/session-info updates where genuine data exists; do not fabricate metrics or expose hidden reasoning by default.
- [ ] Render file edits as editor-friendly diffs/file locations and shell operations as bounded command/output, sanitizing secrets and unsafe paths; keep streaming text and tool status in correct per-session order.
- [ ] Bridge Penguin's approval manager to ACP `session/request_permission` with scoped options (one-time/session/deny as permitted), timeout/disconnect denial, policy precedence, and no global approval leakage between sessions.
- [ ] Support client questions/clarifications and replies via the ACP-supported mechanism or clearly specify the v1-compatible fallback; never hang awaiting a UI event the client cannot answer.
- [ ] Test approval allow/deny/timeout, slow tools, duplicate/late updates, tool failure after cancel, and cross-session event isolation.

## Phase 4 — complete advertised inputs, capabilities, configuration

- [ ] Handle supported ACP prompt content block variants: text, images and embedded/linked resources (including binary size, media type and path safety); reject unsupported types explicitly rather than flattening or discarding them.
- [ ] Attach `session/new`/load-provided MCP servers (stdio and supported remote transports) to that session only, with lifecycle/reconnect, credential isolation, policy checks and clean shutdown; test multiple servers and failure modes.
- [ ] Implement filesystem read/write and terminal client RPCs *only if needed* and only when the client advertises them; otherwise use Penguin tools under normal permission policy, and avoid capability claims implying remote client RPC use.
- [ ] Implement applicable v1 authentication methods (`authenticate`, optional `logout`, setup flow/`auth_required` when appropriate) without accepting editor authentication as tool authority; redact credentials from updates/logs.
- [ ] Implement v1 `session/set_mode` and `session/set_config_option` for model/mode discovery and selection using Penguin's supported models and policies; validate IDs, isolate changes per session, and emit correct state changes. `session/set_model` is **not** a current v1 method; model selection belongs in config options if supported.
- [ ] Implement client-facing `elicitation/create` and `elicitation/complete` for supported interactive prompts if the pinned v1 SDK and negotiated client support them; otherwise document an explicit fallback with no indefinite waits.
- [ ] Handle v1 `$/cancel_request` where applicable, keeping request cancellation separate from `session/cancel`.
- [ ] Advertise commands and session metadata/title/usage capabilities only with concrete handlers and correct notifications; decide on registry `agent.json` distribution separately from protocol conformance.
- [ ] Check every applicable method, enum/variant and capability in the pinned schema against implemented behavior; explicitly mark v1 optional features supported, deliberately unsupported, or not applicable.

## Phase 5 — conformance, packaging, and release

- [ ] Add schema/SDK contract tests for all advertised methods and bidirectional requests; negative tests for unknown methods, invalid params, unsupported client capabilities, EOF and interrupted streams.
- [ ] Exercise official SDK client plus at least one real editor through install, multiple sessions, tools, permissions, images/MCP (if advertised), cancel, reconnect, and reload; document results and known client differences.
- [ ] Verify path containment and permission policy, authorization lifetime, concurrent turn isolation, backpressure/output limits, secret redaction, shutdown cleanup and crash/restart behavior.
- [ ] Document install/opt-in invocation, editor configuration, capabilities, auth/setup, troubleshooting and actual limitations; update public docs/API and packaging metadata.
- [ ] Run narrow unit/contract tests, supported Python/Pydantic matrix, lint/type checks, then editor smoke tests; record exact evidence before declaring full v1 support.

## Phase gates

- Phase 1: a real editor can launch Penguin, create a session, prompt twice and cancel without a web service.
- Phase 2: a restart can reload a conversation with accurate replay and no cross-session state leaks.
- Phase 3: tools and approvals are visible, scoped, and terminate correctly under failure/cancel.
- Phase 4: every advertised capability is demonstrably implemented; unsupported v1 options are explicit.
- Phase 5: conformance/security/interop evidence supports the public claim. A2A/Link tests are separate and not ACP acceptance evidence.
