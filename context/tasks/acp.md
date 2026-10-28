# Penguin ACP implementation and conformance audit

Updated October 28, 2026. This file supersedes the original phase checklist with the implemented state and remaining gates. The stack is draft and unmerged. It is not a claim of complete ACP parity.

## Contract and evidence

Penguin acts as an ACP agent over `penguin acp` stdio. The implementation targets protocol v1 using `agent-client-protocol>=0.12.1,<0.13`, Pydantic 2 and MCP 1.x. It is independent of the A2A HTTP server and MCP tools. The SDK includes resource links; earlier notes claiming it did not were incorrect. Published session deletion and exact prompt-request cancellation need explicit schema-validated transport handlers because the pinned SDK does not route them. Most RPCs and all client RPCs still use the official SDK.

Primary references:
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/docs/protocol/v1/overview.mdx
- https://github.com/agentclientprotocol/agent-client-protocol/blob/main/schema/v1/schema.json
- https://github.com/agentclientprotocol/python-sdk

The current subagent RFD and form elicitation are optional negotiated/experimental behavior. They are not counted as mandatory v1 features, ACP v2 support, or old AIR extensions.

## Implemented and tested

| Area | Behavior and evidence |
| --- | --- |
| Transport and baseline | Real shipped CLI over subprocess stdio, clean stdout, Unicode, malformed frames, supported version negotiation, provider errors and explicit stop reasons. Tests use a deterministic provider core, not a live model. |
| Input | Text and resource references; local URIs confined to authorized cwd after decoding and resolution, remote references never automatically fetched. PNG/JPEG/WebP only on a vision-enabled selected model; bounded embedded text/binary storage. Audio is rejected and not advertised. |
| Ownership | One ACP root session maps to one native conversation and immutable cwd. Indexed ACP metadata is required on reload; legacy or foreign-root sessions are rejected. File reads/writes continue through normal tool permissions. |
| Lifecycle | New, load with ordered replay, resume without replay, list/filter/page, close, delete. Delete checks ownership, rejects active work/unresolved processes, and removes native history, journal and attachments. Close retains history. |
| Long sessions | Append-only replay journal; native model state saved at turn boundaries. Incomplete final append recovery, malformed complete-record rejection, 2,000-chunk linear-write regression. Reload does not inject a whole transcript into model context. |
| Tools | Scoped stable start/result IDs, bounded content, todo plans, terminal failed updates on interruption. Canonical authorized EditService transactions provide native complete before/after snapshots up to limits; other tools retain textual results. |
| Processes | Actual runtime events update independent execution cards after the initiating turn, without polling or consuming model cursors. Retained output, capture failure and exit status shown. Missing root-process handle after reconnect is explicitly unknown. |
| Permissions | Existing policy enforced; ACP offers allow-once or deny. Timeouts, cancel, close and child completion deny pending requests; no late grants. Multiple pending child approvals preserve requires_action until all resolve. |
| Questions | Actual ActionExecutor question tool, negotiated form answers validated before resolution. Unsupported clients receive a text question for their next message; the tool request is rejected immediately so it cannot wait on an absent web UI. Cancel/close rejects forms. |
| Controls | Per-session configured-model selection and Build/Plan modes, busy changes rejected. Plan appears only with permission enforcement and cannot become writable after enforcement is disabled. Settings persist; provider choices must be configured locally. `/status` and `/mcp` are local read-only commands. |
| Usage | Session-scoped current context/window telemetry; unknown/global/malformed values omitted. Cost is not fabricated. |
| MCP | Per-session stdio/HTTP/SSE providers, literal client env values, independent context and permissions; server descriptions resent on reconnect, provider closed on session close. Actual isolated local MCP server contracts. |
| Cancel | Whole-turn session/cancel and exact prompt RPC cancellation through $/cancel_request. Running and queued prompt isolation, stale request IDs and continued use are tested over real stdio. |
| Child agents | Current draft negotiation only. Actual runtime lifecycle/public output, directed messages, child tools, nested parentage and replay. Legacy clients get ordinary parent cards. Independently scheduled background children can be cancelled; foreground children sharing a task cannot claim independent cancel. |

## Deliberate limits and exact remaining work

