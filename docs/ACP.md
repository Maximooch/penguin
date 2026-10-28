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
returning; resume
restores without replay; close detaches without deleting history. List supports
workspace filtering and pagination. Legacy sessions without ACP ownership are
not exposed. Interrupted tool entries replay as failed, without re-execution.
Turns and lifecycle operations are serialized because the core conversation
manager is shared. Embedded context is supported with persistent attachment
storage. PNG/JPEG/WebP image input is advertised only for a vision-enabled model.
Client MCP, configuration, child-session and deletion capabilities are not
advertised yet. Do not interpret this as full ACP parity.

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
5. Per-session client MCP servers.
6. Model/mode/configuration and command discovery/authentication where supported.
7. Child-agent and background-task visibility using negotiated capabilities.
8. Remaining client filesystem/terminal integration, concurrency and interop audit.

Stable v1 requirements and negotiated optional capabilities are separate from
draft v2, draft subagent protocols and client-specific AIR extensions. Each PR
must document precisely what it advertises and proves. The process/subagent
runtime reliability PR is a dependency of later runtime-backed integrations,
not part of the baseline.
