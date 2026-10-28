# ACP editor integration

Install `penguin-ai[acp]`, then configure your ACP client to execute `penguin acp`
in the authorized workspace. This starts a stdio agent directly, without a web
server. Configure the Penguin provider as usual before starting the agent.

Current baseline: new sessions, text and resource-reference prompts, streamed
assistant text, one-time tool approvals, and cancellation. Tool starts/results
and todo plans are delivered as native ACP updates with stable call IDs. Display
output is bounded; file locations are resolved inside the session workspace.
Returned unified diffs are displayed as diff text (not fabricated full-file
before/after snapshots). Interrupted tools receive failed terminal updates;
duplicate and unrelated-session events are suppressed. ACP-created sessions
store workspace ownership in Penguin's native session store and visible updates
in an append-only journal beneath that store. Load replays the journal before
returning; resume restores without replay; close detaches without deleting history. List supports
workspace filtering and pagination. Legacy sessions without ACP ownership are
not exposed. Interrupted tool entries replay as failed, without re-execution.
Turns and lifecycle operations are serialized because the core conversation
manager is shared. Embedded context is supported with persistent attachment
storage. PNG/JPEG/WebP image input is advertised only for a vision-enabled model.
Client MCP servers are scoped to the session and combined with configured
Penguin servers. Stdio, HTTP and SSE transports use the existing MCP client;
tool execution still passes through normal tool permissions. Client environment
values are literal and client credentials are not persisted in the transcript.
Servers must be resent on load/resume and are closed with the session.
Configured model selection is exposed as an ACP session option. It uses
request-scoped model/runtime overrides and does not change other sessions or the
global default. Build mode uses normal permission policy; Plan mode is offered
only while the tool permission enforcer is enabled and blocks mutating tools.
Mode/model settings persist across resume. `/status` and `/mcp` provide read-only
session information without making a model request. Deletion is not supported
yet; experimental negotiated child sessions are described below. Do not
interpret this as full ACP parity.

Provider authentication uses the existing local Penguin configuration. This
adapter does not advertise an interactive ACP authentication flow. Model choices
that lack configured credentials are rejected without changing the session.

Resource links are passed to the agent as clearly labeled context references.
The adapter does not fetch their contents or grant file/network permission. Local
file URIs must resolve inside the session workspace, including after decoding
and symlink resolution. Ordinary tools and permission policy govern later reads.
Remote URIs remain references, without an automatic network request.

Images and embedded binary resources are stored by content hash under the native
session store's `acp-assets` directory. Images use Penguin's native image input;
binary resources become inert attachment references. Embedded text remains
labeled untrusted context. Per-binary limits are 10 MiB, total attachments 20 MiB,
and images 40 million pixels. The bytes remain available after close so future
turns can reuse their attachments. No attachment is executed automatically.

Diagnostic prints go to stderr; protocol frames always go to the original
stdout stream, including on Windows. Clients must keep stdin open for the session
and send newline-delimited JSON-RPC. Provider errors become protocol errors;
explicit provider stop reasons are preserved.

## Validation

Streaming appends one record per update rather than rewriting growing history.
Native model state is checkpointed at turn boundaries. An incomplete final
journal write is discarded on recovery; malformed complete records fail closed.
Loading replays history only to the client; it does not inject the full transcript
into model context or bypass Penguin's context-window policy.

`python -m pytest tests/integrations/test_acp_server.py tests/integrations/test_acp_wire.py -q`

The suite uses the official SDK client over subprocess stdio and the real CLI
entrypoint with a deterministic fake provider core. This proves routing/framing,
not a live provider or editor interaction. An actual editor smoke test remains
required before claiming the complete user workflow.

## Planned PR series

1. Baseline resource inputs, protocol output, failures and wire validation (implemented).
2. Tool results, plans and bounded output (implemented); native complete-file
   diff previews and finer execution progress still need runtime evidence.
3. Session persistence, history replay, list/resume/close (implemented).
4. Image and embedded-resource input (implemented).
5. Per-session client MCP servers (implemented; SDK 1.x compatibility pin).
6. Model/mode selection and command discovery (implemented); interactive ACP
   authentication remains unsupported, using existing local provider setup.
7. Child-agent and background-task visibility using negotiated capabilities.
8. Remaining client filesystem/terminal integration, concurrency and interop audit.

Stable v1 requirements and negotiated optional capabilities are separate from
draft v2, draft subagent protocols and client-specific AIR extensions. Each PR
must document precisely what it advertises and proves. The process/subagent
runtime reliability PR is a dependency of later runtime-backed integrations,
not part of the baseline.

## Experimental child sessions

Clients that explicitly advertise the current draft `clientCapabilities.subagents`
receive separate child-session associations, observed directed messages, tool
updates, public assistant output and work-state changes. Announcement precedes
all child traffic. The SDK currently drops that draft capability, so the stdio
transport observes it before SDK validation; ordinary RPC dispatch remains in
the SDK. No draft updates are sent without negotiation. This is the current
subagent RFD, not ACP v2 or the older AIR-specific shape.

Background children with independent runtime tasks may advertise targeted cancel.
Foreground children sharing their parent's task do not advertise independent
cancel, since cancelling that task would also cancel the parent. On reload,
historical associations carry no effective cancel authorization, and current
activity is unknown unless this process still observes a live child. Nested
parentage is retained. Clients without the draft capability get ordinary parent
tool cards instead. Shared-session children do not become fake separate sessions.

The current tests use the real runtime lifecycle producer with deterministic
core/scope fixtures over raw stdio, plus cancellation and replay contracts. They
do not claim verification in a particular GUI editor. Background shell-task
panels and client-specific goal extensions remain separate work.