| Gap | Current decision | Requirement to close it |
| --- | --- | --- |
| Additional directories | Not advertised; requests are rejected. Cwd alone is the immutable workspace boundary. | Carry an immutable authorized-root set through core/tool permissions, MCP resources, child execution and reload, with path-escape tests. Do not broaden access merely because the client sends paths. |
| Client filesystem/terminal RPC | Not invoked. Penguin uses its local tool suite and process owner policy. Clients can still use ACP without implementing these optional RPCs. | Needed for remote editor-owned files/terminals: negotiated routing, permission-preserving policy, handle lifetime, output limits, disconnect cleanup and real remote-client tests. |
| True parallel top-level sessions | A process gate serializes model turns and stateful lifecycle operations because the core conversation manager is shared. Independent runtime background tasks may outlive a turn. | Separate mutable conversation/model/tool state per root session and prove overlapping prompts, models, permissions, reload/close, and cancellation do not contaminate each other. |
| Persisted approvals | Only allow-once/deny are exposed. No always/session allow options or persisted grants. | Define resource/tool scope, revocation and reconnect policy before offering broader authorization. Restoring a transcript never restores a permission grant. |
| Interactive ACP auth/logout | No interactive auth advertised; use normal local Penguin provider setup. | A provider-specific flow with token storage/refresh/revocation and client negotiation. Editor identity must never become tool authority. |
| Extra model configuration | Configured models and modes only; no arbitrary provider/model IDs, effort or sampling knobs. | Add only knobs the selected backend can validate and apply through request-scoped runtime APIs. |
| Other request cancellation | Exact cancellation is for prompts. Atomic/short control operations and session setup do not implement request cancellation. | Explicit lifecycle rollback/resource cleanup for cancellable MCP discovery and session setup; do not partially cancel permanent deletion. |
| Reconnect and recovery | Native conversation and replay persist; live child execution is not resumed after adapter-process death. Historical child association has no cancel authority. Root process cards check only live owned handles; historical child-process cards cannot reconstruct live work. | Durable supervisor identity/ownership and explicit recovery protocol; reconnect must distinguish known live work from unknown outcomes. |
| Advanced UI extensions | No client-specific goal/task panel, arbitrary native tool renderer, hidden reasoning feed, ACP v2 or older AIR shape. Process output uses standard cards. | Negotiate an actual released/compatible client contract and test that client; do not infer parity from extension count. |
| Diff breadth | Complete snapshots only from the canonical authorized async edit path; deleted/oversized files remain textual. | Additional tool producers must expose trustworthy bounded transaction snapshots, not extra unauthorized reads. |
| Real editor/provider acceptance | Not done in this stack. Real CLI/SDK transport with fake provider is proven, not an installed editor or live model. | Launch a supported editor against this branch with a configured provider; exercise multi-turn tools, approve/deny, image, MCP, cancel, close/reopen and persisted replay. Repeat child tests with a client supporting the current draft. |

Windows process termination uses taskkill tree cleanup, not Windows Job Objects or guaranteed ownership of detached descendants. Tests preserve this distinction.

## Draft PR dependency graph

Baseline sequence: #134 baseline -> #135 tool events -> #136 sessions -> #137 rich input -> #138 replay journal -> #139 contract CI -> #140 session MCP -> #141 controls.

`stack/acp-runtime-base` combines that sequence with separate reliability #133. Then #142 child sessions, with sibling #143 native diffs and #144 child approval cleanup. `stack/acp-progress-base` combines those siblings, followed by #145 process UI -> #147 deletion -> #148 questions. `stack/acp-windows-base` combines that stack with Windows runtime #146 (including environment correction), then #149 cross-platform producer tests -> #150 scoped usage -> #151 exact prompt request cancellation. These are Git branch integrations for review, not merged pull requests.

## Validation gates

- [x] Deterministic real stdio CLI/SDK contracts and negative inputs.
- [x] Actual runtime producers: child lifecycle, authorized edit transactions, process output, question tool, persisted usage.
- [x] Dedicated CI on Windows/Linux and Python 3.11/3.12 with ACP dependencies, no provider secrets.
- [x] Windows native process capture and environment assertions; no skipped Windows ACP producer.
- [x] Locked dependency check and scoped Ruff checks.
- [x] Final code aggregate: 111 passed on Windows Python 3.11.14, no skips; scoped Ruff and pinned uv 0.11.2 lock check passed.
- [ ] Final code-head CI completion recorded after the last increment.
- [ ] Real editor plus live-provider acceptance as specified above.
- [ ] All optional decisions above revisited before claiming parity for a particular remote/advanced client.

Final code aggregate after #151: 111 ACP, native Windows process and environment-policy checks passed, with no skips, on Windows Python 3.11.14. Scoped Ruff and the pinned uv 0.11.2 lock check passed. #149's entire CI, including four ACP matrix jobs, passed; #151 CI was still running when this audit was prepared. Older full-repository failures must be reported separately, not hidden by focused results.
