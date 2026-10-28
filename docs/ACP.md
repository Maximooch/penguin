# ACP editor integration

Install `penguin-ai[acp]`, then configure your ACP client to execute `penguin acp`
in the authorized workspace. This starts a stdio agent directly, without a web
server. Configure the Penguin provider as usual before starting the agent.

Current baseline: new sessions, text and resource-reference prompts, streamed
assistant text, one-time tool approvals, and cancellation. Tool starts/results
and todo plans are delivered as native ACP updates with stable call IDs. Display
output is bounded; file locations are resolved inside the session workspace.
Canonical asynchronous file edits expose native before/after snapshots from
the authorized transaction, without additional file reads. Snapshots are complete
or explicitly omitted above 128 KiB (16 files per tool call); deletion remains
a textual result. Other returned unified diffs remain diff text. Interrupted tools receive failed terminal updates;
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
session information without making a model request. Owned session deletion and
experimental negotiated child sessions are described below. Do not
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

October 28 code-head validation (#151): 111 combined ACP, native Windows process
and environment-policy checks passed on Windows Python 3.11.14, without skips.
Scoped Ruff and pinned uv 0.11.2 lock validation passed. #149's full CI matrix
passed; final code-head CI is tracked separately from local results.

The current implementation/unsupported-feature matrix and draft dependency
graph live in [the conformance audit](../context/tasks/acp.md). Optional editor
filesystem/terminal RPCs, parallel root turns, persisted
permission grants and interactive ACP authentication remain deliberately absent.

Additional session roots are accepted only as absolute existing directories inside
the adapter's launch-authorized roots. They are fixed during a turn; loading or
resuming activates the complete supplied list (omitting it narrows to cwd alone).
Roots are reported by session/list. They preserve cwd as the relative
path base, propagate to child file-tool scopes and permit resource references and
native diff locations in those directories. File-tool attempts outside the scoped
set are rejected even if an ordinary tool context tries to override the root list.
The session's private attachment-copy directory is also available to file tools,
so attached resources remain usable; other sessions' storage is not included.
This is a file-tool boundary, not an OS sandbox for shell commands or MCP servers.

## Planned PR series

1. Baseline resource inputs, protocol output, failures and wire validation (implemented).
2. Tool results, plans, bounded output and native canonical-edit snapshots
   (implemented); process output also updates outside the initiating turn.
3. Session persistence, history replay, list/resume/close/delete (implemented).
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
the SDK except published `session/delete` and `session/prompt`, dispatched through
explicit schema-validated handlers for deletion and exact-request cancellation. No
draft updates are sent without negotiation. This is the current
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
client-specific goal extensions remain separate work.

## Background processes

Real scoped process events create separate execution cards that remain live after
the initiating model turn. They show a bounded output tail, exit status and
capture failures. They do not poll or advance the model's output cursor. Reload
checks an existing root-session process handle without consuming output; absent
handles produce an explicitly unknown outcome, never a claimed successful exit.
Historical child-process cards replay, but reconnecting child process activity is
not reconstructed without a live observed child. These cards are ACP tool updates,
not a claim to implement a client-specific task panel or terminal RPC.

The producer regression runs a real subprocess on Windows and Linux. It includes
the separate Windows ProcessRuntime capture fix (#146) as an explicit dependency.
Windows tree termination uses taskkill, not Job Object ownership; detached-child
cleanup guarantees are outside this adapter's claims.

`session/delete` is advertised only by the transport with its installed handler.
It rejects busy sessions and unresolved background processes, checks indexed ACP
workspace ownership, and deletes the native conversation plus its replay journal
and attachment directory. Close merely detaches; delete is permanent.

## Questions

The actual Penguin question tool uses form elicitation when the client explicitly
advertises it. This optional SDK feature remains experimental. Single-choice,
free-text and fixed multi-choice answers are validated before resolving the
question. Unsupported clients and custom multi-select questions receive the
question and choices as text for the user's next message, and the pending tool
request is rejected immediately rather than waiting for a missing web UI.
Cancellation and disconnect reject pending forms; late replies cannot revive
them. No answers or approval authority are inferred from a declined form.

Context usage comes from Penguin's session-scoped telemetry after each turn or
from an explicitly scoped token event. The adapter sends current context tokens
and window size, not an invented spend figure. Global, missing, malformed and
unknown-window data are omitted; no runtime-wide usage is attributed to a session.

`$/cancel_request` targets an active or queued prompt by its JSON-RPC request ID.
Stale IDs cannot cancel a later turn in the same session. `session/cancel` remains
the whole-turn cancellation interface. Cancellation of short control operations
or session setup is not implemented; partial session deletion is never attempted.
